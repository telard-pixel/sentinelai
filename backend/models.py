"""Modelli dati di SentinelAI (ricostruiti il 05/11/2026 dai pezzi originali e dal frontend)."""
import re
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional
from urllib.parse import quote

from pydantic import BaseModel, Field, model_validator

from detection import DEFAULT_CLASSES

#: Risoluzione della griglia della mappa di calore (celle).
HEAT_W, HEAT_H = 64, 36

CATEGORIES = ("persona", "veicolo", "animale", "oggetto")


class Line(BaseModel):
    enabled: bool = True
    x1: float = Field(0.08, ge=0, le=1)
    y1: float = Field(0.62, ge=0, le=1)
    x2: float = Field(0.92, ge=0, le=1)
    y2: float = Field(0.62, ge=0, le=1)
    invert: bool = False


class Zone(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(min_length=1)
    enabled: bool = True
    points: List[List[float]] = Field(min_length=3)
    categories: List[str] = []
    alert_on_enter: bool = True
    dwell_seconds: int = Field(0, ge=0, le=3600)
    color: str = "#EF4444"


class CameraIn(BaseModel):
    name: str = Field(min_length=1)
    type: Literal["webcam", "rtsp", "nvr", "file", "demo"] = "demo"
    url: str = ""
    nvr_brand: Literal["hikvision", "dahua", "custom"] = "hikvision"
    nvr_host: str = ""
    nvr_port: int = Field(554, ge=1, le=65535)
    nvr_username: str = ""
    nvr_password: str = ""
    nvr_channel: int = Field(1, ge=1, le=256)
    nvr_stream: Literal["main", "sub"] = "sub"
    nvr_path: str = ""
    device_id: str = ""
    line: Line = Line()
    zones: List[Zone] = []

    @model_validator(mode="after")
    def check_nvr(self):
        # Senza indirizzo la telecamera NVR si salva comunque, ma resta disattivata (lo dice il frontend).
        host = self.nvr_host.strip()
        if self.type == "nvr" and host and not re.fullmatch(r"[A-Za-z0-9.\-\[\]:]+", host):
            raise ValueError("Indirizzo NVR non valido")
        if self.type == "rtsp" and not self.url.strip():
            raise ValueError("URL del flusso obbligatorio")
        return self


class Camera(CameraIn):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def nvr_path(c: CameraIn) -> str:
    ch, main = c.nvr_channel, c.nvr_stream == "main"
    if c.nvr_brand == "hikvision":
        return f"/Streaming/Channels/{ch}0{1 if main else 2}"
    if c.nvr_brand == "dahua":
        return f"/cam/realmonitor?channel={ch}&subtype={0 if main else 1}"
    p = c.nvr_path.strip() or "/"
    return p if p.startswith("/") else "/" + p


def stream_url(c: CameraIn, hide_password: bool = False) -> str:
    """Indirizzo del flusso che legge il server (solo per RTSP e NVR)."""
    if c.type == "rtsp":
        return c.url.strip()
    if c.type != "nvr" or not c.nvr_host.strip():
        return ""
    auth = ""
    if c.nvr_username:
        pw = "****" if hide_password and c.nvr_password else quote(c.nvr_password, safe="")
        auth = quote(c.nvr_username, safe="") + (f":{pw}" if c.nvr_password else "") + "@"
    return f"rtsp://{auth}{c.nvr_host.strip()}:{c.nvr_port}{nvr_path(c)}"


def camera_public(c: Camera) -> dict:
    """Quello che vede il browser: mai la password dell'NVR."""
    d = c.model_dump()
    d["has_nvr_password"] = bool(d.pop("nvr_password"))
    d["nvr_password"] = ""
    d["disabled"] = c.type == "nvr" and not c.nvr_host.strip()
    if c.type == "nvr":
        d["url"] = stream_url(c, hide_password=True)
    return d


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
    transit_min_dist: float = Field(0.18, ge=0.0, le=1.0)
    sound: bool = True
    desktop_notifications: bool = True
    alert_rules: List[AlertRule] = [
        AlertRule(name="Persona in orario notturno", categories=["persona"], start="22:00", end="06:00"),
        AlertRule(name="Veicolo in entrata", categories=["veicolo"], direction="IN", enabled=False),
    ]
    clips_enabled: bool = True
    clip_pre_seconds: int = Field(5, ge=1, le=15)
    clip_post_seconds: int = Field(5, ge=1, le=20)
    telegram_enabled: bool = False
    telegram_chat_id: str = ""
    telegram_chat_name: str = ""
    telegram_send_photo: bool = True
    telegram_send_clip: bool = True
    retention_days: int = Field(30, ge=0, le=3650)


class Event(BaseModel):
    id: str
    clip_id: Optional[str] = None
    type: Literal["attraversamento", "transito", "zona_ingresso", "zona_sosta"]
    source: str
    camera_id: Optional[str] = None
    camera_name: Optional[str] = None
    zone_name: Optional[str] = None
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
