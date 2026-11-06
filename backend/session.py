"""Sessione di analisi di una telecamera: riconoscimento, linea virtuale, zone, mappa di calore, clip.

Ricostruita il 05/11/2026: save_event e add_heat seguono i pezzi originali, il resto segue
quello che il frontend si aspetta (tracks, events, counts, fps, zones_active)."""
import asyncio
import base64
import logging
import math
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import cv2
from fastapi import WebSocket

import telegram_bot
from clips import ClipRecorder
from detection import COCO_IT, Tracker, annotated_snapshot, category_of, detector, encode_jpeg, heading_of, line_side, within_segment
from models import HEAT_H, HEAT_W, Camera, Event, Settings, Zone

logger = logging.getLogger(__name__)

HEAT_FLUSH_SECONDS = 15
LINE_MARGIN = 0.015       # frazione dell'inquadratura: dentro questa fascia attorno alla linea non si cambia lato
LINE_COOLDOWN = 0.4       # secondi prima che la stessa traccia possa riattraversare (i tremolii li filtra LINE_CONFIRM)
LINE_CONFIRM = 3          # fotogrammi di fila sul lato nuovo per contare un passaggio "lento"...
LINE_STRONG = 0.045       # ...ma se è già ben oltre la linea (3 margini) basta un fotogramma: niente passaggi veloci persi
LINE_ARM = 0.07           # un passaggio conta solo se prima l'oggetto è stato DAVVERO lontano dall'altra parte
ZONE_EXIT_GRACE = 1.5     # secondi fuori dalla zona prima di considerarla davvero uscita
BACKGROUND_SECONDS = 60


def local_tz_offset() -> int:
    """Come Date.getTimezoneOffset() di JavaScript: UTC - ora locale, in minuti (Italia d'inverno: -60)."""
    return -round(datetime.now().astimezone().utcoffset().total_seconds() / 60)


def in_window(now_hm: str, start: str, end: str) -> bool:
    return start <= now_hm <= end if start <= end else (now_hm >= start or now_hm <= end)


def match_rule(settings: Settings, category: str, direction: Optional[str], tz_offset: int):
    local_hm = (datetime.now(timezone.utc) - timedelta(minutes=tz_offset)).strftime("%H:%M")
    for r in settings.alert_rules:
        if not r.enabled or (r.categories and category not in r.categories):
            continue
        if r.direction != "any" and r.direction != direction:
            continue
        if in_window(local_hm, r.start, r.end):
            return r.name
    return None


def line_distance(line, px, py) -> float:
    """Distanza con segno dalla linea (stesso segno di line_side), in frazioni dell'inquadratura."""
    lx, ly = line["x2"] - line["x1"], line["y2"] - line["y1"]
    return (lx * (py - line["y1"]) - ly * (px - line["x1"])) / (math.hypot(lx, ly) or 1e-9)


def coherent_crossing(line, history, side) -> bool:
    """Gli ultimi 3 punti della traccia si muovono tutti verso il lato nuovo, per almeno 2 volte LINE_STRONG."""
    pts = list(history)[-3:]
    if len(pts) < 3:
        return False
    d = [line_distance(line, x, y) * side for x, y in pts]
    return d[0] < d[1] < d[2] and d[2] - d[0] >= 2 * LINE_STRONG


def point_in_polygon(x: float, y: float, pts) -> bool:
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


