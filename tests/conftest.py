"""Prove automatiche di SentinelAI (10/11/2026: prima vivevano in cartelle temporanee e sono andate perse).

  .venv-prove/bin/python -m pytest tests -q

Il server gira su un database SQLite in una cartella temporanea, con un riconoscitore finto (niente modello):
le prove decidono cosa "vede" l'IA fotogramma per fotogramma e un orologio finto fa passare il tempo."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
DATI = Path(tempfile.mkdtemp(prefix="sentinel-prove-"))
os.environ.update(MONGO_URL=f"sqlite:///{DATI.as_posix()}", DB_NAME="prove", DATA_DIR=str(DATI), APP_PASSWORD="",
                  SENTINEL_CLIPS_DIR=str(DATI / "video"), SENTINEL_LOG=str(DATI / "sentinelai.log"),
                  SENTINEL_VERSION="9.9.9", ALLOWED_HOSTS="", CORS_ORIGINS="", SENTINEL_RETE="0", TELEGRAM_BOT_TOKEN="")
os.environ.pop("SENTINEL_AGGIORNAMENTO", None)
sys.path.insert(0, str(RADICE / "backend"))

import detection  # noqa: E402


class Finto:
    """Al posto di YOLO: restituisce quello che la prova ha messo in `prossimi` (lista di (classe, conf, riquadro))."""
    prossimi: list = []

    @classmethod
    def detect(cls, frame, conf, iou, classes):
        return [d for d in cls.prossimi if d[1] >= conf and (not classes or d[0] in classes)]


def _carica():
    detection.detector.model, detection.detector.kind, detection.detector.engine = object(), "finto", "finto"


detection.detector.load = _carica
detection.detector.detect = Finto.detect


class Orologio:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def avanti(self, s):
        self.t += s


def esegui(coro):
    return asyncio.run(coro)


def riquadro(cx, cy, w=0.08, h=0.2):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


@pytest.fixture
def finto():
    Finto.prossimi = []
    return Finto


@pytest.fixture
def orologio(monkeypatch):
    import types
    import session
    o = Orologio()
    monkeypatch.setattr(session, "time", types.SimpleNamespace(monotonic=o.monotonic))
    monkeypatch.setattr(session, "IDLE_INTERVAL", -1)     # l'IA gira a ogni fotogramma (immagine fissa nelle prove)
    return o


@pytest.fixture
def db():
    """Database pulito (quello del server, così le prove dell'API e delle sessioni vedono le stesse cose)."""
    import server
    for nome in ("events", "snapshots", "clips", "cameras", "heatmaps", "backgrounds", "settings", "meta"):
        esegui(server.db[nome].delete_many({}))
    return server.db


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    import server
    with TestClient(server.app) as c:
        yield c


@pytest.fixture
def api(client, db):
    """Client con database pulito e senza password."""
    for f in (".app_password", ".app_generazione", ".chiedi_a_ogni_apertura"):
        (DATI / f).unlink(missing_ok=True)
    import auth_local
    auth_local._fails.clear(); auth_local._slow.clear(); auth_local._good_ips.clear()
    client.cookies.clear()
    client.headers.pop("authorization", None)
    return client
