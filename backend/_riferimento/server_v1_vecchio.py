# VERSIONE VECCHIA di server.py (prima che venisse divisa in models.py / session.py e prima di
# telecamere multiple, clip, heatmap, Telegram e login Clerk). Tenuta solo come riferimento
# per ricostruire il backend attuale. Recuperata dalla chat di Emergent il 05/11/2026.
import asyncio
import base64
import io
import logging
import math
import os
import time
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Literal, Optional

import cv2
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, IndexModel
from starlette.middleware.cors import CORSMiddleware

from detection import (COCO_IT, DEFAULT_CLASSES, Tracker, annotated_snapshot, category_of, detector, encode_jpeg,
                       heading_of, line_side, within_segment)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

INDEXES: dict[str, list[IndexModel]] = {
    "events": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("timestamp", DESCENDING)], name="timestamp_desc"),
        IndexModel([("category", ASCENDING), ("timestamp", DESCENDING)], name="category_ts"),
    ],
    "snapshots": [IndexModel([("event_id", ASCENDING)], name="event_id", unique=True)],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)


app = FastAPI()
api = APIRouter(prefix="/api")


class Line(BaseModel):
    enabled: bool = True
    x1: float = 0.08
    y1: float = 0.62
    x2: float = 0.92
    y2: float = 0.62
    invert: bool = False


class AlertRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    enabled: bool = True
    categories: List[str] = []
    direction: Literal["any", "IN", "OUT"] = "any"
    start: str = "00:00"
    end: str = "23:59"


class Settings(BaseModel):
    conf: float = Field(0.4, ge=0.05, le=0.99)
    iou: float = Field(0.5, ge=0.1, le=0.95)
    classes: List[int] = DEFAULT_CLASSES
    line: Line = Line()
    transit_min_dist: float = Field(0.18, ge=0.0, le=1.0)
    sound: bool = True
    desktop_notifications: bool = True
    alert_rules: List[AlertRule] = [
        AlertRule(name="Persona in orario notturno", categories=["persona"], start="22:00", end="06:00"),
        AlertRule(name="Veicolo in entrata", categories=["veicolo"], direction="IN", enabled=False),
    ]


class Event(BaseModel):
    id: str
    type: Literal["attraversamento", "transito"]
    source: str
    class_id: int
    class_name: str
    category: str
    direction: Optional[str] = None
    heading: str
    arrow: str
    angle: Optional[float] = None
    confidence: float
    track_id: int
    alert: bool = False
    alert_rule: Optional[str] = None
    has_snapshot: bool = False
    timestamp: datetime


async def load_settings() -> Settings:
    doc = await db.settings.find_one({"_id": "global"})
    if not doc:
        return Settings()
    doc.pop("_id", None)
    return Settings(**doc)


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


class StreamSession:
    def __init__(self, settings: Settings, source: str, tz_offset: int):
        self.settings, self.source, self.tz_offset = settings, source, tz_offset
        self.tracker = Tracker()
        self.counts = {"in": 0, "out": 0}
        self.frame_times: list[float] = []

    async def save_event(self, etype, tr, direction, snap):
        dx, dy = tr.history[-1][0] - tr.first[0], tr.history[-1][1] - tr.first[1]
        if etype == "attraversamento":
            dx, dy = tr.history[-1][0] - tr.history[0][0], tr.history[-1][1] - tr.history[0][1]
        name, arrow, ang = heading_of(dx, dy, 0.0)
        cat = category_of(tr.cls)
        rule = match_rule(self.settings, cat, direction, self.tz_offset)
        ev = Event(id=str(uuid.uuid4()), type=etype, source=self.source, class_id=tr.cls, class_name=COCO_IT[tr.cls],
                   category=cat, direction=direction, heading=name, arrow=arrow, angle=ang,
                   confidence=round(tr.conf, 3), track_id=tr.id, alert=bool(rule), alert_rule=rule,
                   has_snapshot=bool(snap), timestamp=datetime.now(timezone.utc))
        doc = ev.model_dump()
        doc["timestamp"] = ev.timestamp.isoformat()
        await db.events.insert_one(doc)
        if snap:
            await db.snapshots.insert_one({"event_id": ev.id, "data": snap})
        out = ev.model_dump()
        out["timestamp"] = doc["timestamp"]
        return out

    async def process(self, frame):
        s = self.settings
        now = time.monotonic()
        dets = await asyncio.to_thread(detector.detect, frame, s.conf, s.iou, s.classes)
        active, expired = self.tracker.update(dets, now)
        events, line = [], s.line.model_dump()
        for tr in active:
            cx, cy = tr.history[-1]
            if tr.conf > tr.snap_conf + 0.05:
                tr.snap = await asyncio.to_thread(annotated_snapshot, frame, tr.box, f"{COCO_IT[tr.cls]} {tr.conf:.2f}")
                tr.snap_conf = tr.conf
            if not line["enabled"]:
                continue
            side = line_side(line, cx, cy)
            if side == 0:
                continue
            if tr.side is not None and side != tr.side and within_segment(line, cx, cy):
                direction = "IN" if (side > 0) != line["invert"] else "OUT"
                self.counts["in" if direction == "IN" else "out"] += 1
                tr.crossed = True
                snap = await asyncio.to_thread(annotated_snapshot, frame, tr.box, f"{COCO_IT[tr.cls]} {direction}")
                events.append(await self.save_event("attraversamento", tr, direction, snap))
            tr.side = side
        for tr in expired:
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
        return {"tracks": tracks, "events": events, "counts": self.counts,
                "fps": round(len(self.frame_times) / 2, 1)}


