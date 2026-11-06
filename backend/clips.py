import asyncio
import os
import re
import subprocess
import tempfile
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

import logging

import telegram_bot
from detection import encode_jpeg

logger = logging.getLogger("clips")

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


# ---------------------------------------------------------------- cartella dei video (1.0.5)
# Prima le clip stavano DENTRO il database (non si vedevano da Esplora file e il database cresceva).
# Ora sono file .mp4 in <cartella>/<AAAA-MM-GG>/<telecamera>_<HHMMSS>_<id>.mp4.

def default_clips_dir() -> Path:
    return Path(os.environ.get("SENTINEL_CLIPS_DIR") or Path(os.environ.get("DATA_DIR", ".")) / "clip").resolve()


def check_folder(folder) -> str | None:
    """None se nella cartella si può scrivere (la crea se manca), altrimenti il motivo."""
    try:
        p = Path(folder)
        if not p.is_absolute():
            return "serve un percorso completo (es. D:\\Video\\SentinelAI)"
        p.mkdir(parents=True, exist_ok=True)
        test = p / f".prova-scrittura-{uuid.uuid4().hex[:6]}"
        test.write_bytes(b"ok")
        test.unlink()
        return None
    except OSError as exc:
        return f"non si può scrivere ({exc.strerror or exc})"


def clips_dir(settings) -> tuple[Path | None, str | None]:
    """Cartella da usare adesso e un avviso se quella scelta non è disponibile (NAS spento, chiavetta tolta...)."""
    want = (getattr(settings, "clips_folder", "") or "").strip()
    if want:
        err = check_folder(want)
        if not err:
            return Path(want), None
        warn = f"La cartella scelta ({want}) non è disponibile: {err}. Uso quella predefinita."
    else:
        warn = None
    d = default_clips_dir()
    err = check_folder(d)
    if err:
        return None, f"Nessuna cartella per i video disponibile ({err}): le clip restano nel database."
    return d, warn


def _safe(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "_", name or "").strip()[:40] or "telecamera"


def save_clip_file(settings, data: bytes, camera_name: str, clip_id: str, wall_utc: datetime, tz_offset: int):
    """Scrive la clip su file. Restituisce (percorso, avviso); percorso None = resta nel database."""
    folder, warn = clips_dir(settings)
    if folder is None:
        return None, warn
    local = wall_utc - timedelta(minutes=tz_offset)
    day = folder / local.strftime("%Y-%m-%d")
    try:
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"{_safe(camera_name)}_{local.strftime('%H%M%S')}_{clip_id[:6]}.mp4"
        tmp = path.with_suffix(".mp4.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)     # disco pieno: niente .tmp abbandonati
            except OSError:
                pass
            raise
        return path, warn
    except OSError as exc:
        return None, f"Video non salvato nella cartella ({exc}): resta nel database."


def same_place(a, b) -> bool:
    """Stessa cartella o stesso file anche se scritti diversamente (Z:\\ e \\\\nas\\..., link, ..)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        try:
            return Path(a).resolve() == Path(b).resolve()
        except OSError:
            return False


def _no_window() -> dict:
    """Su Windows ffmpeg partiva con una finestra nera del prompt che si apriva e chiudeva a ogni clip (1.0.6)."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0                                   # SW_HIDE
    return {"creationflags": 0x08000000, "startupinfo": si}   # CREATE_NO_WINDOW


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
        subprocess.run(cmd, input=b"".join(j for _, j in frames), check=True, capture_output=True, timeout=120,
                       **_no_window())
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
        self.active = {"id": cid, "frames": frames, "start": start, "until": now + s.clip_post_seconds, "events": [event_id],
                       "wall": datetime.now(timezone.utc) - timedelta(seconds=max(0.0, now - start))}
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
            fields = {"status": status, "duration": duration, "frames": len(rec["frames"]), "size": len(data)}
            path = None
            if data:
                path, warn = await asyncio.to_thread(save_clip_file, self.settings, data, self.camera.name, rec["id"],
                                                     rec.get("wall") or datetime.now(timezone.utc), self.tz_offset)
                if warn:
                    logger.warning("[%s] %s", self.camera.name, warn)
            if path:
                fields["file"] = str(path)
            else:
                fields["data"] = data        # nessuna cartella utilizzabile: come prima, nel database
            await self.db.clips.update_one({"id": rec["id"]}, {"$set": fields})
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
