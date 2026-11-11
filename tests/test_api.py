"""Il server visto dal browser: telecamere, impostazioni, eventi, clip, accesso, diretta."""
import json
from datetime import datetime, timezone

import cv2
import numpy as np

from conftest import DATI, esegui, riquadro

CAM = {"name": "Garage", "type": "rtsp", "url": "rtsp://admin:segreta@10.0.0.5:554/1"}


def test_salute_e_versione(api):
    assert api.get("/api/health").json()["status"] == "ok"
    assert api.get("/api/version").json()["version"] == "9.9.9"


def test_telecamera_crea_modifica_elimina(api):
    c = api.post("/api/cameras", json=CAM).json()
    assert c["url"] == "rtsp://admin:****@10.0.0.5:554/1" and c["rev"] == 0
    # il browser rimanda l'indirizzo con ****: la password vera resta
    r = api.put(f"/api/cameras/{c['id']}", json={**CAM, "url": c["url"], "name": "Garage 2", "rev": 0})
    assert r.status_code == 200 and r.json()["rev"] == 1
    vera = esegui(__import__("server").db.cameras.find_one({"id": c["id"]}))
    assert vera["url"] == CAM["url"] and vera["name"] == "Garage 2"
    # una pagina rimasta indietro (revisione vecchia) non riscrive
    assert api.put(f"/api/cameras/{c['id']}", json={**CAM, "name": "Vecchia", "rev": 0}).status_code == 409
    assert api.delete(f"/api/cameras/{c['id']}").status_code == 200
    assert api.delete(f"/api/cameras/{c['id']}").status_code == 404


def test_solo_indirizzi_rtsp(api):
    for u in ("file:///etc/passwd", "http://127.0.0.1:8006/", "concat:/etc/passwd"):
        assert api.post("/api/cameras", json={**CAM, "url": u}).status_code == 422


def test_ordine_delle_telecamere(api):
    ids = [api.post("/api/cameras", json={**CAM, "name": n}).json()["id"] for n in "abc"]
    assert api.put("/api/camera-order", json={"ids": [ids[2], "inesistente", ids[0], ids[2]]}).json()["ids"] == [ids[2], ids[0]]
    assert [c["id"] for c in api.get("/api/cameras").json()] == [ids[2], ids[0], ids[1]]


def test_impostazioni_la_cartella_video_non_si_cambia_dal_salva(api):
    s = api.get("/api/settings").json()
    r = api.put("/api/settings", json={**s, "conf": 0.55, "clips_folder": "/tmp/altrove"})
    assert r.status_code == 200 and r.json()["conf"] == 0.55 and r.json()["clips_folder"] == ""
    assert api.put("/api/settings", json={**s, "conf": 7}).status_code == 422


def _evento(db, **k):
    ev = {"id": k.pop("id", "e1"), "clip_id": None, "type": "attraversamento", "source": "rtsp", "camera_id": "c1", "camera_name": "Garage",
          "zone_name": None, "class_id": 0, "class_name": "persona", "category": "persona", "direction": "IN", "heading": "Destra",
          "arrow": "→", "angle": 0.0, "confidence": 0.9, "track_id": 1, "alert": False, "alert_rule": None, "has_snapshot": False,
          "timestamp": datetime.now(timezone.utc).isoformat(), **k}
    esegui(db.events.insert_one(ev))
    return ev


def test_eventi_filtri_statistiche_ed_esportazione(api, db):
    _evento(db, id="e1")
    _evento(db, id="e2", category="veicolo", class_name="auto", direction="OUT", camera_name="=cmd|'/c calc'!A1", alert=True)
    _evento(db, id="e3", type="zona_ingresso", direction=None, zone_name="Cortile")
    assert len(api.get("/api/events").json()) == 3
    assert [e["id"] for e in api.get("/api/events", params={"category": "veicolo"}).json()] == ["e2"]
    assert [e["id"] for e in api.get("/api/events", params={"type": "zona"}).json()] == ["e3"]
    assert [e["id"] for e in api.get("/api/events", params={"alert_only": True}).json()] == ["e2"]
    st = api.get("/api/stats").json()
    assert st["totals"] == {"total": 3, "in": 1, "out": 1, "alerts": 1}
    assert sum(h["in"] for h in st["hourly"]) == 1 and sum(h["zone"] for h in st["hourly"]) == 1
    assert {c["name"]: c["value"] for c in st["by_category"]} == {"persona": 2, "veicolo": 1}
    csv = api.get("/api/events/export").content.decode("utf-8-sig")
    assert "'=cmd" in csv and "\n=cmd" not in csv and ";=cmd" not in csv      # niente formule nel foglio
    assert api.get("/api/events/export", params={"format": "xlsx"}).content[:2] == b"PK"
    assert api.delete("/api/events").json()["deleted"] == 3


