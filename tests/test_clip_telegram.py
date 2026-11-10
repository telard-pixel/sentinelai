"""1.0.22: clip che fallisce scritta nel registro, didascalia con la telecamera, foto che non aspetta la clip."""
import asyncio
import logging
from datetime import datetime, timezone

import clips
import telegram_bot
from conftest import esegui
from models import Camera, Settings


def registratore(db, **imp):
    cam = Camera(name="Garage", type="rtsp", url="rtsp://h/x")
    return clips.ClipRecorder(db, cam, Settings(**imp), -60)


def test_didascalia_con_telecamera_e_ora(db):
    r = registratore(db)
    t = r.clip_caption({"wall": datetime(2026, 11, 10, 17, 5, 9, tzinfo=timezone.utc), "events": ["a", "b"]})
    assert "Garage" in t and "10/11/2026 18:05:09" in t and "2 allarmi" in t
    assert "allarmi" not in r.clip_caption({"wall": datetime.now(timezone.utc), "events": ["a"]}).split("\n", 1)[1]


def test_clip_che_fallisce_scritta_nel_registro(db, monkeypatch, caplog):
    def rotto(frames):
        raise RuntimeError("ffmpeg rotto")
    monkeypatch.setattr(clips, "encode_mp4", rotto)
    r = registratore(db)

    async def f():
        await db.clips.insert_one({"id": "k", "status": "recording"})
        await r.finalize({"id": "k", "frames": [(0, b"a"), (1, b"b")], "events": ["e"]})
        return await db.clips.find_one({"id": "k"})
    with caplog.at_level(logging.ERROR, logger="clips"):
        doc = esegui(f())
    assert doc["status"] == "failed" and "ffmpeg rotto" in caplog.text and "Garage" in caplog.text


def test_la_foto_non_aspetta_la_clip(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:" + "A" * 35)
    ordine = []

    async def finta(method, data=None, files=None, timeout=60, _tries=0):
        if method == "sendVideo":
            await asyncio.sleep(0.5)
        ordine.append(method)
        return {}
    monkeypatch.setattr(telegram_bot, "call", finta)
    s = Settings(telegram_enabled=True, telegram_chat_id="1")
    ev = {"camera_id": "c-foto", "timestamp": datetime.now(timezone.utc).isoformat(), "type": "transito", "class_name": "persona",
          "arrow": "→", "heading": "Destra", "alert_rule": "r", "camera_name": "Garage"}

    async def f():
        clip = asyncio.create_task(telegram_bot.send_clip(s, b"video", "didascalia"))
        await asyncio.sleep(0.05)
        telegram_bot._last_photo.clear()
        telegram_bot.send_photo_bg(s, ev, b"jpeg", -60)
        assert len(telegram_bot._tasks) == 1
        await asyncio.sleep(0.2)
        a_meta = list(ordine)
        await clip
        return a_meta
    assert esegui(f()) == ["sendPhoto"] and ordine == ["sendPhoto", "sendVideo"]


def test_errore_telegram_senza_token_nel_registro(monkeypatch, caplog):
    token = "123456789:" + "B" * 35
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    async def rotta():
        raise RuntimeError(f"errore su https://api.telegram.org/bot{token}/sendPhoto")
    with caplog.at_level(logging.ERROR):
        esegui(telegram_bot._safe(rotta()))
    assert token not in caplog.text and "****" in caplog.text


def test_esci_aspetta_il_server():
    import sys
    import threading
    import time
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))
    import os
    os.environ.setdefault("LOCALAPPDATA", os.environ["DATA_DIR"])
    import sentinel_desktop as d

    class Srv:
        should_exit = False
        finito = False

        def run(self):
            while not self.should_exit:
                time.sleep(0.01)
            time.sleep(0.4)          # la clip in corso che si salva
            self.finito = True
    srv = Srv()
    srv.thread = threading.Thread(target=srv.run, daemon=True)
    srv.thread.start()
    d.stop_server(srv)
    assert srv.finito
