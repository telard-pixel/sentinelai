"""SentinelAI Vision Guard - backend (FastAPI + MongoDB + YOLOv8 locale).

Ricostruito il 05/11/2026: l'inizio (indici, router, load_settings, get_camera) è quello originale,
il resto segue le chiamate del frontend. Login locale con password (auth_local) al posto di Clerk."""
import asyncio
import io
import json
import logging
import os
import re
import time
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Literal, Optional

import csv

import cv2
import numpy as np
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel
from pymongo import ASCENDING, DESCENDING, IndexModel
from starlette.middleware.cors import CORSMiddleware

import telegram_bot
from auth_local import require_approved, users_router, ws_member
from detection import COCO_IT, category_of, detector
from models import HEAT_H, HEAT_W, Camera, CameraIn, Event, Settings, camera_public, stream_url
from session import StreamSession, network_loop

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

if os.environ['MONGO_URL'].startswith("sqlite:"):
    # Versione Windows: database in un file SQLite, niente server MongoDB.
    from docstore import Client as _DBClient
else:
    from motor.motor_asyncio import AsyncIOMotorClient as _DBClient
client = _DBClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

INDEXES: dict[str, list[IndexModel]] = {
    "events": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("timestamp", DESCENDING)], name="timestamp_desc"),
        IndexModel([("category", ASCENDING), ("timestamp", DESCENDING)], name="category_ts"),
        IndexModel([("camera_id", ASCENDING), ("timestamp", DESCENDING)], name="camera_ts"),
    ],
    "snapshots": [
        IndexModel([("event_id", ASCENDING)], name="event_id", unique=True),
        IndexModel([("timestamp", ASCENDING)], name="timestamp"),
    ],
    "clips": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("timestamp", ASCENDING)], name="timestamp"),
    ],
    "cameras": [IndexModel([("id", ASCENDING)], name="id", unique=True)],
    "heatmaps": [IndexModel([("camera_id", ASCENDING)], name="camera_id")],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)


app = FastAPI(title="SentinelAI Vision Guard")
public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(require_approved)])


async def load_settings() -> Settings:
    doc = await db.settings.find_one({"_id": "global"}, {"_id": 0})
    return Settings(**doc) if doc else Settings()


async def get_camera(camera_id: str) -> Camera:
    doc = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Telecamera non trovata")
    return Camera(**doc)


