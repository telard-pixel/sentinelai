"""SentinelAI Vision Guard - backend (FastAPI + MongoDB + YOLO11 locale).

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
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, IndexModel
from starlette.middleware.cors import CORSMiddleware

import aggiornamento
import clips as clips_mod
import telegram_bot
from auth_local import require_approved, users_router, ws_member
from detection import COCO_IT, category_of, detector
from models import HEAT_H, HEAT_W, Camera, CameraIn, Event, Settings, camera_public, mask_text, restore_url_password, rtsp_url_allowed, RTSP_URL_ERROR, stream_url
from monitor import Manager
from session import StreamSession

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
manager = Manager(db)
_cam_locks: dict = {}


def cam_lock(camera_id: str) -> asyncio.Lock:
    """Accendere/spegnere/modificare la stessa telecamera uno alla volta (agente di prova: avvio subito dopo
    uno stop lasciava monitor=true nel database senza nessun lavoratore acceso)."""
    return _cam_locks.setdefault(camera_id, asyncio.Lock())

#: Nomi con cui si può chiamare il server (contro il "DNS rebinding": un sito che si finge 127.0.0.1).
#: Vuoto = qualsiasi (Docker dietro nginx/Tailscale). La versione Windows mette 127.0.0.1,localhost.
ALLOWED_HOSTS = {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}


def _hostname(value: str) -> str:
    from urllib.parse import urlsplit
    value = (value or "").strip()
    try:
        return (urlsplit(value if "//" in value else f"//{value}").hostname or "").lower()
    except ValueError:
        return ""


#: Origini in più ammesse per i comandi (es. https://sentinel.tuarete.ts.net dietro Tailscale serve).
ALLOWED_ORIGINS = {o.strip().lower().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()}
DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443"}


def _netloc(value: str, scheme: str = "http") -> str:
    """nome:porta normalizzato (porta di default esplicita)."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(value if "//" in value else f"//{value}")
        host = (u.hostname or "").lower()
        port = str(u.port) if u.port else DEFAULT_PORTS.get((u.scheme or scheme).lower(), "80")
    except ValueError:
        return ""
    return f"{host}:{port}" if host else ""


