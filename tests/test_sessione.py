"""Linea virtuale, zone, cose ferme, telecamere di prova e clip: la sessione di analisi con IA e orologio finti."""
import numpy as np

from conftest import esegui, riquadro
from models import Camera, Line, Settings, Zone
from session import StreamSession

FOTO = np.zeros((360, 640, 3), dtype=np.uint8)
SEMPRE = [{"name": "sempre", "categories": [], "direction": "any", "start": "00:00", "end": "23:59"}]


def sessione(db, **cam):
    cam.setdefault("line", Line(enabled=True, x1=0.08, y1=0.62, x2=0.92, y2=0.62))
    camera = Camera(name="Prova", type="rtsp", url="rtsp://h/x", **cam)
    return StreamSession(db, camera, Settings(alert_rules=cam.pop("regole", []), clips_enabled=True, clip_pre_seconds=1, clip_post_seconds=1), 0)


async def gira(s, finto, orologio, punti, cls=0, conf=0.8, passo=0.2):
    eventi = []
    for p in punti:
        finto.prossimi = [] if p is None else [(cls, conf, riquadro(*p))]
        eventi += (await s.process(FOTO))["events"]
        orologio.avanti(passo)
    return eventi


def test_passaggio_sulla_linea_contato_una_volta(db, finto, orologio):
    async def f():
        s = sessione(db)
        ev = await gira(s, finto, orologio, [(0.5, 0.30 + 0.04 * i) for i in range(16)])
        await s.close()
        return s, ev
    s, ev = esegui(f())
    passaggi = [e for e in ev if e["type"] == "attraversamento"]
    assert len(passaggi) == 1 and passaggi[0]["direction"] in ("IN", "OUT")
    assert s.counts["in"] + s.counts["out"] == 1
    assert esegui(db.events.count_documents({"type": "attraversamento"})) == 1
    assert esegui(db.snapshots.count_documents({})) == 1


def test_andata_e_ritorno_due_passaggi_opposti(db, finto, orologio):
    async def f():
        s = sessione(db)
        giu = [(0.5, 0.30 + 0.04 * i) for i in range(16)]
        ev = await gira(s, finto, orologio, giu + giu[::-1])
        await s.close()
        return ev
    d = [e["direction"] for e in esegui(f()) if e["type"] == "attraversamento"]
    assert len(d) == 2 and set(d) == {"IN", "OUT"}


def test_fermo_sulla_linea_che_trema_non_conta(db, finto, orologio):
    async def f():
        s = sessione(db)
        ev = await gira(s, finto, orologio, [(0.5, 0.62 + (0.03 if i % 2 else -0.03)) for i in range(60)])
        await s.close()
        return s, ev
    s, ev = esegui(f())
    assert not [e for e in ev if e["type"] == "attraversamento"] and s.counts == {"in": 0, "out": 0}


def test_fuori_dal_segmento_non_conta(db, finto, orologio):
    async def f():
        s = sessione(db, line=Line(enabled=True, x1=0.1, y1=0.62, x2=0.4, y2=0.62))
        ev = await gira(s, finto, orologio, [(0.9, 0.30 + 0.04 * i) for i in range(16)])
        await s.close()
        return s
    assert esegui(f()).counts == {"in": 0, "out": 0}


def test_zona_ingresso_sosta_allarme_e_clip(db, finto, orologio):
    zona = Zone(name="Cortile", points=[[0, 0.5], [1, 0.5], [1, 1], [0, 1]], dwell_seconds=2)

    async def f():
        s = sessione(db, zones=[zona], line=Line(enabled=False))
        s.settings.clip_post_seconds = 5        # i due allarmi (a 2 s di distanza) finiscono nella stessa clip
        ev = await gira(s, finto, orologio, [(0.5, 0.2)] * 3 + [(0.5, 0.7)] * 20)
        await s.close()
        return ev
    ev = esegui(f())
    assert [e["type"] for e in ev] == ["zona_ingresso", "zona_sosta"]
    assert all(e["alert"] and e["alert_rule"] == "Zona «Cortile»" and e["clip_id"] for e in ev)
    clip = esegui(db.clips.find({}, {"_id": 0, "data": 0}).to_list(9))
    assert len(clip) == 1 and clip[0]["status"] == "ready" and clip[0]["frames"] > 3
    assert set(clip[0]["event_ids"]) == {e["id"] for e in ev}


def test_zona_solo_per_la_categoria_scelta(db, finto, orologio):
    zona = Zone(name="Solo persone", points=[[0, 0.5], [1, 0.5], [1, 1], [0, 1]], categories=["persona"])

    async def f():
        s = sessione(db, zones=[zona], line=Line(enabled=False))
        ev = await gira(s, finto, orologio, [(0.5, 0.7)] * 10, cls=15)     # un gatto
        await s.close()
        return ev
    assert esegui(f()) == []


def test_telecamera_di_prova_eventi_ma_niente_allarmi_ne_clip(db, finto, orologio):
    zona = Zone(name="Z", points=[[0, 0.5], [1, 0.5], [1, 1], [0, 1]])

    async def f():
        s = sessione(db, zones=[zona], prova=True, line=Line(enabled=False))
        ev = await gira(s, finto, orologio, [(0.5, 0.7)] * 10)
        await s.close()
        return ev
    ev = esegui(f())
    assert len(ev) == 1 and not ev[0]["alert"] and ev[0]["clip_id"] is None
    assert esegui(db.clips.count_documents({})) == 0


def test_regola_di_allarme_sul_passaggio(db, finto, orologio):
    async def f():
        s = sessione(db)
        s.settings = Settings(alert_rules=SEMPRE, clips_enabled=False)
        s.recorder.settings = s.settings
        ev = await gira(s, finto, orologio, [(0.5, 0.30 + 0.04 * i) for i in range(16)])
        await s.close()
        return ev
    ev = [e for e in esegui(f()) if e["type"] == "attraversamento"]
    assert ev and ev[0]["alert"] and ev[0]["alert_rule"] == "sempre" and ev[0]["clip_id"] is None


def test_transito_senza_linea(db, finto, orologio):
    async def f():
        s = sessione(db, line=Line(enabled=False))
        ev = await gira(s, finto, orologio, [(0.1 + 0.05 * i, 0.3) for i in range(12)] + [None] * 12)
        await s.close()
        return ev
    assert [e["type"] for e in esegui(f())] == ["transito"]


def test_cosa_ferma_poco_sicura_non_da_eventi(db, finto, orologio):
    zona = Zone(name="Z", points=[[0, 0], [1, 0], [1, 1], [0, 1]], alert_on_enter=False, dwell_seconds=400)

    async def f():
        s = sessione(db, zones=[zona], line=Line(enabled=False))
        ev = await gira(s, finto, orologio, [(0.5, 0.5)] * 230, cls=1, conf=0.45, passo=2.0)   # bici appesa, 460 s
        fermo = [t.fixed for t in s.tracker.tracks.values()]
        await s.close()
        return ev, fermo
    ev, fermo = esegui(f())
    assert ev == [] and fermo == [True]


def test_mappa_di_calore_salvata(db, finto, orologio):
    async def f():
        s = sessione(db, line=Line(enabled=False))
        await gira(s, finto, orologio, [(0.5, 0.5)] * 5)
        await s.close()
    esegui(f())
    h = esegui(db.heatmaps.find_one({"category": "persona"}, {"_id": 0}))
    assert h["tracks"] == 1 and sum(h["cells"].values()) == 5