def utc_range_of_day(day: str, tz_offset: int):
    """Giorno locale (AAAA-MM-GG) -> intervallo UTC. tz_offset è quello di JavaScript (UTC - ora locale, in minuti)."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(minutes=tz_offset)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- pubblico

@public.get("/")
async def root():
    return {"message": "SentinelAI attivo", "model_loaded": detector.model is not None}


@public.get("/health")
async def health():
    return {"status": "ok", "model": "YOLOv8n (locale)", "model_loaded": detector.model is not None}


# ---------------------------------------------------------------- impostazioni

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


# ---------------------------------------------------------------- telecamere

@api.get("/cameras")
async def list_cameras():
    docs = await db.cameras.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return [camera_public(Camera(**d)) for d in docs]


@api.post("/cameras")
async def create_camera(body: CameraIn):
    cam = Camera(**body.model_dump())
    await db.cameras.insert_one(cam.model_dump())
    return camera_public(cam)


@api.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, body: CameraIn):
    old = await get_camera(camera_id)
    data = body.model_dump()
    if not data["nvr_password"]:
        data["nvr_password"] = old.nvr_password   # campo vuoto = password invariata
    cam = Camera(**data, id=old.id, created_at=old.created_at)
    await db.cameras.replace_one({"id": camera_id}, cam.model_dump())
    return camera_public(cam)


@api.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str):
    r = await db.cameras.delete_one({"id": camera_id})
    if not r.deleted_count:
        raise HTTPException(404, "Telecamera non trovata")
    await db.heatmaps.delete_many({"camera_id": camera_id})
    await db.backgrounds.delete_many({"camera_id": camera_id})
    return {"deleted": True}


@api.get("/cameras/{camera_id}/heatmap")
async def camera_heatmap(camera_id: str, category: Optional[str] = None):
    q = {"camera_id": camera_id, **({"category": category} if category else {})}
    grid, tracks = [0] * (HEAT_W * HEAT_H), 0
    async for d in db.heatmaps.find(q, {"_id": 0}):
        tracks += d.get("tracks", 0)
        for k, v in (d.get("cells") or {}).items():
            i = int(k)
            if 0 <= i < len(grid):
                grid[i] += v
    return {"w": HEAT_W, "h": HEAT_H, "grid": grid, "max": max(grid), "total": tracks}


@api.delete("/cameras/{camera_id}/heatmap")
async def reset_heatmap(camera_id: str):
    r = await db.heatmaps.delete_many({"camera_id": camera_id})
    return {"deleted": r.deleted_count}


@api.get("/cameras/{camera_id}/background")
async def camera_background(camera_id: str):
    doc = await db.backgrounds.find_one({"camera_id": camera_id}, {"_id": 0, "data": 1})
    if not doc:
        raise HTTPException(404, "Nessuna immagine di sfondo")
    return Response(bytes(doc["data"]), media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- eventi

def events_filter(category, direction, etype, alert_only, hours, camera_id=None):
    q: dict = {}
    if category:
        q["category"] = category
    if direction:
        q["direction"] = direction
    if etype == "zona":
        q["type"] = {"$regex": "^zona"}
    elif etype:
        q["type"] = etype
    if alert_only:
        q["alert"] = True
    if hours:
        q["timestamp"] = {"$gte": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()}
    if camera_id:
        q["camera_id"] = camera_id
    return q


@api.get("/events", response_model=List[Event])
async def list_events(limit: int = Query(100, ge=1, le=1000), category: Optional[str] = None,
                      direction: Optional[str] = None, type: Optional[str] = None, alert_only: bool = False,
                      hours: Optional[int] = None, camera_id: Optional[str] = None):
    q = events_filter(category, direction, type, alert_only, hours, camera_id)
    docs = await db.events.find(q, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return [Event(**d) for d in docs]


TYPE_IT = {"attraversamento": "Attraversamento", "transito": "Transito", "zona_ingresso": "Ingresso in zona", "zona_sosta": "Sosta in zona"}


@api.get("/events/export")
async def export_events(format: Literal["csv", "xlsx"] = "csv", category: Optional[str] = None,
                        direction: Optional[str] = None, type: Optional[str] = None, hours: Optional[int] = None,
                        alert_only: bool = False, camera_id: Optional[str] = None, tz_offset: int = 0):
    q = events_filter(category, direction, type, alert_only, hours, camera_id)
    docs = await db.events.find(q, {"_id": 0}).sort("timestamp", -1).to_list(50000)
    rows = []
    for d in docs:
        ts = datetime.fromisoformat(d["timestamp"]) - timedelta(minutes=tz_offset)
        rows.append({"Data": ts.strftime("%d/%m/%Y"), "Ora": ts.strftime("%H:%M:%S"), "Telecamera": d.get("camera_name") or "",
                     "Tipo": TYPE_IT.get(d["type"], d["type"]), "Zona": d.get("zone_name") or "",
                     "Categoria": d["category"], "Oggetto": d["class_name"], "Direzione varco": d.get("direction") or "-",
                     "Direzione movimento": d["heading"], "Angolo (°)": d.get("angle"),
                     "Confidenza (%)": round(d["confidence"] * 100, 1), "ID traccia": d["track_id"],
                     "Sorgente": d["source"], "Allarme": d.get("alert_rule") or "", "Clip": "sì" if d.get("clip_id") else "",
                     "ID evento": d["id"]})
    cols = ["Data", "Ora", "Telecamera", "Tipo", "Zona", "Categoria", "Oggetto", "Direzione varco", "Direzione movimento",
            "Angolo (°)", "Confidenza (%)", "ID traccia", "Sorgente", "Allarme", "Clip", "ID evento"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if format == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Eventi"
        ws.append(cols)
        for r in rows:
            ws.append([r[c] for c in cols])
        ws.freeze_panes = "A2"
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="eventi_{stamp}.xlsx"'})
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows({c: ("" if r[c] is None else r[c]) for c in cols} for r in rows)
    return Response(out.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="eventi_{stamp}.csv"'})


@api.get("/events/{event_id}/snapshot")
async def event_snapshot(event_id: str):
    doc = await db.snapshots.find_one({"event_id": event_id}, {"_id": 0, "data": 1})
    if not doc:
        raise HTTPException(404, "Screenshot non trovato")
    return Response(bytes(doc["data"]), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@api.delete("/events")
async def clear_events():
    r = await db.events.delete_many({})
    await db.snapshots.delete_many({})
    return {"deleted": r.deleted_count}


@api.get("/stats")
async def stats(hours: int = Query(24, ge=1, le=720)):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    docs = await db.events.find({"timestamp": {"$gte": since.isoformat()}},
                                {"_id": 0, "timestamp": 1, "type": 1, "direction": 1, "category": 1, "class_name": 1, "alert": 1}).to_list(200000)
    start = since.replace(minute=0, second=0, microsecond=0)
    buckets = {(start + timedelta(hours=i)).isoformat(): {"hour": (start + timedelta(hours=i)).isoformat(), "in": 0, "out": 0, "transiti": 0, "zone": 0}
               for i in range(hours + 1)}
    by_cat: dict = {}
    by_class: dict = {}
    totals = {"total": 0, "in": 0, "out": 0, "alerts": 0}
    for d in docs:
        totals["total"] += 1
        totals["alerts"] += 1 if d.get("alert") else 0
        key = datetime.fromisoformat(d["timestamp"]).replace(minute=0, second=0, microsecond=0).isoformat()
        b = buckets.get(key)
        if d.get("type", "").startswith("zona"):
            if b:
                b["zone"] += 1
        elif d.get("direction") == "IN":
            totals["in"] += 1
            if b:
                b["in"] += 1
        elif d.get("direction") == "OUT":
            totals["out"] += 1
            if b:
                b["out"] += 1
        elif b:
            b["transiti"] += 1
        by_cat[d["category"]] = by_cat.get(d["category"], 0) + 1
        by_class[d["class_name"]] = by_class.get(d["class_name"], 0) + 1
    return {"totals": totals, "hourly": list(buckets.values()),
            "by_category": [{"name": k, "value": v} for k, v in by_cat.items()],
            "by_class": sorted([{"name": k, "value": v} for k, v in by_class.items()], key=lambda x: -x["value"])[:10]}


# ---------------------------------------------------------------- clip

CLIP_META = {"_id": 0, "data": 0}


async def with_event(clip: dict) -> dict:
    eid = (clip.get("event_ids") or [None])[0]
    ev = await db.events.find_one({"id": eid}, {"_id": 0}) if eid else None
    return {**clip, "event": ev}


@api.get("/clips")
async def list_clips(tz_offset: int = 0, camera_id: Optional[str] = None, day: Optional[str] = None,
                     limit: int = Query(200, ge=1, le=1000)):
    q: dict = {"status": {"$ne": "failed"}}
    if camera_id:
        q["camera_id"] = camera_id
    if day:
        try:
            a, b = utc_range_of_day(day, tz_offset)
        except ValueError:
            raise HTTPException(422, "Giorno non valido")
        q["timestamp"] = {"$gte": a, "$lt": b}
    docs = await db.clips.find(q, CLIP_META).sort("timestamp", -1).limit(limit).to_list(limit)
    return [await with_event(d) for d in docs]


@api.get("/clips/days")
async def clip_days(tz_offset: int = 0, camera_id: Optional[str] = None):
    q: dict = {"status": {"$ne": "failed"}, **({"camera_id": camera_id} if camera_id else {})}
    counts: dict = {}
    async for d in db.clips.find(q, {"_id": 0, "timestamp": 1}):
        day = (datetime.fromisoformat(d["timestamp"]) - timedelta(minutes=tz_offset)).strftime("%Y-%m-%d")
        counts[day] = counts.get(day, 0) + 1
    return [{"day": k, "count": v} for k, v in sorted(counts.items(), reverse=True)]


@api.get("/clips/{clip_id}/meta")
async def clip_meta(clip_id: str):
    doc = await db.clips.find_one({"id": clip_id}, CLIP_META)
    if not doc:
        raise HTTPException(404, "Clip non trovata")
    return doc


@api.get("/clips/{clip_id}/video")
async def clip_video(clip_id: str, request: Request, download: bool = False):
    doc = await db.clips.find_one({"id": clip_id, "status": "ready"}, {"_id": 0, "data": 1, "timestamp": 1})
    if not doc or not doc.get("data"):
        raise HTTPException(404, "Clip non disponibile")
    data = bytes(doc["data"])
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400"}
    if download:
        stamp = datetime.fromisoformat(doc["timestamp"]).strftime("%Y%m%d_%H%M%S")
        headers["Content-Disposition"] = f'attachment; filename="clip_{stamp}.mp4"'
    # Safari e i telefoni chiedono il video a pezzi (Range): senza risposta 206 non lo riproducono.
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("range", ""))
    if m and (m.group(1) or m.group(2)):
        size = len(data)
        if m.group(1):
            first, last = int(m.group(1)), int(m.group(2) or size - 1)
        else:
            first, last = max(0, size - int(m.group(2))), size - 1
        last = min(last, size - 1)
        if first > last:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {first}-{last}/{size}"
        return Response(data[first:last + 1], status_code=206, media_type="video/mp4", headers=headers)
    return Response(data, media_type="video/mp4", headers=headers)


@api.delete("/clips/{clip_id}")
async def delete_clip(clip_id: str):
    r = await db.clips.delete_one({"id": clip_id})
    if not r.deleted_count:
        raise HTTPException(404, "Clip non trovata")
    await db.events.update_many({"clip_id": clip_id}, {"$set": {"clip_id": None}})
    return {"deleted": True}


# ---------------------------------------------------------------- spazio

async def cleanup_old(days: int) -> dict:
    if not days:
        return {"events": 0, "snapshots": 0, "clips": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    ev = await db.events.delete_many({"timestamp": {"$lt": cutoff}})
    sn = await db.snapshots.delete_many({"timestamp": {"$lt": cutoff}})
    cl = await db.clips.delete_many({"timestamp": {"$lt": cutoff}})
    await db.meta.update_one({"_id": "storage"}, {"$set": {"last_cleanup": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    return {"events": ev.deleted_count, "snapshots": sn.deleted_count, "clips": cl.deleted_count}


@api.get("/storage")
async def storage():
    try:
        st = await db.command("dbstats")
    except Exception as exc:  # non deve mai far sparire il resto del riquadro
        logger.warning("dbstats non disponibile: %s", exc)
        st = {}
    meta = await db.meta.find_one({"_id": "storage"}) or {}
    return {"events": await db.events.count_documents({}), "snapshots": await db.snapshots.count_documents({}),
            "clips": await db.clips.count_documents({}),
            "size_mb": round((st.get("dataSize", 0) + st.get("indexSize", 0)) / 1048576, 1),
            "last_cleanup": meta.get("last_cleanup")}


@api.post("/storage/cleanup")
async def storage_cleanup():
    return await cleanup_old((await load_settings()).retention_days)


async def cleanup_loop():
    while True:
        try:
            await cleanup_old((await load_settings()).retention_days)
        except Exception as exc:
            logger.error("pulizia automatica: %s", exc)
        await asyncio.sleep(3600)


# ---------------------------------------------------------------- Telegram

_tg_status: dict = {"at": 0.0, "data": None}


@api.get("/telegram/status")
async def telegram_status():
    if not telegram_bot.bot_token():
        return {"token_configured": False, "bot_username": None, "error": None}
    if _tg_status["data"] and time.monotonic() - _tg_status["at"] < 60:
        return _tg_status["data"]
    try:
        me = await telegram_bot.call("getMe", timeout=15)
        data = {"token_configured": True, "bot_username": me.get("username"), "error": None}
    except Exception as exc:
        data = {"token_configured": True, "bot_username": None, "error": str(exc)}
    _tg_status.update(at=time.monotonic(), data=data)
    return data


TOKEN_FILE = Path(os.environ.get("DATA_DIR", ROOT_DIR)) / "telegram_token"


def load_telegram_token():
    if not os.environ.get("TELEGRAM_BOT_TOKEN") and TOKEN_FILE.exists():
        os.environ["TELEGRAM_BOT_TOKEN"] = TOKEN_FILE.read_text().strip()


class TokenIn(BaseModel):
    token: str


@api.put("/telegram/token")
async def telegram_set_token(body: TokenIn):
    """Token del bot messo dall'app (versione Windows): si prova con getMe e si salva solo se è valido."""
    token = body.token.strip()
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", token):
        raise HTTPException(400, "Il token non ha il formato giusto (numero:lettere, come lo dà @BotFather)")
    old = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    try:
        me = await telegram_bot.call("getMe", timeout=15)
    except Exception as exc:
        os.environ["TELEGRAM_BOT_TOKEN"] = old
        raise HTTPException(400, f"Telegram rifiuta il token: {exc}")
    TOKEN_FILE.write_text(token)
    with suppress(OSError):
        TOKEN_FILE.chmod(0o600)
    _tg_status.update(at=0.0, data=None)
    return {"bot_username": me.get("username")}


