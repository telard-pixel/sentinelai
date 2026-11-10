import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
# 1.0.22: due code separate. Prima c'era un lucchetto solo: la foto di un allarme nuovo aspettava che finisse il
# caricamento della clip precedente (fino a 2 minuti, più le attese chieste da Telegram).
_lock_foto = asyncio.Lock()
_lock_clip = asyncio.Lock()
_tasks: set = set()     # invii in corso: senza un riferimento Python può buttare via il compito a metà
_last_photo: dict[str, float] = {}
PHOTO_COOLDOWN = 15


class TelegramError(Exception):
    pass


def bot_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


async def call(method: str, data: dict | None = None, files: dict | None = None, timeout: float = 60, _tries: int = 0):
    token = bot_token()
    if not token:
        raise TelegramError("Token del bot Telegram non configurato")
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not body.get("ok"):
        if body.get("error_code") == 429 and _tries < 3:   # al massimo 3 nuovi tentativi, poi si rinuncia
            await asyncio.sleep(min(60, body.get("parameters", {}).get("retry_after", 3)))
            return await call(method, data, files, timeout, _tries + 1)
        raise TelegramError(body.get("description") or f"HTTP {r.status_code}")
    return body["result"]


def caption_for(ev: dict, tz_offset: int) -> str:
    ts = datetime.fromisoformat(ev["timestamp"]) - timedelta(minutes=tz_offset)
    kind = ("sosta in zona" if ev["type"] == "zona_sosta" else "ingresso in zona") if ev.get("zone_name") else \
        ("entrata" if ev.get("direction") == "IN" else "uscita" if ev.get("direction") == "OUT" else "transito")
    return (f"🚨 ALLERTA: {ev.get('alert_rule')}\n"
            f"📷 {ev.get('camera_name') or '-'}\n"
            f"{ev['class_name'].capitalize()} · {kind} · {ev['arrow']} {ev['heading']}\n"
            f"🕒 {ts.strftime('%d/%m/%Y %H:%M:%S')}")


def enabled(settings) -> bool:
    return bool(settings.telegram_enabled and settings.telegram_chat_id and bot_token())


async def _safe(coro, lock=None):
    try:
        async with (lock or _lock_foto):
            await coro
    except Exception as exc:
        # mai l'indirizzo (contiene il token del bot): solo il tipo e il testo dell'errore, senza indirizzi
        testo = str(exc).replace(bot_token() or "\0", "****")
        logger.error("Telegram: invio non riuscito (%s) %s", type(exc).__name__, testo)


def send_photo_bg(settings, ev: dict, photo: bytes | None, tz_offset: int):
    if not enabled(settings) or not settings.telegram_send_photo or not photo:
        return
    key = ev.get("camera_id") or ""
    now = time.monotonic()
    if now - _last_photo.get(key, 0) < PHOTO_COOLDOWN:
        return
    _last_photo[key] = now
    t = asyncio.create_task(_safe(call("sendPhoto", {"chat_id": settings.telegram_chat_id, "caption": caption_for(ev, tz_offset)},
                                       {"photo": ("allarme.jpg", photo, "image/jpeg")})))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def send_clip(settings, clip: bytes, caption: str):
    if not enabled(settings) or not settings.telegram_send_clip or not clip:
        return
    await _safe(call("sendVideo", {"chat_id": settings.telegram_chat_id, "caption": caption, "supports_streaming": "true"},
                     {"video": ("clip.mp4", clip, "video/mp4")}, timeout=120), _lock_clip)
