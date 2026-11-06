"""Accesso locale con una password unica (05/11/2026): sostituisce Clerk per l'uso a casa.

- APP_PASSWORD vuota  -> nessun login (solo per prove su una rete fidata).
- APP_PASSWORD impostata -> il browser fa login una volta e riceve un gettone firmato (30 giorni),
  sia come cookie (serve a immagini, video ed esportazioni) sia da mandare come Bearer / ?token=.
Gli stessi nomi di prima (require_approved, users_router, ws_member) così server.py non cambia."""
import base64
import hashlib
import asyncio
import hmac
import os
import re
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
_slow: dict[str, float] = {}          # ultimo tentativo per indirizzo quando il freno è attivo
_good_ips: dict[str, float] = {}      # indirizzi da cui si è già entrati con la password giusta
_pw_lock = asyncio.Lock()             # due cambi di password insieme: uno alla volta (5° giro dell'agente)


# 06/11/2026: la password si può mettere, cambiare o togliere dall'app (Impostazioni). Si salva come impronta
# scrypt in DATA_DIR/.app_password; se quel file non c'è vale APP_PASSWORD (Docker, .env). Il login con Google
# è stato tolto su richiesta di Roberto.
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def _hash_file() -> Path:
    return _data_file(".app_password")


def _stored_hash() -> str:
    """Impronta salvata. 4° giro dell'agente: un file VUOTO o ROVINATO (es. corrente mancata) non deve mai
    voler dire "nessuna password": resta bloccato (va cancellato a mano, vedi LEGGIMI) e lo si scrive nel registro."""
    p = _hash_file()
    if not p.exists():
        return ""
    try:
        h = p.read_text().strip()
    except OSError:
        h = ""
    if not re.fullmatch(r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}", h):
        import logging
        logging.getLogger("auth").error("file della password %s vuoto o rovinato: accesso bloccato. "
                                        "Per sbloccare cancellalo (si riapre senza password).", p)
        return "rovinato"
    return h


def password_file_ok() -> bool:
    """True se c'è una password valida salvata dall'app (per la versione Windows con "rete")."""
    h = _stored_hash()
    return bool(h) and h != "rovinato"


def _hash(pw: str, salt: bytes = None) -> str:
    salt = salt or secrets.token_bytes(16)
    d = hashlib.scrypt(pw.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${d.hex()}"


def check_password(pw: str) -> bool:
    stored = _stored_hash()
    if stored == "rovinato":
        return False
    if stored:
        try:
            _, salt, digest = stored.split("$")
            return hmac.compare_digest(_hash(pw, bytes.fromhex(salt)).split("$")[2], digest)
        except ValueError:
            return False
    env = os.environ.get("APP_PASSWORD", "")
    return bool(env) and hmac.compare_digest(pw.encode(), env.encode())


def _password() -> str:
    """Qualcosa che cambia quando cambia la password (entra nella chiave dei gettoni); vuoto = nessuna password."""
    return _stored_hash() or os.environ.get("APP_PASSWORD", "")


def login_required() -> bool:
    return bool(_password())


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
    return {"password_required": login_required(), "password": login_required(),
            "password_from_env": bool(os.environ.get("APP_PASSWORD")) and not _stored_hash()}


def _client_ip(request: Request) -> str:
    # 06/11/2026 (agente di prova): X-Real-IP lo può inventare chiunque. Ci si fida solo se c'è davanti un
    # proxy nostro (Docker con nginx: TRUST_PROXY=1) e la richiesta arriva davvero da lui.
    peer = request.client.host if request.client else "?"
    return (request.headers.get("x-real-ip") or peer) if os.environ.get("TRUST_PROXY") == "1" else peer


def _signed_by_us(token: str) -> bool:
    """Gettone firmato da noi, anche se scaduto da poco (60 giorni): vuol dire che è un dispositivo di casa."""
    try:
        exp, sig = token.split(".", 1)
        good = base64.urlsafe_b64encode(hmac.new(_secret(), exp.encode(), hashlib.sha256).digest()).rstrip(b"=")
        return hmac.compare_digest(sig.encode("utf-8", "replace"), good) and int(exp) > time.time() - 60 * 86400
    except (ValueError, AttributeError, TypeError, UnicodeError):
        return False


def check_attempt(request: Request) -> str:
    """Limiti prima di controllare una password (login e cambio password). Ritorna l'indirizzo.
    - al massimo 8 errori in 15 minuti per indirizzo;
    - oltre 100 errori in 15 minuti in tutto, gli indirizzi SCONOSCIUTI possono provare solo una volta ogni 5 s
      ciascuno. 4° giro dell'agente: il freno unico per tutto il server teneva fuori Roberto finché l'attaccante
      continuava; ora chi è già entrato da quell'indirizzo, o ha un gettone nostro, non viene frenato."""
    ip, now = _client_ip(request), time.time()
    if len(_fails) > 1000:   # pulizia: si tengono solo gli indirizzi con tentativi recenti
        for k in [k for k, v in _fails.items() if not v or now - v[-1] > 900]:
            _fails.pop(k, None)
    if len(_slow) > 5000:
        _slow.clear()
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    if len(recent) >= 8:
        raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto")
    known = now - _good_ips.get(ip, 0) < 30 * 86400 or _signed_by_us(_token_of(request))
    if not known and sum(1 for v in _fails.values() for t in v if now - t < 900) >= 100:
        # ogni indirizzo sconosciuto al massimo 1 tentativo ogni 5 s, e TUTTI gli sconosciuti insieme al massimo
        # 1 ogni 2 s: cambiare indirizzo non serve più a provare password a raffica.
        # Chi da quell'indirizzo non ha ancora sbagliato non aspetta il posto comune (sennò un attaccante veloce
        # lo occupa sempre e un dispositivo nuovo di Roberto non entra mai).
        clean = not recent
        if now - _slow.get(ip, 0) < 5 or (not clean and now - _slow.get("*", 0) < 2):
            raise HTTPException(429, "Troppi tentativi: riprova tra qualche secondo")
        _slow[ip] = now
        if not clean:
            _slow["*"] = now
    return ip


def record_failure(ip: str):
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < 900] + [now]


