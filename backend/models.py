"""Modelli dati di SentinelAI (ricostruiti il 05/11/2026 dai pezzi originali e dal frontend)."""
import re
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional
from urllib.parse import quote

from pydantic import BaseModel as _PydanticBase, ConfigDict, Field, model_validator

from detection import DEFAULT_CLASSES

class BaseModel(_PydanticBase):
    # 06/11/2026 (agente di prova): niente NaN/Infinito nei numeri (rompevano il salvataggio).
    model_config = ConfigDict(allow_inf_nan=False)


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
    points: List[List[float]] = Field(min_length=3, max_length=100)
    categories: List[str] = []
    alert_on_enter: bool = True
    dwell_seconds: int = Field(0, ge=0, le=3600)
    color: str = "#EF4444"


    @model_validator(mode="after")
    def check_points(self):
        # 06/11/2026 (agente di prova): un punto NaN rompeva il salvataggio (errore 500).
        import math
        for p in self.points:
            if len(p) != 2 or not all(math.isfinite(v) and -0.01 <= v <= 1.01 for v in p):
                raise ValueError("Punti della zona non validi")
        return self


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
    #: RTSP/NVR: il server la tiene sotto controllo di continuo, anche a finestra chiusa (si spegne con "Ferma").
    monitor: bool = False
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


def split_url(url: str):
    """(schema://, utente, password o None, host[:porta], resto) come urlsplit: l'userinfo arriva fino
    all'ULTIMA @ prima di / ? #. 06/11/2026 (agente di prova): prima una password con @ o spazi restava
    visibile in parte o del tutto."""
    m = re.match(r"^([a-z][a-z0-9+.-]*://)", url or "", re.I)
    if not m:
        return None
    rest = url[m.end():]
    # 2° giro dell'agente: una password con # / ? scritti così come sono (senza %23 ecc.) restava visibile.
    # Se prima dell'ultima @ c'è un ":", tutto quello prima è utente:password, qualunque carattere contenga.
    word = re.split(r"\s", rest, maxsplit=1)[0]
    at = word.rfind("@")
    if at >= 0 and ":" in word[:at] and not re.fullmatch(r"[^/?#@]*:\d+(/.*)?", word[:at]):
        userinfo, after = word[:at], word[at + 1:] + rest[len(word):]
        end = min([i for i in (after.find("/"), after.find("?"), after.find("#")) if i >= 0] or [len(after)])
        user, _, pw = userinfo.partition(":")
        return m.group(1), user, pw, after[:end], after[end:]
    end = min([i for i in (rest.find("/"), rest.find("?"), rest.find("#")) if i >= 0] or [len(rest)])
    auth, tail = rest[:end], rest[end:]
    if "@" not in auth:
        return m.group(1), None, None, auth, tail
    userinfo, host = auth.rsplit("@", 1)
    user, sep, pw = userinfo.partition(":")
    return m.group(1), user, (pw if sep else None), host, tail


def mask_url_password(url: str) -> str:
    p = split_url(url)
    if not p or p[2] is None:
        return url or ""
    scheme, user, pw, host, tail = p
    return f"{scheme}{user}:****@{host}{tail}"


def restore_url_password(new: str, old: str) -> str:
    """Il browser riceve l'indirizzo RTSP con la password oscurata: se lo rimanda con ****, si rimette la
    password vera, ma solo per lo stesso utente sulla stessa telecamera (IP e porta): mai a un altro apparecchio."""
    pn, po = split_url(new or ""), split_url(old or "")
    if not (pn and po and pn[2] == "****" and po[2] is not None):
        return new
    if pn[0].lower() == po[0].lower() and pn[1] == po[1] and pn[3].lower() == po[3].lower():
        return f"{pn[0]}{pn[1]}:{po[2]}@{pn[3]}{pn[4]}"
    return new


_SCHEME_IN_TEXT = re.compile(r"[a-z][a-z0-9+.-]*://", re.I)


def mask_text(text: str) -> str:
    """Oscura le password di tutti gli indirizzi dentro un testo (registro, messaggi di errore).
    L'utente e la password possono contenere spazi o @: si prende fino all'ULTIMA @ della riga prima del
    primo / ? # dopo lo schema, come per gli indirizzi veri."""
    out, pos, text = [], 0, text or ""
    for m in _SCHEME_IN_TEXT.finditer(text):
        if m.start() < pos:
            continue
        line_end = text.find("\n", m.end())
        line_end = len(text) if line_end < 0 else line_end
        nxt = _SCHEME_IN_TEXT.search(text, m.end(), line_end)   # fino al prossimo indirizzo, non a fine riga
        seg = text[m.end():nxt.start() if nxt else line_end]
        # fino all'ultima @ della "parola" (prima di uno spazio): la password può contenere / ? # @ e anche spazi
        word = re.split(r"\s", seg, maxsplit=1)[0]
        at = word.rfind("@")
        if at < 0:
            # spazi nella password: cerca l'ultima @ della riga dopo un ":" (utente:pass word@host)
            at = seg.rfind("@")
            if at < 0 or ":" not in seg[:at]:
                continue
        if ":" not in seg[:at]:
            continue
        user = seg[:at].split(":", 1)[0]
        out.append(text[pos:m.end()] + f"{user}:****")
        pos = m.end() + at
    out.append(text[pos:])
    return "".join(out)


def camera_public(c: Camera) -> dict:
    """Quello che vede il browser: mai la password dell'NVR né quella dentro l'indirizzo RTSP."""
    d = c.model_dump()
    d["has_nvr_password"] = bool(d.pop("nvr_password"))
    d["nvr_password"] = ""
    d["disabled"] = c.type == "nvr" and not c.nvr_host.strip()
    if c.type == "nvr":
        d["url"] = stream_url(c, hide_password=True)
    else:
        d["url"] = mask_url_password(c.url)
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
    # 1.0.5: cartella dei video delle clip ("" = predefinita: Video\SentinelAI sul PC, DATA_DIR/clip in Docker)
    clips_folder: str = Field("", max_length=400)


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
