"""Coperture chieste dall'agente di prova della 1.0.22: punti che le prove lasciavano passare anche col codice rotto."""
import json
from datetime import datetime, timezone

import pytest

from conftest import DATI, esegui
from models import AlertRule, Settings


def test_avvio_sistema_le_clip_a_meta(api, db, monkeypatch):
    import server
    esegui(db.clips.insert_one({"id": "orfana", "status": "recording", "event_ids": [], "timestamp": datetime.now(timezone.utc).isoformat()}))
    prima = {k: getattr(server.app.state, k) for k in ("index_task", "cleanup_task", "risorse_task")}
    try:
        esegui(server.startup())
    finally:
        for k, v in prima.items():
            setattr(server.app.state, k, v)
    assert esegui(db.clips.find_one({"id": "orfana"}))["status"] == "failed"


def test_salva_avvisa_le_telecamere_accese(api, monkeypatch):
    import server
    viste = []
    monkeypatch.setattr(server.manager, "reload_settings", viste.append)
    s = api.get("/api/settings").json()
    api.put("/api/settings", json={**s, "conf": 0.6})
    assert len(viste) == 1 and viste[0].conf == 0.6
    assert api.put("/api/settings", json={**s, "conf": 0.7}).status_code == 409 and len(viste) == 1


def test_cartella_video_non_cambia_la_revisione(api):
    assert api.put("/api/storage/folder", json={"folder": str(DATI / "altri-video")}).status_code == 200
    s = api.get("/api/settings").json()
    assert s["rev"] == 0 and s["clips_folder"].endswith("altri-video")
    assert api.put("/api/settings", json={**s, "conf": 0.6}).status_code == 200
    api.put("/api/storage/folder", json={"folder": ""})


def test_collega_chat_aumenta_la_revisione(api, monkeypatch):
    import telegram_bot
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:" + "A" * 35)

    async def finta(method, data=None, files=None, timeout=60, _tries=0):
        return [{"message": {"chat": {"id": 42, "first_name": "Rob"}}}]
    monkeypatch.setattr(telegram_bot, "call", finta)
    vecchie = api.get("/api/settings").json()
    r = api.post("/api/telegram/detect-chat").json()
    assert r == {"chat_id": "42", "chat_name": "Rob", "rev": 1}
    assert api.put("/api/settings", json={**vecchie, "telegram_chat_id": ""}).status_code == 409     # pagina rimasta indietro
    assert api.get("/api/settings").json()["telegram_chat_id"] == "42"


def test_video_si_legge_solo_il_pezzo_e_file_sparito(api, db, monkeypatch):
    import server
    f = DATI / "pezzi.mp4"
    f.write_bytes(bytes(1000))
    esegui(db.clips.insert_one({"id": "k", "status": "ready", "event_ids": [], "timestamp": datetime.now(timezone.utc).isoformat(), "file": str(f)}))
    chiesti, vero = [], server._read_piece
    monkeypatch.setattr(server, "_read_piece", lambda p, a, b: chiesti.append((a, b)) or vero(p, a, b))
    monkeypatch.setattr(type(f), "read_bytes", lambda self: pytest.fail("letto tutto il file"))
    assert len(api.get("/api/clips/k/video", headers={"Range": "bytes=100-199"}).content) == 100 and chiesti == [(100, 199)]
    f.unlink()
    assert api.get("/api/clips/k/video").status_code == 404
    assert api.get("/api/clips/k/video", headers={"Range": "bytes=0-9"}).status_code == 404


def test_statistiche_per_periodo_e_cancella(api, db):
    from test_api import _evento
    from datetime import timedelta
    _evento(db, id="nuovo")
    _evento(db, id="vecchio", timestamp=(datetime.now(timezone.utc) - timedelta(hours=30)).isoformat())
    assert api.get("/api/stats", params={"hours": 24}).json()["totals"]["total"] == 1
    assert api.get("/api/stats", params={"hours": 48}).json()["totals"]["total"] == 2
    api.delete("/api/events")
    assert api.get("/api/stats", params={"hours": 24}).json()["totals"]["total"] == 0


def test_diretta_non_accende_una_telecamera_spenta(api):
    import server
    cam = api.post("/api/cameras", json={"name": "Rete", "type": "rtsp", "url": "rtsp://127.0.0.1:1/x", "monitor": False}).json()
    demo = api.post("/api/cameras", json={"name": "Demo", "type": "demo"}).json()
    with api.websocket_connect("/api/ws/stream") as ws:
        for _ in range(2):
            ws.send_text(json.dumps({"type": "start", "camera_id": cam["id"]}))
            assert ws.receive_json()["type"] == "stopped"
        ws.send_text(json.dumps({"type": "reload"}))
        ws.send_text(json.dumps({"type": "reset"}))
        ws.send_text(json.dumps({"type": "start", "camera_id": demo["id"]}))
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(b"")                                   # fotogramma vuoto: la connessione resta su
        assert ws.receive_json()["tracks"] == []
    assert server.manager.workers == {}


def test_orari_delle_regole_mai_in_errore():
    for brutto in (None, 800, "25:99", "", " 08:00", "8:00"):
        r = AlertRule(name="x", start=brutto, end=brutto)
        assert (r.start, r.end) == ("00:00", "23:59")
    assert AlertRule(name="x", start="22:00", end="06:00").start == "22:00"
    assert Settings(alert_rules=[{"name": "v", "start": None}]).alert_rules[0].start == "00:00"