class StreamSession:
    def __init__(self, db, camera: Camera, settings: Settings, tz_offset: Optional[int]):
        # tz_offset None = ora locale del computer, ricalcolata (segue l'ora legale senza riavviare).
        self.auto_tz = tz_offset is None
        tz_offset = local_tz_offset() if tz_offset is None else tz_offset
        self.db, self.camera, self.settings, self.tz_offset = db, camera, settings, tz_offset
        self.tracker = Tracker()
        self.counts = {"in": 0, "out": 0}
        self.frame_times: list[float] = []
        self.recorder = ClipRecorder(db, camera, settings, tz_offset)
        self.heat: dict[str, dict[str, int]] = {}
        self.heat_tracks: dict[str, int] = {}
        self.heat_seen: set[int] = set()
        self.last_flush = time.monotonic()
        self.last_background = 0.0
        # track_id -> zone_id -> {"since": istante d'ingresso, "dwell": allarme di sosta già dato}
        self.zone_state: dict[int, dict[str, dict]] = {}

    def update(self, camera: Camera, settings: Settings):
        self.camera, self.settings = camera, settings
        self.recorder.camera, self.recorder.settings = camera, settings

    async def save_event(self, etype, tr, direction, snap, zone: Optional[Zone] = None):
        src = tr.history if etype == "attraversamento" else [tr.first, tr.history[-1]]
        dx, dy = src[-1][0] - src[0][0], src[-1][1] - src[0][1]
        name, arrow, ang = heading_of(dx, dy, 0.0)
        cat = category_of(tr.cls)
        rule = f"Zona «{zone.name}»" if zone else match_rule(self.settings, cat, direction, self.tz_offset)
        eid = str(uuid.uuid4())
        clip_id = await self.recorder.trigger(time.monotonic(), eid) if rule else None
        ev = Event(id=eid, clip_id=clip_id, type=etype, source=self.camera.type, camera_id=self.camera.id,
                   camera_name=self.camera.name, zone_name=zone.name if zone else None, class_id=tr.cls,
                   class_name=COCO_IT[tr.cls], category=cat, direction=direction, heading=name, arrow=arrow,
                   angle=ang, confidence=round(tr.conf, 3), track_id=tr.id, alert=bool(rule), alert_rule=rule,
                   has_snapshot=bool(snap), timestamp=datetime.now(timezone.utc))
        doc = ev.model_dump()
        doc["timestamp"] = ev.timestamp.isoformat()
        await self.db.events.insert_one(doc)
        if snap:
            await self.db.snapshots.insert_one({"event_id": ev.id, "data": snap, "timestamp": doc["timestamp"]})
        out = {**ev.model_dump(), "timestamp": doc["timestamp"]}
        if rule:
            telegram_bot.send_photo_bg(self.settings, out, snap, self.tz_offset)
        return out

    def add_heat(self, tr):
        cx, cy = tr.history[-1]
        cell = min(HEAT_H - 1, max(0, int(cy * HEAT_H))) * HEAT_W + min(HEAT_W - 1, max(0, int(cx * HEAT_W)))
        cat = category_of(tr.cls)
        cells = self.heat.setdefault(cat, {})
        cells[str(cell)] = cells.get(str(cell), 0) + 1
        if tr.id not in self.heat_seen and tr.hits >= 3:
            self.heat_seen.add(tr.id)
            self.heat_tracks[cat] = self.heat_tracks.get(cat, 0) + 1

    async def flush_heat(self):
        heat, tracks = self.heat, self.heat_tracks
        self.heat, self.heat_tracks = {}, {}
        for cat in set(heat) | set(tracks):
            inc = {f"cells.{k}": v for k, v in heat.get(cat, {}).items()}
            if tracks.get(cat):
                inc["tracks"] = tracks[cat]
            if inc:
                await self.db.heatmaps.update_one({"camera_id": self.camera.id, "category": cat}, {"$inc": inc}, upsert=True)

    async def save_background(self, frame):
        jpeg = await asyncio.to_thread(encode_jpeg, frame, 960, 70)
        await self.db.backgrounds.replace_one(
            {"camera_id": self.camera.id},
            {"camera_id": self.camera.id, "data": jpeg, "timestamp": datetime.now(timezone.utc).isoformat()}, upsert=True)

    async def _count_crossing(self, frame, tr, side, now, events, inside_segment):
        tr.pending = 0
        tr.side = side
        tr.armed = side if abs(line_distance(self.camera.line.model_dump(), *tr.history[-1])) >= LINE_ARM else None
        if not inside_segment:
            return
        direction = "IN" if (side > 0) != self.camera.line.invert else "OUT"
        self.counts["in" if direction == "IN" else "out"] += 1
        tr.crossed = True
        tr.last_cross = now
        snap = await asyncio.to_thread(annotated_snapshot, frame, tr.box, f"{COCO_IT[tr.cls]} {direction}")
        events.append(await self.save_event("attraversamento", tr, direction, snap))

    async def check_zones(self, frame, tr, now, events, active_zones):
        cat = category_of(tr.cls)
        bx, by = (tr.box[0] + tr.box[2]) / 2, tr.box[3]   # base dell'oggetto (i piedi per le persone)
        state = self.zone_state.setdefault(tr.id, {})
        for z in self.camera.zones:
            if not z.enabled or (z.categories and cat not in z.categories):
                continue
            if not point_in_polygon(bx, by, z.points):
                # 06/11/2026 (agente di prova): chi sta sul bordo entrava e usciva a ogni fotogramma: allarmi
                # di ingresso a raffica e la sosta non scattava mai. Ora si esce solo dopo ZONE_EXIT_GRACE s fuori.
                st = state.get(z.id)
                if st is not None:
                    st.setdefault("out_since", now)
                    if now - st["out_since"] >= ZONE_EXIT_GRACE:
                        state.pop(z.id, None)
                continue
            active_zones.add(z.id)
            st = state.get(z.id)
            if st is None:
                st = state[z.id] = {"since": now, "dwell": False, "entered": False}
            st.pop("out_since", None)
            # 06/11/2026: prima l'allarme partiva solo se al primo istante dentro la zona la traccia era già
            # confermata (3 rilevamenti): chi compariva direttamente nella zona non dava MAI l'allarme.
            if z.alert_on_enter and not st["entered"] and tr.hits >= 3:
                st["entered"] = True
                snap = await asyncio.to_thread(annotated_snapshot, frame, tr.box, f"{COCO_IT[tr.cls]} · {z.name}")
                events.append(await self.save_event("zona_ingresso", tr, None, snap, z))
            if z.dwell_seconds and not st["dwell"] and now - st["since"] >= z.dwell_seconds:
                st["dwell"] = True
                snap = await asyncio.to_thread(annotated_snapshot, frame, tr.box, f"{COCO_IT[tr.cls]} sosta · {z.name}")
                events.append(await self.save_event("zona_sosta", tr, None, snap, z))

    async def process(self, frame):
        s = self.settings
        now = time.monotonic()
        if self.auto_tz:
            self.tz_offset = self.recorder.tz_offset = local_tz_offset()
        dets = await asyncio.to_thread(detector.detect, frame, s.conf, s.iou, s.classes)
        active, expired = self.tracker.update(dets, now)
        events, line, active_zones = [], self.camera.line.model_dump(), set()
        for tr in active:
            cx, cy = tr.history[-1]
            if tr.conf > tr.snap_conf + 0.05:
                tr.snap = await asyncio.to_thread(annotated_snapshot, frame, tr.box, f"{COCO_IT[tr.cls]} {tr.conf:.2f}")
                tr.snap_conf = tr.conf
            self.add_heat(tr)
            await self.check_zones(frame, tr, now, events, active_zones)
            if not line["enabled"]:
                continue
            # 06/11/2026 (agente di prova): una persona ferma SULLA linea, con il centro che trema di poco,
            # veniva contata decine di volte (IN/OUT/IN...), con allarmi, clip e Telegram a raffica.
            # Ora: isteresi (si cambia lato solo allontanandosi di LINE_MARGIN dalla linea) e, per la stessa
            # traccia, un nuovo passaggio conta solo dopo LINE_COOLDOWN secondi.
            dist = line_distance(line, cx, cy)
            if abs(dist) < LINE_MARGIN:
                continue
            side = 1 if dist > 0 else -1
            # 4° giro dell'agente: il tremolio CASUALE di chi sta fermo sulla linea dava ancora conteggi.
            # "Armato": l'oggetto è stato lontano dalla linea (LINE_ARM) da un lato; solo così il passaggio
            # verso l'altro lato conta. Dopo un conteggio si disarma finché non è di nuovo lontano.
            if tr.side is None:
                tr.side = side
                if abs(dist) >= LINE_ARM:
                    tr.armed = side
                continue
            if side == tr.side:
                tr.pending = 0
                if abs(dist) >= LINE_ARM:   # si arma solo il lato GIÀ confermato, mai quello verso cui va
                    tr.armed = side
                continue
            # 2° giro dell'agente: con tremolii più ampi del margine contava ancora. Ora il lato nuovo deve
            # durare LINE_CONFIRM fotogrammi di fila, e durante il cooldown il lato vecchio resta quello buono
            # (così un ritorno indietro rapido viene contato, invece di perdersi).
            tr.pending = getattr(tr, "pending", 0) + 1
            # 3° giro dell'agente: con la sola conferma su 3 fotogrammi un'auto veloce (2 fotogrammi oltre la linea)
            # non veniva contata. Ora basta 1 fotogramma se è già ben oltre (LINE_STRONG); i tremolii restano sotto.
            # 4° giro dell'agente: il fotogramma singolo "forte" contava anche il tremolio ampio (±0,05).
            # Ora vale solo se gli ultimi 3 punti vanno tutti nella stessa direzione e si spostano davvero.
            confirmed = tr.pending >= LINE_CONFIRM or (abs(dist) >= LINE_STRONG and coherent_crossing(line, tr.history, side))
            if not confirmed or now - getattr(tr, "last_cross", -1e9) < LINE_COOLDOWN:
                continue
            if getattr(tr, "armed", None) != -side:
                tr.side, tr.pending = side, 0     # cambio di lato senza venire da lontano: non è un passaggio
                continue
            await self._count_crossing(frame, tr, side, now, events, within_segment(line, cx, cy))
        for tr in expired:
            self.zone_state.pop(tr.id, None)
            self.heat_seen.discard(tr.id)
            disp = math.hypot(tr.history[-1][0] - tr.first[0], tr.history[-1][1] - tr.first[1])
            if not tr.crossed and tr.hits >= 5 and disp >= s.transit_min_dist:
                events.append(await self.save_event("transito", tr, None, tr.snap))
        self.frame_times = [t for t in self.frame_times if now - t < 2] + [now]
        tracks = []
        for tr in active:
            hx = tr.history[-1][0] - tr.history[0][0]
            hy = tr.history[-1][1] - tr.history[0][1]
            name, arrow, ang = heading_of(hx, hy)
            tracks.append({"id": tr.id, "class_id": tr.cls, "label": COCO_IT[tr.cls], "category": category_of(tr.cls),
                           "conf": round(tr.conf, 3), "box": [round(v, 4) for v in tr.box], "heading": name,
                           "arrow": arrow, "angle": ang, "dx": round(hx, 4), "dy": round(hy, 4)})
        await self.recorder.push(now, frame, tracks)
        if now - self.last_flush >= HEAT_FLUSH_SECONDS:
            self.last_flush = now
            await self.flush_heat()
        if now - self.last_background >= BACKGROUND_SECONDS:
            self.last_background = now
            await self.save_background(frame)
        return {"tracks": tracks, "events": events, "counts": self.counts,
                "fps": round(len(self.frame_times) / 2, 1), "zones_active": sorted(active_zones)}

    async def close(self):
        with_errors = []
        for step in (self.flush_heat, self.recorder.close):
            try:
                await step()
            except Exception as exc:  # una chiusura sporca non deve far perdere l'altra
                with_errors.append(exc)
        for exc in with_errors:
            logger.error("chiusura sessione %s: %s", self.camera.id, exc)