def real_scheme(headers, scheme: str) -> str:
    """Schema vero della pagina: dietro il nostro proxy (Docker, TRUST_PROXY=1) è quello di X-Forwarded-Proto,
    anche se uvicorn non è stato avviato con --proxy-headers (2° giro dell'agente di prova)."""
    if os.environ.get("TRUST_PROXY") == "1":
        fwd = (headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
        if fwd in ("http", "https"):
            return fwd
    return "https" if scheme in ("https", "wss") else "http"


def request_allowed(headers, method: str = "GET", scheme: str = "http") -> Optional[str]:
    """None se va bene, altrimenti il motivo del rifiuto. Vale per HTTP e WebSocket.

    06/11/2026 (agente di prova): si guarda SOLO l'intestazione Host. X-Forwarded-Host la può mettere chiunque
    (una pagina con DNS rebinding è "stessa origine" e la aggiunge a fetch) e aggirava tutto il controllo."""
    raw_host = headers.get("host", "")
    host = _hostname(raw_host)
    scheme = real_scheme(headers, scheme)
    if ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        return "indirizzo non ammesso"
    origin = (headers.get("origin") or "").strip()
    # Le richieste che cambiano qualcosa (e i WebSocket, che il browser manda sempre con Origin) devono
    # venire dalla pagina dell'app stessa: stesso schema-nome-porta, non un altro sito né "null".
    if method not in ("GET", "HEAD", "OPTIONS") or headers.get("upgrade", "").lower() == "websocket":
        if headers.get("sec-fetch-site") == "cross-site":
            return "richiesta da un altro sito"
        if origin:
            if origin.lower() == "null":
                return "origine nascosta (null)"
            if _netloc(origin) != _netloc(raw_host, scheme) and origin.lower().rstrip("/") not in ALLOWED_ORIGINS:
                return "richiesta da un altro sito"
    return None


from fastapi.exceptions import RequestValidationError  # noqa: E402


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Errori dei dati inviati, SENZA ripetere il valore ricevuto: con un NaN la risposta stessa andava in
    errore 500 (06/11/2026, agente di prova)."""
    detail = [{"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))} for e in exc.errors()]
    return Response(json.dumps({"detail": detail}, default=str), status_code=422, media_type="application/json")


@app.middleware("http")
async def guard(request: Request, call_next):
    why = request_allowed(request.headers, request.method, request.url.scheme)
    if why:
        logger.warning("rifiutata %s %s: %s (host=%s origin=%s)", request.method, request.url.path, why,
                       request.headers.get("host"), request.headers.get("origin"))
        return Response(json.dumps({"detail": f"Rifiutata: {why}"}), status_code=403, media_type="application/json")
    return await call_next(request)
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


def _zone(tz: Optional[str]):
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz)
        except Exception:
            return None
    return None


def to_local(ts_iso: str, tz_offset: int, tz: Optional[str] = None) -> datetime:
    """Ora locale di un evento. 06/11/2026 (agente di prova): con il nome del fuso (es. Europe/Rome) ogni evento
    usa l'ora legale del SUO giorno; lo spostamento fisso di oggi sbagliava di un'ora gli eventi estivi."""
    dt = datetime.fromisoformat(ts_iso)
    z = _zone(tz)
    return dt.astimezone(z).replace(tzinfo=None) if z else (dt - timedelta(minutes=tz_offset)).replace(tzinfo=None)


def utc_range_of_day(day: str, tz_offset: int, tz: Optional[str] = None):
    """Giorno locale (AAAA-MM-GG) -> intervallo UTC. tz_offset è quello di JavaScript (UTC - ora locale, in minuti)."""
    z = _zone(tz)
    d = datetime.strptime(day, "%Y-%m-%d")
    if z:
        a = d.replace(tzinfo=z).astimezone(timezone.utc)
        b = (d + timedelta(days=1)).replace(tzinfo=z).astimezone(timezone.utc)
        return a.isoformat(), b.isoformat()
    start = d.replace(tzinfo=timezone.utc) + timedelta(minutes=tz_offset)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def cell(v):
    """Contro le formule nel CSV/Excel: un nome che inizia con = + - @ diventerebbe un comando del foglio."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


# ---------------------------------------------------------------- pubblico

@public.get("/")
async def root():
    return {"message": "SentinelAI attivo", "model_loaded": detector.model is not None}


@api.get("/version")
async def version():
    """1.0.10: versione installata, mostrata in fondo alle Impostazioni (solo dopo il login)."""
    # 1.0.14: anche il motore dell'IA (OpenVINO scheda video / processore, OpenCV)
    return {"version": os.environ.get("SENTINEL_VERSION", "sviluppo"), "ai": detector.engine}


@api.get("/aggiornamento")
async def update_check(forza: bool = False):
    """1.0.12: c'è una versione nuova? (repository pubblico dei rilasci, controllato al massimo ogni 10 minuti)"""
    return {**await asyncio.to_thread(aggiornamento.controlla, forza), "stato": aggiornamento.stato()}


@api.post("/aggiornamento/installa")
async def update_install():
    """1.0.12: scarica, controlla la firma e installa la versione nuova; SentinelAI si riavvia da solo."""
    try:
        return await asyncio.to_thread(aggiornamento.avvia)
    except aggiornamento.ErroreAggiornamento as e:
        raise HTTPException(409, str(e))


@api.get("/aggiornamento/stato")
async def update_status():
    return aggiornamento.stato()


@public.get("/health")
async def health():
    return {"status": "ok", "model": "YOLO11s (locale)", "model_loaded": detector.model is not None}


# ---------------------------------------------------------------- impostazioni

@api.get("/classes")
async def classes():
    return [{"id": i, "name": n, "category": category_of(i)} for i, n in enumerate(COCO_IT)]


@api.get("/settings", response_model=Settings)
async def get_settings():
    return await load_settings()


@api.put("/settings", response_model=Settings)
async def put_settings(s: Settings):
    # La cartella dei video si cambia solo con PUT /storage/folder (controllata): il Salva generale delle
    # Impostazioni manda i valori letti all'apertura e rimetterebbe quella vecchia.
    s.clips_folder = (await load_settings()).clips_folder
    await db.settings.replace_one({"_id": "global"}, s.model_dump(), upsert=True)
    manager.reload_settings(s)
    return s


# ---------------------------------------------------------------- telecamere

@api.get("/cameras")
async def list_cameras():
    docs = await db.cameras.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return [camera_public(Camera(**d)) for d in docs]


@api.post("/cameras")
async def create_camera(body: CameraIn):
    if not rtsp_url_allowed(body):
        raise HTTPException(422, RTSP_URL_ERROR)
    cam = Camera(**body.model_dump())
    await db.cameras.insert_one(cam.model_dump())
    return camera_public(cam)


@api.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, body: CameraIn):
    old = await get_camera(camera_id)
    data = body.model_dump()
    if not data["nvr_password"] and data["nvr_host"].strip().lower() == old.nvr_host.strip().lower() \
            and data["nvr_username"] == old.nvr_username and data["nvr_port"] == old.nvr_port:
        data["nvr_password"] = old.nvr_password   # campo vuoto = password invariata (solo stesso NVR e utente)
    data["url"] = restore_url_password(data["url"], old.url)
    cam = Camera(**data, id=old.id, created_at=old.created_at)
    if not rtsp_url_allowed(cam):
        raise HTTPException(422, RTSP_URL_ERROR)
    async with cam_lock(camera_id):
        await db.cameras.replace_one({"id": camera_id}, cam.model_dump())
        if cam.type in ("rtsp", "nvr") and cam.monitor:
            if manager.get(cam.id):
                manager.reload_camera(cam, await load_settings())
            else:
                manager.ensure(cam, await load_settings())
        else:
            await manager.stop(cam.id)
    return camera_public(cam)