def open_capture(url: str):
    cap = cv2.VideoCapture(url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


async def network_loop(ws: WebSocket, session: StreamSession, url: str):
    cap = await asyncio.to_thread(open_capture, url)
    if not cap.isOpened():
        await ws.send_json({"type": "error", "message": "Impossibile aprire il flusso. Verifica l'URL RTSP/HTTP."})
        return
    is_file = not url.lower().startswith(("rtsp", "rtmp"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    await ws.send_json({"type": "ready"})
    try:
        while True:
            t0 = time.monotonic()
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
                for _ in range(max(0, int((time.monotonic() - t0) * fps) - 1)):
                    await asyncio.to_thread(cap.grab)
    finally:
        cap.release()


@api.websocket("/ws/stream")
async def stream_ws(ws: WebSocket):
    await ws.accept()
    session: Optional[StreamSession] = None
    net_task: Optional[asyncio.Task] = None
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if session is None:
                    continue
                frame = cv2.imdecode(np.frombuffer(msg["bytes"], np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    await ws.send_json({"type": "detections", "tracks": [], "events": [], "counts": session.counts, "fps": 0})
                    continue
                await ws.send_json({"type": "detections", **(await session.process(frame))})
                continue
            import json
            data = json.loads(msg.get("text") or "{}")
            kind = data.get("type")
            if kind == "start":
                session = StreamSession(await load_settings(), data.get("source", "webcam"), int(data.get("tz_offset", 0)))
                if data.get("source") == "rtsp":
                    net_task = asyncio.create_task(network_loop(ws, session, data.get("url", "")))
                else:
                    await ws.send_json({"type": "ready"})
            elif kind == "reload" and session:
                session.settings = await load_settings()
            elif kind == "reset" and session:
                session.counts = {"in": 0, "out": 0}
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("stream error: %s", exc)
    finally:
        if net_task:
            net_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await net_task


@api.get("/")
async def root():
    return {"message": "SentinelAI attivo", "model_loaded": detector.model is not None}


@api.get("/health")
async def health():
    return {"status": "ok", "model": "YOLOv8n (locale)", "model_loaded": detector.model is not None}


@api.get("/classes")
async def classes():
    return [{"id": i, "name": n, "category": category_of(i)} for i, n in enumerate(COCO_IT)]


@api.get("/settings", response_model=Settings)
async def get_settings():
    return await load_settings()


@api.put("/settings", response_model=Settings)
async def put_settings(s: Settings):
    await db.settings.replace_one({"_id": "global"}, s.model_dump(), upsert=True)
    return s


def events_filter(category, direction, etype, alert_only, hours):
    q: dict = {}
    if category:
        q["category"] = category
    if direction:
        q["direction"] = direction
    if etype:
        q["type"] = etype
    if alert_only:
        q["alert"] = True
    if hours:
        q["timestamp"] = {"$gte": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()}
    return q


@api.get("/events", response_model=List[Event])
async def list_events(limit: int = Query(100, ge=1, le=1000), category: Optional[str] = None,
                      direction: Optional[str] = None, type: Optional[str] = None, alert_only: bool = False,
                      hours: Optional[int] = None):
    q = events_filter(category, direction, type, alert_only, hours)
    docs = await db.events.find(q, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return [Event(**d) for d in docs]


@api.get("/events/export")
async def export_events(format: Literal["csv", "xlsx"] = "csv", category: Optional[str] = None,
                        direction: Optional[str] = None, type: Optional[str] = None, hours: Optional[int] = None,
                        tz_offset: int = 0):
    q = events_filter(category, direction, type, False, hours)
    docs = await db.events.find(q, {"_id": 0}).sort("timestamp", -1).to_list(50000)
    rows = []
    for d in docs:
        ts = datetime.fromisoformat(d["timestamp"]) - timedelta(minutes=tz_offset)
        rows.append({"Data": ts.strftime("%d/%m/%Y"), "Ora": ts.strftime("%H:%M:%S"), "Tipo": d["type"],
                     "Categoria": d["category"], "Oggetto": d["class_name"], "Direzione varco": d.get("direction") or "-",
                     "Direzione movimento": d["heading"], "Angolo (°)": d.get("angle"),
                     "Confidenza (%)": round(d["confidence"] * 100, 1), "ID traccia": d["track_id"],
                     "Sorgente": d["source"], "Allarme": d.get("alert_rule") or "", "ID evento": d["id"]})
    cols = ["Data", "Ora", "Tipo", "Categoria", "Oggetto", "Direzione varco", "Direzione movimento", "Angolo (°)",
            "Confidenza (%)", "ID traccia", "Sorgente", "Allarme", "ID evento"]
    df = pd.DataFrame(rows, columns=cols)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if format == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, sheet_name="Eventi")
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="eventi_{stamp}.xlsx"'})
    csv = df.to_csv(index=False, sep=";").encode("utf-8-sig")
    return Response(csv, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="eventi_{stamp}.csv"'})


@api.get("/events/{event_id}/snapshot")
async def event_snapshot(event_id: str):
    doc = await db.snapshots.find_one({"event_id": event_id}, {"_id": 0, "data": 1})
    if not doc:
        raise HTTPException(404, "Screenshot non trovato")
    return Response(bytes(doc["data"]), media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@api.delete("/events")
async def clear_events():
    r = await db.events.delete_many({})
    await db.snapshots.delete_many({})
    return {"deleted": r.deleted_count}


@api.get("/stats")
async def stats(hours: int = Query(24, ge=1, le=720)):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    docs = await db.events.find({"timestamp": {"$gte": since.isoformat()}},
                                {"_id": 0, "timestamp": 1, "direction": 1, "category": 1, "class_name": 1, "alert": 1}).to_list(100000)
    start = since.replace(minute=0, second=0, microsecond=0)
    buckets = {(start + timedelta(hours=i)).isoformat(): {"hour": (start + timedelta(hours=i)).isoformat(), "in": 0, "out": 0, "transiti": 0}
               for i in range(hours + 1)}
    by_cat: dict = {}
    by_class: dict = {}
    totals = {"total": 0, "in": 0, "out": 0, "alerts": 0}
    for d in docs:
        totals["total"] += 1
        totals["alerts"] += 1 if d.get("alert") else 0
        key = datetime.fromisoformat(d["timestamp"]).replace(minute=0, second=0, microsecond=0).isoformat()
        b = buckets.get(key)
        if d.get("direction") == "IN":
            totals["in"] += 1
            if b: b["in"] += 1
        elif d.get("direction") == "OUT":
            totals["out"] += 1
            if b: b["out"] += 1
        elif b:
            b["transiti"] += 1
        by_cat[d["category"]] = by_cat.get(d["category"], 0) + 1
        by_class[d["class_name"]] = by_class.get(d["class_name"], 0) + 1
    return {"totals": totals, "hourly": list(buckets.values()),
            "by_category": [{"name": k, "value": v} for k, v in by_cat.items()],
            "by_class": sorted([{"name": k, "value": v} for k, v in by_class.items()], key=lambda x: -x["value"])[:10]}


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    app.state.index_task = asyncio.create_task(ensure_indexes())
    await asyncio.to_thread(detector.load)
    logger.info("YOLOv8 caricato")


@app.on_event("shutdown")
async def shutdown_db_client():
    app.state.index_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.index_task
    client.close()