def open_capture(url: str):
    if url.lower().startswith("rtsp"):
        # TCP: con l'UDP i flussi degli NVR perdono pezzi e l'immagine si riempie di macchie grigie.
        # "timeout" (µs): con l'FFmpeg 5 di OpenCV 4.10 "stimeout" non esiste più e non aveva effetto.
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;10000000")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


class LatestFrame:
    """Legge il flusso dal vivo in un thread e tiene solo l'ultimo fotogramma: niente ritardo che si accumula
    quando l'analisi è più lenta della telecamera."""

    def __init__(self, cap):
        self.cap, self.frame, self.seq, self.ok = cap, None, 0, True
        self.cond = threading.Condition()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            while self.ok:
                ok, frame = self.cap.read()
                with self.cond:
                    if not ok:
                        self.ok = False
                    else:
                        self.frame, self.seq = frame, self.seq + 1
                    self.cond.notify_all()
        finally:
            self.cap.release()   # lo chiude il thread che legge, mai mentre sta leggendo

    def wait(self, last_seq, timeout=10):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq or not self.ok, timeout)
            return (self.frame, self.seq) if self.seq != last_seq else (None, last_seq)

    def stop(self):
        self.ok = False


async def network_loop(ws: WebSocket, session: StreamSession, url: str):
    """Flussi letti dal server (RTSP / NVR / URL http): il server manda al browser i fotogrammi già analizzati."""
    cap = await asyncio.to_thread(open_capture, url)
    if not cap.isOpened():
        await ws.send_json({"type": "error", "message": "Impossibile aprire il flusso. Verifica indirizzo, utente e password."})
        return
    is_file = not url.lower().startswith(("rtsp", "rtmp"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    reader = None if is_file else LatestFrame(cap)
    await ws.send_json({"type": "ready"})
    seq = 0
    try:
        while True:
            t0 = time.monotonic()
            if reader:
                frame, seq = await asyncio.to_thread(reader.wait, seq)
                ok = frame is not None
            else:
                ok, frame = await asyncio.to_thread(cap.read)
            if not ok:
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                await ws.send_json({"type": "error", "message": "Flusso interrotto."})
                break
            result = await session.process(frame)
            img = await asyncio.to_thread(encode_jpeg, frame, 960, 70)
            h, w = frame.shape[:2]
            await ws.send_json({"type": "frame", "image": base64.b64encode(img).decode(), "width": w, "height": h, **result})
            if is_file:
                # Un file va alla sua velocità: si saltano i fotogrammi persi mentre si analizzava.
                for _ in range(max(0, int((time.monotonic() - t0) * fps) - 1)):
                    await asyncio.to_thread(cap.grab)
    finally:
        if reader:
            reader.stop()
        else:
            await asyncio.to_thread(cap.release)