@api.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str):
    async with cam_lock(camera_id):
        await manager.stop(camera_id)
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
                        alert_only: bool = False, camera_id: Optional[str] = None, tz_offset: int = 0,
                        tz: Optional[str] = None):
    q = events_filter(category, direction, type, alert_only, hours, camera_id)
    docs = await db.events.find(q, {"_id": 0}).sort("timestamp", -1).to_list(50000)
    rows = []
    for d in docs:
        ts = to_local(d["timestamp"], tz_offset, tz)
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
            ws.append([cell(r[c]) for c in cols])
        ws.freeze_panes = "A2"
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="eventi_{stamp}.xlsx"'})
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows({c: ("" if r[c] is None else cell(r[c])) for c in cols} for r in rows)
    return Response(out.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="eventi_{stamp}.csv"'})


@api.get("/events/{event_id}/snapshot")
async def event_snapshot(event_id: str):
    doc = await db.snapshots.find_one({"event_id": event_id}, {"_id": 0, "data": 1})
    if not doc:
        raise HTTPException(404, "Screenshot non trovato")
    return Response(bytes(doc["data"]), media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


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
async def list_clips(tz_offset: int = 0, camera_id: Optional[str] = None, day: Optional[str] = None, tz: Optional[str] = None,
                     limit: int = Query(200, ge=1, le=1000)):
    q: dict = {"status": {"$ne": "failed"}}
    if camera_id:
        q["camera_id"] = camera_id
    if day:
        try:
            a, b = utc_range_of_day(day, tz_offset, tz)
        except ValueError:
            raise HTTPException(422, "Giorno non valido")
        q["timestamp"] = {"$gte": a, "$lt": b}
    docs = await db.clips.find(q, CLIP_META).sort("timestamp", -1).limit(limit).to_list(limit)
    return [await with_event(d) for d in docs]


@api.get("/clips/days")
async def clip_days(tz_offset: int = 0, camera_id: Optional[str] = None, tz: Optional[str] = None):
    q: dict = {"status": {"$ne": "failed"}, **({"camera_id": camera_id} if camera_id else {})}
    counts: dict = {}
    async for d in db.clips.find(q, {"_id": 0, "timestamp": 1}):
        day = to_local(d["timestamp"], tz_offset, tz).strftime("%Y-%m-%d")
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
    doc = await db.clips.find_one({"id": clip_id, "status": "ready"}, {"_id": 0, "data": 1, "file": 1, "timestamp": 1})
    if not doc or not (doc.get("data") or doc.get("file")):
        raise HTTPException(404, "Clip non disponibile")
    if doc.get("file"):
        try:
            data = await asyncio.to_thread(Path(doc["file"]).read_bytes)
        except OSError:
            raise HTTPException(404, "Il file del video non c'è più (cartella spostata, scollegata o file cancellato)")
    else:
        data = bytes(doc["data"])
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store"}
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
    doc = await db.clips.find_one({"id": clip_id}, {"_id": 0, "file": 1})
    if doc and doc.get("file"):
        await asyncio.to_thread(_remove_file, doc["file"])
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
    async for d in db.clips.find({"timestamp": {"$lt": cutoff}, "file": {"$ne": None}}, {"_id": 0, "file": 1}):
        await asyncio.to_thread(_remove_file, d["file"])
    cl = await db.clips.delete_many({"timestamp": {"$lt": cutoff}})
    await db.meta.update_one({"_id": "storage"}, {"$set": {"last_cleanup": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    return {"events": ev.deleted_count, "snapshots": sn.deleted_count, "clips": cl.deleted_count}


def _remove_file(path: str):
    """Cancella il file di una clip (e la cartella del giorno se resta vuota). Mai errori verso l'utente."""
    try:
        f = Path(path)
        if f.suffix.lower() != ".mp4":
            return
        f.unlink(missing_ok=True)
        try:
            f.parent.rmdir()          # solo se vuota
        except OSError:
            pass
    except OSError as exc:
        logger.warning("clip: file non cancellato %s: %s", path, exc)


class FolderBody(BaseModel):
    folder: str = Field("", max_length=400)


@api.put("/storage/folder")
async def set_clips_folder(body: FolderBody):
    """Sceglie la cartella dei video ("" = predefinita). Le clip nuove vanno lì; le vecchie restano dove sono."""
    folder = body.folder.strip()
    if folder:
        err = await asyncio.to_thread(clips_mod.check_folder, folder)
        if err:
            raise HTTPException(422, f"Cartella dei video: {err}")
    s = await load_settings()
    s.clips_folder = folder
    await db.settings.replace_one({"_id": "global"}, s.model_dump(), upsert=True)
    manager.reload_settings(s)
    return await storage()


@api.post("/storage/move-clips")
async def move_clips_here():
    """Porta nella cartella in uso le clip ancora nel database e quelle salvate in altre cartelle."""
    s = await load_settings()
    folder, warn = await asyncio.to_thread(clips_mod.clips_dir, s)
    if folder is None:
        raise HTTPException(409, warn or "Nessuna cartella disponibile")
    moved = failed = 0
    docs = await db.clips.find({"status": "ready"}, {"_id": 0, "id": 1, "file": 1, "camera_name": 1, "timestamp": 1}).to_list(100000)
    for d in docs:
        cur = d.get("file")
        if cur and Path(cur).exists() and clips_mod.same_place(Path(cur).parent.parent, folder):
            continue
        try:
            if cur:
                data = await asyncio.to_thread(Path(cur).read_bytes)
            else:
                full = await db.clips.find_one({"id": d["id"]}, {"_id": 0, "data": 1})
                data = bytes((full or {}).get("data") or b"")
            if not data:
                failed += 1
                continue
            wall = datetime.fromisoformat(d["timestamp"])
            path, _ = await asyncio.to_thread(clips_mod.save_clip_file, s, data, d.get("camera_name") or "telecamera", d["id"],
                                              wall, local_tz_offset_now())
            if not path:
                failed += 1
                continue
            await db.clips.update_one({"id": d["id"]}, {"$set": {"file": str(path)}, "$unset": {"data": ""}})
            # agente di prova 105: se il "nuovo" file è lo stesso di prima (stessa cartella scritta in altro modo)
            # cancellarlo voleva dire perdere il video
            if cur and Path(cur).exists() and not clips_mod.same_place(cur, path):
                await asyncio.to_thread(_remove_file, cur)
            moved += 1
        except (OSError, ValueError) as exc:
            logger.warning("spostamento clip %s: %s", d.get("id"), exc)
            failed += 1
    if moved:
        await asyncio.to_thread(_compact_db)
    return {"moved": moved, "failed": failed, **(await storage())}


def _compact_db():
    """Dopo aver tolto i video dal database lo si ricompatta (sennò il file resta grande)."""
    try:
        compact = getattr(db, "compact", None)
        if compact:
            compact()
    except Exception as exc:
        logger.warning("ricompattazione database: %s", exc)


def local_tz_offset_now() -> int:
    from session import local_tz_offset
    return local_tz_offset()


@api.get("/storage")
async def storage():
    try:
        st = await db.command("dbstats")
    except Exception as exc:  # non deve mai far sparire il resto del riquadro
        logger.warning("dbstats non disponibile: %s", exc)
        st = {}
    meta = await db.meta.find_one({"_id": "storage"}) or {}
    s = await load_settings()
    folder, warn = await asyncio.to_thread(clips_mod.clips_dir, s)
    files_mb, in_db, elsewhere = 0, 0, 0
    async for d in db.clips.find({"status": "ready"}, {"_id": 0, "file": 1, "size": 1}):
        if d.get("file"):
            files_mb += d.get("size") or 0
            if folder is None or not clips_mod.same_place(Path(d["file"]).parent.parent, folder):
                elsewhere += 1
        else:
            in_db += 1
    return {"events": await db.events.count_documents({}), "snapshots": await db.snapshots.count_documents({}),
            "clips": await db.clips.count_documents({}),
            "clips_folder": str(folder) if folder else None, "clips_folder_chosen": s.clips_folder,
            "clips_folder_default": str(clips_mod.default_clips_dir()), "clips_folder_warning": warn,
            "clips_files_mb": round(files_mb / 1048576, 1), "clips_in_db": in_db, "clips_elsewhere": elsewhere,
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
    why = request_allowed({**ws.headers, "upgrade": "websocket"}, "GET", "https" if ws.url.scheme in ("wss", "https") else "http")
    if why:
        logger.warning("WebSocket rifiutato: %s (origin=%s)", why, ws.headers.get("origin"))
        await ws.close(code=4403)
        return
    if await ws_member(ws.query_params.get("token", "") or ws.cookies.get("sentinel_token", "")) is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    session: Optional[StreamSession] = None     # webcam / file / demo: i fotogrammi li manda la finestra
    worker = None                                # RTSP / NVR: li legge il server di continuo (monitor.py)
    queue = None
    pump: Optional[asyncio.Task] = None

    async def pump_frames(q):
        while True:
            await ws.send_json(await q.get())

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
            try:
                data = json.loads(msg.get("text") or "{}")
            except ValueError:
                continue                    # messaggio malformato: si ignora, la connessione resta su
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            if kind == "start":
                cid = data.get("camera_id")
                try:
                    if not isinstance(cid, str):   # solo testo: un oggetto tipo {"$ne": ...} non deve passare
                        raise HTTPException(404)
                    camera = await get_camera(cid)
                except HTTPException:
                    await ws.send_json({"type": "error", "message": "Telecamera non trovata"})
                    continue
                if session:
                    await asyncio.shield(session.close())
                    session = None
                if worker and queue:
                    worker.detach(queue)
                if pump:
                    pump.cancel()
                if camera.type in ("rtsp", "nvr"):
                    # 06/11/2026 (agente di prova, 2° giro): lo "start" di una finestra NON accende più il
                    # monitoraggio (una finestra rimasta indietro riaccendeva una telecamera appena fermata).
                    # Si accende solo con Avvia (PUT monitor:true); qui, se è spenta, si risponde "stopped".
                    if not camera.monitor:
                        await ws.send_json({"type": "stopped"})
                        continue
                    async with cam_lock(camera.id):
                        worker = manager.ensure(camera, await load_settings())
                    queue = worker.attach()
                    st = worker.status
                    await ws.send_json({"type": "ready"} if st["state"] == "live" else {"type": "error", "message": st["message"]})
                    pump = asyncio.create_task(pump_frames(queue))
                else:
                    try:
                        tzo = int(data.get("tz_offset", 0))
                    except (TypeError, ValueError):
                        tzo = 0
                    session = StreamSession(db, camera, await load_settings(), tzo)
                    await ws.send_json({"type": "ready"})
            elif kind == "reload":
                with suppress(HTTPException):
                    if session:
                        session.update(await get_camera(session.camera.id), await load_settings())
                    elif worker:
                        manager.reload_camera(await get_camera(worker.camera.id), await load_settings())
            elif kind == "reset":
                if session:
                    session.counts = {"in": 0, "out": 0}
                elif worker:
                    worker.session.counts = {"in": 0, "out": 0}
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("stream error: %s", exc)
        # 06/11/2026 (agente di prova): dopo un errore la connessione restava aperta e muta (LIVE finto,
        # niente ricollegamento): ora si chiude, e la finestra si ricollega da sola.
        with suppress(Exception):
            await ws.close(code=1011)
    finally:
        # Chiudere la finestra NON ferma le telecamere di rete: smette solo di guardarle.
        if worker and queue:
            worker.detach(queue)
        if pump:
            pump.cancel()
        if session:
            # shield: anche se la connessione si chiude di colpo, la clip in corso viene salvata.
            with suppress(asyncio.CancelledError):
                await asyncio.shield(session.close())


class MonitorIn(BaseModel):
    on: bool


@api.post("/cameras/{camera_id}/monitor")
async def camera_monitor(camera_id: str, body: MonitorIn):
    async with cam_lock(camera_id):
        cam = await get_camera(camera_id)
        if cam.type not in ("rtsp", "nvr"):
            raise HTTPException(400, "Solo le telecamere RTSP/NVR restano sotto controllo da sole")
        await db.cameras.update_one({"id": camera_id}, {"$set": {"monitor": body.on}})
        if body.on:
            cam.monitor = True
            manager.ensure(cam, await load_settings())
        else:
            await manager.stop(camera_id)
    return {"monitor": body.on}


@api.get("/monitor")
async def monitor_status():
    return {cid: {**w.status, "viewers": len(w.viewers), "fps": (w.last or {}).get("fps", 0)} for cid, w in manager.workers.items()}


@api.get("/log")
async def read_log(lines: int = Query(300, ge=10, le=5000)):
    path = os.environ.get("SENTINEL_LOG", "")
    if not path or not os.path.exists(path):
        return {"available": False, "text": "Registro non disponibile in questa versione (con Docker: docker compose logs backend)."}
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            tail = f.read().decode("utf-8", "replace").splitlines()[-lines:]
    except OSError:   # 1.0.9: cartella o file non leggibile = prima errore 500
        return {"available": False, "text": "Registro non leggibile (controlla i permessi del file sentinelai.log)."}
    text = "\n".join(tail)
    text = mask_text(text)                                                         # password negli indirizzi
    text = re.sub(r"bot\d{5,}:[A-Za-z0-9_-]{20,}", "bot****", text)              # token Telegram
    return {"available": True, "text": text}


app.include_router(public)
app.include_router(users_router)
app.include_router(api)
# 06/11/2026 (revisione): prima CORS "*" con le credenziali = qualsiasi sito aperto nel browser poteva leggere e
# comandare l'app (sul PC non c'è password). L'app e il server stanno sullo stesso indirizzo: CORS serve solo se
# si mette un elenco esplicito in CORS_ORIGINS, mai "*".
_cors = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip() and o.strip() != "*"]
if _cors:
    app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


DEMO_CAMERA = {"name": "Demo strada", "type": "demo"}


@app.on_event("startup")
async def startup():
    load_telegram_token()
    esito = aggiornamento.esito_ultimo_setup()
    if esito is not None:
        logger.warning("aggiornamento: installazione %s (codice %s), ora versione %s",
                       "riuscita" if esito == "0" else "NON riuscita", esito, aggiornamento.versione_attuale())
    app.state.index_task = asyncio.create_task(ensure_indexes())
    if not await db.cameras.count_documents({}):
        await db.cameras.insert_one(Camera(**DEMO_CAMERA).model_dump())
    app.state.cleanup_task = asyncio.create_task(cleanup_loop())
    await asyncio.to_thread(detector.load)
    logger.info("YOLO11s caricato (%s, motore %s)", detector.kind, detector.engine)
    # Le telecamere di rete accese restano accese anche dopo un riavvio del programma.
    settings = await load_settings()
    for d in await db.cameras.find({"monitor": True}, {"_id": 0}).to_list(200):
        cam = Camera(**d)
        if cam.type in ("rtsp", "nvr"):
            manager.ensure(cam, settings)


@app.on_event("shutdown")
async def shutdown_db_client():
    await manager.shutdown()
    for t in (app.state.index_task, app.state.cleanup_task):
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t
    client.close()
