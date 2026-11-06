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

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

COOKIE = "sentinel_token"
TOKEN_DAYS = 30
LOCAL_MEMBER = {"user_id": "locale", "role": "admin", "email": "", "name": "Amministratore", "env": "locale"}

users_router = APIRouter(prefix="/api")
_fails: dict[str, list[float]] = {}


def _google() -> tuple:
    """(client_id, client_secret, indirizzi ammessi) del login con Google; vuoto = spento."""
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    emails = {e.strip().lower() for e in os.environ.get("GOOGLE_EMAILS", "").split(",") if e.strip()}
    return (cid, os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(), emails) if cid else ("", "", set())


def login_required() -> bool:
    return bool(_password() or _google()[0])


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
    if login_required() and not valid_token(_token_of(request)):
        raise HTTPException(401, "Accesso richiesto")
    return LOCAL_MEMBER


async def ws_member(token: str) -> dict | None:
    return LOCAL_MEMBER if not login_required() or valid_token(token) else None


class LoginIn(BaseModel):
    password: str


@users_router.get("/auth/config")
async def auth_config():
    return {"password_required": login_required(), "password": bool(_password()), "google": bool(_google()[0])}


@users_router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    # 06/11/2026 (agente di prova): X-Real-IP lo può inventare chiunque. Ci si fida solo se c'è davanti un
    # proxy nostro (Docker con nginx: TRUST_PROXY=1) e la richiesta arriva davvero da lui.
    peer = request.client.host if request.client else "?"
    ip = (request.headers.get("x-real-ip") or peer) if os.environ.get("TRUST_PROXY") == "1" else peer
    now = time.time()
    if len(_fails) > 1000:   # pulizia: si tengono solo gli indirizzi con tentativi recenti
        for k in [k for k, v in _fails.items() if not v or now - v[-1] > 900]:
            _fails.pop(k, None)
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    if len(recent) >= 8:
        raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto")
    good = bool(_password()) and hmac.compare_digest(body.password.encode(), _password().encode())
    if not good:
        _fails[ip] = recent + [now]
        # Limite complessivo (niente tentativi infiniti cambiando indirizzo): vale solo per chi SBAGLIA,
        # così chi ha la password giusta entra sempre (2° giro dell'agente di prova).
        if sum(1 for v in _fails.values() for t in v if now - t < 900) >= 100:
            raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto")
        raise HTTPException(401, "Password errata")
    _fails.pop(ip, None)
    token = make_token()
    response.set_cookie(COOKIE, token, max_age=TOKEN_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return {"token": token}


@users_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    # Esci = tutti i gettoni dati finora smettono di valere (c'è un solo utente).
    if login_required() and valid_token(_token_of(request)):
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


# ---------------------------------------------------------------- login con Google (06/11/2026)
# OAuth 2.0 con PKCE e "state", come raccomanda Google per le app installate: la password Google la vede solo
# Google; a noi arriva un codice che scambiamo per sapere l'email (verificata). Entra solo chi è in GOOGLE_EMAILS.
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
_pending: dict[str, dict] = {}


def _callback_url(request: Request) -> str:
    # Il nome viene da Host (già controllato dal middleware); la porta, senza un proxy davanti, è quella su cui
    # ascolta davvero il server: chi chiama non può farla puntare a un'altra porta del PC (2° giro dell'agente).
    from server import real_scheme
    scheme = real_scheme(request.headers, request.url.scheme)
    host = request.headers.get("host", "")
    if os.environ.get("TRUST_PROXY") != "1":
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        port = (request.scope.get("server") or ("", 0))[1]
        host = f"{name}:{port}" if port else name
    return f"{scheme}://{host}/api/auth/google/callback"


def _back(error: str = "", token: str = "") -> RedirectResponse:
    # Solo codici fissi dopo il #: la pagina li traduce, così nessuno può far comparire un testo a piacere.
    frag = f"token={quote(token)}" if token else f"errore={quote(error)}"
    return RedirectResponse(f"/sign-in#{frag}", status_code=302)


@users_router.get("/auth/google/start")
async def google_start(request: Request):
    cid, _, _ = _google()
    if not cid:
        raise HTTPException(404, "Login con Google non configurato")
    now = time.time()
    for k in [k for k, v in _pending.items() if v["exp"] < now]:
        _pending.pop(k, None)
    ip = request.client.host if request.client else "?"
    if sum(1 for v in _pending.values() if v.get("ip") == ip) >= 10:
        raise HTTPException(429, "Troppi accessi in corso: riprova tra qualche minuto")
    while len(_pending) >= 200:   # 2° giro dell'agente: si scarta il più vecchio, non si blocca il login a tutti
        _pending.pop(min(_pending, key=lambda k: _pending[k]["exp"]))
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    redirect = _callback_url(request)
    _pending[state] = {"verifier": verifier, "redirect": redirect, "exp": now + 600, "ip": ip}
    q = urlencode({"client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": "openid email profile",
                   "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"})
    return RedirectResponse(f"{GOOGLE_AUTH}?{q}", status_code=302)


@users_router.get("/auth/google/callback")
async def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    import httpx
    p = _pending.pop(state, None)
    if error:
        return _back("annullato")
    if not p or p["exp"] < time.time() or not code:
        return _back("scaduto")
    cid, secret, emails = _google()
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            t = await c.post(GOOGLE_TOKEN, data={"client_id": cid, "client_secret": secret, "code": code,
                                                 "code_verifier": p["verifier"], "grant_type": "authorization_code",
                                                 "redirect_uri": p["redirect"]})
            if t.status_code != 200:
                return _back("rifiutato")
            u = await c.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {t.json().get('access_token', '')}"})
            info = u.json() if u.status_code == 200 else {}
    except httpx.HTTPError:
        return _back("rete")
    email = str(info.get("email", "")).lower()
    if not email or info.get("email_verified") is not True:
        return _back("non_verificato")
    if email not in emails:
        return _back("non_ammesso")
    token = make_token()
    resp = _back(token=token)
    from server import real_scheme
    resp.set_cookie(COOKIE, token, max_age=TOKEN_DAYS * 86400, httponly=True, samesite="lax",
                    secure=real_scheme(request.headers, request.url.scheme) == "https")
    return resp