@api.post("/telegram/detect-chat")
async def telegram_detect_chat():
    try:
        updates = await telegram_bot.call("getUpdates", {"timeout": 0, "allowed_updates": json.dumps(["message", "my_chat_member"])}, timeout=20)
    except Exception as exc:
        raise HTTPException(400, f"Telegram: {exc}")
    chat = None
    for u in reversed(updates):
        c = (u.get("message") or u.get("my_chat_member") or {}).get("chat")
        if c:
            chat = c
            break
    if not chat:
        raise HTTPException(400, "Nessun messaggio trovato: apri il bot su Telegram, premi Avvia (o scrivi /start) e riprova.")
    name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username") or ""
    s = await load_settings()
    s.telegram_chat_id, s.telegram_chat_name, s.telegram_enabled = str(chat["id"]), name, True
    await db.settings.replace_one({"_id": "global"}, s.model_dump(), upsert=True)
    return {"chat_id": str(chat["id"]), "chat_name": name}


@api.post("/telegram/test")
async def telegram_test():
    s = await load_settings()
    if not s.telegram_chat_id:
        raise HTTPException(400, "Chat non collegata")
    try:
        await telegram_bot.call("sendMessage", {"chat_id": s.telegram_chat_id,
                                                "text": "✅ SentinelAI: messaggio di prova. Gli allarmi arriveranno qui."})
    except Exception as exc:
        raise HTTPException(400, f"Telegram: {exc}")
    return {"ok": True}


