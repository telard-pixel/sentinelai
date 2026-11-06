"""Accesso locale con una password unica (05/11/2026): sostituisce Clerk per l'uso a casa.

- APP_PASSWORD vuota  -> nessun login (solo per prove su una rete fidata).
- APP_PASSWORD impostata -> il browser fa login una volta e riceve un gettone firmato (30 giorni),
  sia come cookie (serve a immagini, video ed esportazioni) sia da mandare come Bearer / ?token=.
Gli stessi nomi di prima (require_approved, users_router, ws_member) così server.py non cambia."""
import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

COOKIE = "sentinel_token"
TOKEN_DAYS = 30
LOCAL_MEMBER = {"user_id": "locale", "role": "admin", "email": "", "name": "Amministratore", "env": "locale"}

users_router = APIRouter(prefix="/api")
_fails: dict[str, list[float]] = {}


def _password() -> str:
    return os.environ.get("APP_PASSWORD", "")


def _data_file(name: str) -> Path:
    return Path(os.environ.get("DATA_DIR", Path(__file__).parent)) / name


def _generation() -> str:
    p = _data_file(".app_generazione")
    return p.read_text().strip() if p.exists() else "0"


def _secret() -> bytes:
    """Chiave dei gettoni = segreto fisso + impronta della password + "generazione".
    06/11/2026 (agente di prova): così cambiare la password o premere Esci invalida i gettoni già dati."""
    s = os.environ.get("APP_SECRET", "")
    if not s:
        # Generato una volta e tenuto accanto ai dati, così i login restano validi dopo un riavvio.
        path = _data_file(".app_secret")
        if not path.exists():
            path.write_text(secrets.token_hex(32))
            path.chmod(0o600)
        s = path.read_text().strip()
    pw = hashlib.sha256(_password().encode()).hexdigest()
    return f"{s}|{pw}|{_generation()}".encode()


def new_generation():
    p = _data_file(".app_generazione")
    p.write_text(str(int(_generation()) + 1 if _generation().isdigit() else 1))


def make_token() -> str:
    exp = str(int(time.time()) + TOKEN_DAYS * 86400)
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).digest()
    return f"{exp}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def valid_token(token: str) -> bool:
    try:
        exp, sig = token.split(".", 1)
        good = base64.urlsafe_b64encode(hmac.new(_secret(), exp.encode(), hashlib.sha256).digest()).rstrip(b"=")
        # bytes: con caratteri non ASCII compare_digest su stringhe dava TypeError -> errore 500
        return hmac.compare_digest(sig.encode("utf-8", "replace"), good) and int(exp) > time.time()
    except (ValueError, AttributeError, TypeError, UnicodeError):
        return False


def _token_of(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.cookies.get(COOKIE) or request.query_params.get("token", "")


async def require_approved(request: Request) -> dict:
    if _password() and not valid_token(_token_of(request)):
        raise HTTPException(401, "Accesso richiesto")
    return LOCAL_MEMBER


async def ws_member(token: str) -> dict | None:
    return LOCAL_MEMBER if not _password() or valid_token(token) else None


class LoginIn(BaseModel):
    password: str


@users_router.get("/auth/config")
async def auth_config():
    return {"password_required": bool(_password())}


@users_router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    # 06/11/2026 (agente di prova): X-Real-IP lo può inventare chiunque. Ci si fida solo se c'è davanti un
    # proxy nostro (Docker con nginx: TRUST_PROXY=1) e la richiesta arriva davvero da lui.
    peer = request.client.host if request.client else "?"
    ip = (request.headers.get("x-real-ip") or peer) if os.environ.get("TRUST_PROXY") == "1" else peer
    now = time.time()
    total = sum(1 for v in _fails.values() for t in v if now - t < 900)
    if total >= 100:   # limite complessivo: niente tentativi infiniti anche cambiando indirizzo
        raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto")
    if len(_fails) > 1000:   # pulizia: si tengono solo gli indirizzi con tentativi recenti
        for k in [k for k, v in _fails.items() if not v or now - v[-1] > 900]:
            _fails.pop(k, None)
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    if len(recent) >= 8:
        raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto")
    if not _password() or not hmac.compare_digest(body.password.encode(), _password().encode()):
        _fails[ip] = recent + [now]
        raise HTTPException(401, "Password errata")
    _fails.pop(ip, None)
    token = make_token()
    response.set_cookie(COOKIE, token, max_age=TOKEN_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return {"token": token}


@users_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    # Esci = tutti i gettoni dati finora smettono di valere (c'è un solo utente).
    if _password() and valid_token(_token_of(request)):
        new_generation()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@users_router.get("/me")
async def me(member: dict = Depends(require_approved)):
    return member


@users_router.get("/users")
async def list_users(member: dict = Depends(require_approved)):
    return {"roles": ["admin"], "users": [member]}


@users_router.patch("/users/{user_id}/role")
async def set_role(user_id: str, member: dict = Depends(require_approved)):
    raise HTTPException(403, "Con l'accesso locale c'è un solo utente")