def test_richieste_da_un_altro_sito_rifiutate(api):
    assert api.post("/api/cameras", json=CAM, headers={"Origin": "https://sito-cattivo.example"}).status_code == 403
    assert api.post("/api/cameras", json=CAM, headers={"Origin": "null"}).status_code == 403
    assert api.post("/api/cameras", json=CAM, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert api.post("/api/cameras", json=CAM, headers={"Origin": "http://testserver"}).status_code == 200


def test_video_della_clip_a_pezzi(api, db):
    dati = bytes(range(256)) * 40
    esegui(db.clips.insert_one({"id": "k1", "status": "ready", "camera_id": "c1", "camera_name": "Garage", "event_ids": [],
                                "timestamp": datetime.now(timezone.utc).isoformat(), "data": dati, "size": len(dati)}))
    f = DATI / "video-prova.mp4"
    f.write_bytes(dati)
    esegui(db.clips.insert_one({"id": "k2", "status": "ready", "camera_id": "c1", "camera_name": "Garage", "event_ids": [],
                                "timestamp": datetime.now(timezone.utc).isoformat(), "file": str(f), "size": len(dati)}))
    for k in ("k1", "k2"):
        assert api.get(f"/api/clips/{k}/video").content == dati
        r = api.get(f"/api/clips/{k}/video", headers={"Range": "bytes=100-199"})
        assert r.status_code == 206 and r.content == dati[100:200] and r.headers["content-range"] == f"bytes 100-199/{len(dati)}"
        r = api.get(f"/api/clips/{k}/video", headers={"Range": "bytes=-50"})
        assert r.status_code == 206 and r.content == dati[-50:]
        r = api.get(f"/api/clips/{k}/video", headers={"Range": f"bytes={len(dati) - 10}-"})
        assert r.status_code == 206 and r.content == dati[-10:]
        assert api.get(f"/api/clips/{k}/video", headers={"Range": f"bytes={len(dati) + 5}-"}).status_code == 416
    assert len(api.get("/api/clips").json()) == 2
    assert api.delete("/api/clips/k2").status_code == 200 and not f.exists()


def test_registro_senza_password_ne_token(api):
    (DATI / "sentinelai.log").write_text("apro rtsp://admin:segreta@10.0.0.5/1\nerrore https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789/sendPhoto\n")
    t = api.get("/api/log").json()["text"]
    assert "segreta" not in t and "ABCdef" not in t and "admin:****" in t


def test_password_accesso_cambio_e_gettoni(api):
    assert api.get("/api/auth/config").json()["password_required"] is False
    assert api.put("/api/auth/password", json={"new": "abc"}).status_code == 422
    tok = api.put("/api/auth/password", json={"new": "prima-pass"}).json()["token"]
    api.cookies.clear()
    assert api.get("/api/cameras").status_code == 401
    assert api.post("/api/auth/login", json={"password": "sbagliata"}).status_code == 401
    assert api.get("/api/cameras", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    tok2 = api.post("/api/auth/login", json={"password": "prima-pass"}).json()["token"]
    h = {"Authorization": f"Bearer {tok2}"}
    api.cookies.clear()
    assert api.put("/api/auth/password", json={"current": "no", "new": "seconda-pass"}, headers=h).status_code == 403
    tok3 = api.put("/api/auth/password", json={"current": "prima-pass", "new": "seconda-pass"}, headers=h).json()["token"]
    api.cookies.clear()
    assert api.get("/api/cameras", headers=h).status_code == 401          # il gettone di prima non vale più
    h3 = {"Authorization": f"Bearer {tok3}"}
    assert api.get("/api/cameras", headers=h3).status_code == 200
    api.post("/api/auth/logout", headers=h3)                               # Esci: tutti i gettoni scadono
    api.cookies.clear()
    assert api.get("/api/cameras", headers=h3).status_code == 401
    assert api.get("/api/cameras", headers={"Authorization": b"Bearer 9999999999.\xe0\xe8\xec"}).status_code == 401


def test_troppi_tentativi_di_accesso(api):
    api.put("/api/auth/password", json={"new": "una-password"})
    api.cookies.clear()
    codici = [api.post("/api/auth/login", json={"password": f"no{i}"}).status_code for i in range(10)]
    assert codici[:8] == [401] * 8 and codici[8:] == [429, 429]
    assert api.post("/api/auth/login", json={"password": "una-password"}).status_code == 429


def test_diretta_dalla_finestra(api, finto):
    cam = api.post("/api/cameras", json={"name": "Demo", "type": "demo"}).json()
    jpg = cv2.imencode(".jpg", np.zeros((360, 640, 3), dtype=np.uint8))[1].tobytes()
    with api.websocket_connect("/api/ws/stream") as ws:
        ws.send_text("non è json")
        ws.send_text(json.dumps({"type": "start", "camera_id": {"$ne": ""}}))
        assert ws.receive_json()["type"] == "error"
        ws.send_text(json.dumps({"type": "start", "camera_id": cam["id"], "tz_offset": -60}))
        assert ws.receive_json()["type"] == "ready"
        finto.prossimi = [(0, 0.9, riquadro(0.5, 0.5))]
        ws.send_bytes(jpg)
        m = ws.receive_json()
        assert m["type"] == "detections" and len(m["tracks"]) == 1 and m["tracks"][0]["label"] == "persona"
        ws.send_bytes(b"non un'immagine")
        assert ws.receive_json()["tracks"] == []


def test_diretta_rifiutata_senza_accesso(api):
    api.put("/api/auth/password", json={"new": "una-password"})
    api.cookies.clear()
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with api.websocket_connect("/api/ws/stream"):
            pass
    assert e.value.code == 4401


# ------------------------------------------------------------------ 1.0.22

def test_impostazioni_pagina_vecchia_non_riscrive(api):
    s = api.get("/api/settings").json()
    assert s["rev"] == 0
    a = api.put("/api/settings", json={**s, "conf": 0.6}).json()             # il PC cambia la soglia
    assert a["rev"] == 1
    r = api.put("/api/settings", json={**s, "sound": False})                  # il telefono, rimasto alla revisione 0
    assert r.status_code == 409
    assert api.get("/api/settings").json()["conf"] == 0.6
    senza = {k: v for k, v in s.items() if k != "rev"}                        # client vecchio: nessun controllo
    assert api.put("/api/settings", json={**senza, "conf": 0.7}).json()["rev"] == 2


def test_orario_scritto_male_nelle_regole(api):
    s = api.get("/api/settings").json()
    r = api.put("/api/settings", json={**s, "alert_rules": [{"name": "x", "start": "25:99", "end": ""}]}).json()
    assert (r["alert_rules"][0]["start"], r["alert_rules"][0]["end"]) == ("00:00", "23:59")


def test_clip_rimaste_a_meta_sistemate_all_avvio(api, db):
    import server
    ora = datetime.now(timezone.utc).isoformat()
    esegui(db.clips.insert_one({"id": "orfana", "status": "recording", "camera_id": "c1", "camera_name": "G", "event_ids": ["e1"], "timestamp": ora}))
    esegui(db.clips.insert_one({"id": "buona", "status": "ready", "camera_id": "c1", "camera_name": "G", "event_ids": [], "timestamp": ora, "data": b"x"}))
    _evento(db, id="e1", clip_id="orfana")
    assert esegui(server.close_orphan_clips()) == 1
    assert [c["id"] for c in api.get("/api/clips").json()] == ["buona"]
    assert api.get("/api/clips/orfana/meta").json()["status"] == "failed"
    assert api.get("/api/events").json()[0]["clip_id"] is None
    assert esegui(server.close_orphan_clips()) == 0


def test_statistiche_tenute_pochi_secondi(api, db, monkeypatch):
    import server
    _evento(db, id="e1")
    assert api.get("/api/stats").json()["totals"]["total"] == 1
    _evento(db, id="e2")
    assert api.get("/api/stats").json()["totals"]["total"] == 1               # stessa risposta entro 4 s
    monkeypatch.setattr(server, "STATS_SECONDS", 0)
    assert api.get("/api/stats").json()["totals"]["total"] == 2


def test_interruttore_allarme_attivo(api):
    c = api.post("/api/cameras", json=CAM).json()
    assert c["alarm_enabled"] is True and c["alarm_categories"] == []
    r = api.post(f"/api/cameras/{c['id']}/alarm", json={"on": False}).json()
    assert r["alarm_enabled"] is False and r["rev"] == 1 and r["url"] == c["url"]
    assert api.get("/api/cameras").json()[0]["alarm_enabled"] is False
    # una pagina rimasta indietro non lo riaccende salvando la telecamera
    assert api.put(f"/api/cameras/{c['id']}", json={**CAM, "rev": 0}).status_code == 409
    r = api.put(f"/api/cameras/{c['id']}", json={**CAM, "url": c["url"], "rev": 1, "alarm_enabled": False, "alarm_categories": ["persona"]}).json()
    assert r["alarm_enabled"] is False and r["alarm_categories"] == ["persona"]
    assert api.post("/api/cameras/inesistente/alarm", json={"on": True}).status_code == 404


def test_salvare_senza_i_campi_degli_allarmi_non_li_riaccende(api):
    c = api.post("/api/cameras", json={**CAM, "alarm_enabled": False, "alarm_categories": ["persona"]}).json()
    r = api.put(f"/api/cameras/{c['id']}", json={**CAM, "url": c["url"], "name": "Rinominata"}).json()   # client vecchio
    assert r["name"] == "Rinominata" and r["alarm_enabled"] is False and r["alarm_categories"] == ["persona"]
    assert api.put(f"/api/cameras/{c['id']}", json={**CAM, "url": c["url"], "alarm_categories": ["Animale"]}).status_code == 422


def test_interruttore_allarme_avvisa_la_telecamera_accesa_e_non_tocca_altro(api, monkeypatch):
    import server
    c = api.post("/api/cameras", json={**CAM, "monitor": False}).json()
    viste = []
    monkeypatch.setattr(server.manager, "reload_camera", lambda cam, s: viste.append(cam.alarm_enabled))
    prima = esegui(server.db.cameras.find_one({"id": c["id"]}, {"_id": 0}))
    api.post(f"/api/cameras/{c['id']}/alarm", json={"on": False})
    dopo = esegui(server.db.cameras.find_one({"id": c["id"]}, {"_id": 0}))
    assert viste == [False]
    assert {k: v for k, v in dopo.items() if k not in ("alarm_enabled", "rev")} == {k: v for k, v in prima.items() if k not in ("alarm_enabled", "rev")}


def test_interruttore_allarme_vale_anche_per_la_diretta_del_browser(api, finto):
    cam = api.post("/api/cameras", json={"name": "Demo", "type": "demo", "line": {"enabled": False},
                                         "zones": [{"name": "Z", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}]}).json()
    jpg = cv2.imencode(".jpg", np.zeros((360, 640, 3), dtype=np.uint8))[1].tobytes()
    with api.websocket_connect("/api/ws/stream") as ws:
        ws.send_text(json.dumps({"type": "start", "camera_id": cam["id"]}))
        assert ws.receive_json()["type"] == "ready"
        api.post(f"/api/cameras/{cam['id']}/alarm", json={"on": False})       # da un'altra finestra
        finto.prossimi = [(0, 0.9, riquadro(0.5, 0.5))]
        eventi = []
        for _ in range(5):
            ws.send_bytes(jpg)
            eventi += ws.receive_json()["events"]
    import server
    assert [(e["type"], e["alert"]) for e in eventi] == [("zona_ingresso", False)]
    assert not server._browser_sessions.get(cam["id"])


def test_modifica_da_un_altra_finestra_vale_per_la_diretta_e_il_registro_si_svuota(api, finto, orologio):
    import server
    zona = {"name": "Z", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}
    a = api.post("/api/cameras", json={"name": "A", "type": "demo", "line": {"enabled": False}, "zones": [zona], "alarm_enabled": False}).json()
    b = api.post("/api/cameras", json={"name": "B", "type": "demo"}).json()
    jpg = cv2.imencode(".jpg", np.zeros((360, 640, 3), dtype=np.uint8))[1].tobytes()
    with api.websocket_connect("/api/ws/stream") as ws:
        ws.send_text(json.dumps({"type": "start", "camera_id": a["id"]}))
        assert ws.receive_json()["type"] == "ready"
        finto.prossimi = [(0, 0.9, riquadro(0.5, 0.5))]
        eventi = []
        for _ in range(4):
            ws.send_bytes(jpg); eventi += ws.receive_json()["events"]
        api.put(f"/api/cameras/{a['id']}", json={"name": "A", "type": "demo", "line": {"enabled": False}, "zones": a["zones"], "alarm_enabled": True})
        for _ in range(3):
            ws.send_bytes(jpg); eventi += ws.receive_json()["events"]
        assert [e["alert"] for e in eventi] == [False, True]
        ws.send_text(json.dumps({"type": "start", "camera_id": b["id"]}))        # stessa connessione, altra telecamera
        assert ws.receive_json()["type"] == "ready"
        assert not server._browser_sessions.get(a["id"]) and len(server._browser_sessions[b["id"]]) == 1
    assert not server._browser_sessions.get(b["id"])