# ---------------------------------------------------------------- streaming

@public.websocket("/ws/stream")
async def stream_ws(ws: WebSocket):
    if await ws_member(ws.query_params.get("token", "") or ws.cookies.get("sentinel_token", "")) is None:
        await ws.close(code=4401)
        return
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
                    await ws.send_json({"type": "detections", "tracks": [], "events": [], "counts": session.counts, "fps": 0, "zones_active": []})
                    continue
                await ws.send_json({"type": "detections", **(await session.process(frame))})
                continue
            data = json.loads(msg.get("text") or "{}")
            kind = data.get("type")
            if kind == "start":
                try:
                    camera = await get_camera(data.get("camera_id", ""))
                except HTTPException:
                    await ws.send_json({"type": "error", "message": "Telecamera non trovata"})
                    continue
                if session:
                    await session.close()
                session = StreamSession(db, camera, await load_settings(), int(data.get("tz_offset", 0)))
                if camera.type in ("rtsp", "nvr"):
                    url = stream_url(camera)
                    if not url:
                        await ws.send_json({"type": "error", "message": "Telecamera disattivata: manca l'indirizzo dell'NVR."})
                        continue
                    net_task = asyncio.create_task(network_loop(ws, session, url))
                else:
                    await ws.send_json({"type": "ready"})
            elif kind == "reload" and session:
                with suppress(HTTPException):
                    session.update(await get_camera(session.camera.id), await load_settings())
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
        if session:
            # shield: anche se la connessione si chiude di colpo, la clip in corso viene salvata.
            with suppress(asyncio.CancelledError):
                await asyncio.shield(session.close())


app.include_router(public)
app.include_router(users_router)
app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
                   allow_methods=["*"], allow_headers=["*"])


DEMO_CAMERA = {"name": "Demo strada", "type": "demo"}


@app.on_event("startup")
async def startup():
    load_telegram_token()
    app.state.index_task = asyncio.create_task(ensure_indexes())
    if not await db.cameras.count_documents({}):
        await db.cameras.insert_one(Camera(**DEMO_CAMERA).model_dump())
    app.state.cleanup_task = asyncio.create_task(cleanup_loop())
    await asyncio.to_thread(detector.load)
    logger.info("YOLOv8 caricato")


@app.on_event("shutdown")
async def shutdown_db_client():
    for t in (app.state.index_task, app.state.cleanup_task):
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t
    client.close()