@users_router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    ip = check_attempt(request)
    # scrypt in un thread: non ferma il server mentre calcola
    good = await asyncio.to_thread(check_password, body.password)
    if not good:
        record_failure(ip)
        raise HTTPException(401, "Password errata")
    _fails.pop(ip, None)
    _good_ips[ip] = time.time()
    token = make_token()
    from server import real_scheme
    response.set_cookie(COOKIE, token, max_age=TOKEN_DAYS * 86400, httponly=True, samesite="lax",
                        secure=real_scheme(request.headers, request.url.scheme) == "https")
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



class PasswordIn(BaseModel):
    current: str = ""
    new: str = ""


@users_router.put("/auth/password")
async def set_password(body: PasswordIn, request: Request, response: Response, member: dict = Depends(require_approved)):
    async with _pw_lock:
        # ricontrollo dentro il lucchetto: se un altro cambio è appena passato, questo gettone non vale più
        if login_required() and not valid_token(_token_of(request)):
            raise HTTPException(401, "Accesso richiesto")
        return await _set_password(body, request, response)


async def _set_password(body: PasswordIn, request: Request, response: Response):
    """Imposta, cambia o toglie (new vuota) la password dell'app. Se c'è già una password va scritta quella attuale.
    I gettoni dati prima smettono di valere; chi la cambia riceve subito un gettone nuovo e resta dentro."""
    if login_required():
        ip = check_attempt(request)
        if not await asyncio.to_thread(check_password, body.current):
            record_failure(ip)   # 4° giro dell'agente: anche qui si contano gli errori (prima tentativi infiniti)
            raise HTTPException(403, "La password attuale non è giusta")
    new = body.new
    if new and len(new.strip()) < 6:
        raise HTTPException(422, "La password deve avere almeno 6 caratteri")
    if len(new) > 200:
        raise HTTPException(422, "Password troppo lunga")
    p = _hash_file()
    if new:
        tmp = p.with_suffix(".tmp")
        digest = await asyncio.to_thread(_hash, new)
        with open(tmp, "w") as f:
            f.write(digest)
            f.flush()
            os.fsync(f.fileno())     # su disco prima di sostituire: niente file vuoto dopo un calo di corrente
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(p)
    else:
        if os.environ.get("SENTINEL_RETE") == "1":
            # 4° giro dell'agente: con "rete" accesa togliere la password apriva a tutta la rete di casa.
            raise HTTPException(400, "L'app è aperta alla rete di casa: prima togli \"rete\" da config.json e riavvia")
        if os.environ.get("APP_PASSWORD") and not p.exists():
            raise HTTPException(400, "Questa password è scritta nel file di configurazione (.env o config.json): si toglie da lì")
        p.unlink(missing_ok=True)   # con APP_PASSWORD presente si torna a quella
    new_generation()
    if not login_required():
        response.delete_cookie(COOKIE)
        return {"password_required": False, "token": ""}
    token = make_token()
    from server import real_scheme
    response.set_cookie(COOKIE, token, max_age=TOKEN_DAYS * 86400, httponly=True, samesite="lax",
                        secure=real_scheme(request.headers, request.url.scheme) == "https")
    return {"password_required": True, "token": token}
