import asyncio
import os
import subprocess
import tempfile
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

import telegram_bot
from detection import encode_jpeg

MAX_CLIP_SECONDS = 30
_SENDING: set = set()   # invii a Telegram in corso (riferimenti tenuti per non perderli)
CAT_BGR = {"persona": (129, 185, 16), "veicolo": (212, 182, 6), "animale": (11, 158, 245), "oggetto": (182, 114, 244)}


def annotate_frame(frame, tracks, caption):
    h, w = frame.shape[:2]
    scale = min(1.0, 640 / w)
    img = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1 else frame.copy()
    ih, iw = img.shape[:2]
    for t in tracks:
        if t.get("fixed"):
            continue          # cose ferme (mai mosse): non si disegnano nella clip
        c = CAT_BGR.get(t["category"], (255, 255, 255))
        x1, y1, x2, y2 = (int(t["box"][0] * iw), int(t["box"][1] * ih), int(t["box"][2] * iw), int(t["box"][3] * ih))
        cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
        cv2.putText(img, f"#{t['id']} {t['label']} {t['heading']}", (x1, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
    cv2.rectangle(img, (0, ih - 22), (iw, ih), (20, 13, 9), -1)
    cv2.putText(img, caption, (8, ih - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
    return encode_jpeg(img, 640, 70)


def _encode_opencv(frames, fps, path):
    """Versione Windows: H.264 col codificatore di sistema (Media Foundation), niente ffmpeg da allegare."""
    first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
    h, w = first.shape[:2]
    w, h = w - w % 2, h - h % 2
    api = cv2.CAP_MSMF if os.name == "nt" else cv2.CAP_ANY
    for code in ("avc1", "H264"):
        vw = cv2.VideoWriter(path, api, cv2.VideoWriter_fourcc(*code), fps, (w, h))
        if vw.isOpened():
            break
    else:
        raise RuntimeError("nessun codificatore H.264 disponibile")
    try:
        for _, jpg in frames:
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                vw.write(cv2.resize(img, (w, h)) if img.shape[1] != w or img.shape[0] != h else img)
    finally:
        vw.release()


def encode_mp4(frames):
    if len(frames) < 2:
        return b"", 0.0
    duration = max(0.5, frames[-1][0] - frames[0][0])
    fps = max(1.0, min(30.0, (len(frames) - 1) / duration))
    duration = len(frames) / fps
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        try:
            import imageio_ffmpeg
        except ImportError:
            _encode_opencv(frames, fps, path)
            with open(path, "rb") as f:
                return f.read(), round(duration, 1)
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", f"{fps:.3f}",
               "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p", "-color_range", "tv",
               "-movflags", "+faststart", path]
        subprocess.run(cmd, input=b"".join(j for _, j in frames), check=True, capture_output=True, timeout=120)
        with open(path, "rb") as f:
            return f.read(), round(duration, 1)
    finally:
        os.remove(path)


class ClipRecorder:
    def __init__(self, db, camera, settings, tz_offset):
        self.db, self.camera, self.settings, self.tz_offset = db, camera, settings, tz_offset
        self.buffer: deque = deque()
        self.active = None
        self.tasks: set = set()

    def caption(self):
        local = datetime.now(timezone.utc) - timedelta(minutes=self.tz_offset)
        return f"{self.camera.name}  {local.strftime('%d/%m/%Y %H:%M:%S')}"

    async def trigger(self, now, event_id) -> str | None:
        s = self.settings
        if not s.clips_enabled:
            return None
        if self.active:
            r = self.active
            r["until"] = min(r["start"] + MAX_CLIP_SECONDS, max(r["until"], now + s.clip_post_seconds))
            r["events"].append(event_id)
            await self.db.clips.update_one({"id": r["id"]}, {"$push": {"event_ids": event_id}})
            return r["id"]
        cid = str(uuid.uuid4())
        frames = list(self.buffer)
        start = frames[0][0] if frames else now
        self.active = {"id": cid, "frames": frames, "start": start, "until": now + s.clip_post_seconds, "events": [event_id]}
        await self.db.clips.insert_one({"id": cid, "status": "recording", "camera_id": self.camera.id, "camera_name": self.camera.name,
                                        "event_ids": [event_id], "timestamp": datetime.now(timezone.utc).isoformat()})
        return cid

    async def push(self, now, frame, tracks):
        if not self.settings.clips_enabled and not self.active:
            self.buffer.clear()
            return
        jpeg = await asyncio.to_thread(annotate_frame, frame, tracks, self.caption())
        self.buffer.append((now, jpeg))
        while self.buffer and now - self.buffer[0][0] > self.settings.clip_pre_seconds:
            self.buffer.popleft()
        if self.active:
            self.active["frames"].append((now, jpeg))
            if now >= self.active["until"]:
                self.finish()

    def finish(self):
        rec, self.active = self.active, None
        if rec:
            t = asyncio.create_task(self.finalize(rec))
            self.tasks.add(t)
            t.add_done_callback(self.tasks.discard)

    async def finalize(self, rec):
        try:
            data, duration = await asyncio.to_thread(encode_mp4, rec["frames"])
            status = "ready" if data else "failed"
            await self.db.clips.update_one({"id": rec["id"]}, {"$set": {"status": status, "data": data, "duration": duration,
                                                                         "frames": len(rec["frames"]), "size": len(data)}})
            if data:
                # 06/11/2026 (agente di prova): l'invio a Telegram (fino a minuti) non deve far aspettare
                # Ferma, la modifica della telecamera o l'uscita dal programma.
                t = asyncio.create_task(telegram_bot.send_clip(self.settings, data, rec.get("caption") or "🎬 Clip allarme"))
                _SENDING.add(t)
                t.add_done_callback(_SENDING.discard)
        except Exception:
            await self.db.clips.update_one({"id": rec["id"]}, {"$set": {"status": "failed"}})

    async def close(self):
        self.finish()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
