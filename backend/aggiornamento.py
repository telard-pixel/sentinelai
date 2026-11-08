"""Aggiornamento dall'app (1.0.12, richiesta di Roberto: "aggiornarlo da app senza riscaricare").

Le versioni si prendono dal repository PUBBLICO telard-pixel/sentinelai-rilasci (solo gli installer: il codice
resta nel repository privato). Ogni versione ha un certificato firmato, rilascio.json + rilascio.json.sig
(RSA-PSS, chiave privata solo sul CT 103): numero di versione e impronta SHA-256 dell'installer Windows e del
pacchetto Linux. Si installa solo ciò che corrisponde al certificato, solo se è più nuovo di quello in uso.

- Windows (SENTINEL_AGGIORNAMENTO=windows, messo da sentinel_desktop): il server scarica e controlla il Setup,
  scrive un piccolo .cmd che aspetta la chiusura di SentinelAI, installa in silenzio e lo riapre; poi chiude l'app.
- Linux (SENTINEL_AGGIORNAMENTO=linux, nell'unità systemd): il servizio non può scrivere in /opt (gira come
  utente sentinelai): lascia solo una "richiesta"; il servizio root sentinelai-aggiorna (linux/aggiorna.sh)
  scarica, controlla la firma con la chiave della versione GIÀ installata, installa, riavvia e se la nuova
  non resta su rimette la precedente. Lo stato lo scrive in /run/sentinelai-aggiorna/stato.json.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("sentinelai.aggiornamento")

REPO = "telard-pixel/sentinelai-rilasci"
API_ULTIMA = f"https://api.github.com/repos/{REPO}/releases/latest"
SCARICA = f"https://github.com/{REPO}/releases/download"
ALLEGATI = f"https://api.github.com/repos/{REPO}/releases/assets"
MANIFESTO, FIRMA = "rilascio.json", "rilascio.json.sig"
NOME_SETUP = re.compile(r"SentinelAI-Setup-\d+\.\d+\.\d+\.exe")
NOME_LINUX = re.compile(r"SentinelAI-linux-\d+\.\d+\.\d+\.tar\.gz")
TAG = re.compile(r"v\d+\.\d+\.\d+")
STATO_LINUX = Path(os.environ.get("SENTINEL_STATO_AGGIORNAMENTO", "/run/sentinelai-aggiorna/stato.json"))
CACHE_S = 600
UA = {"User-Agent": "SentinelAI-aggiornamento"}

#: sentinel_desktop mette qui la funzione che chiude il programma (server, finestra, icona).
chiudi_app = None

_lock = threading.Lock()
_cache = {"t": 0.0, "dati": None}
_stato = {"fase": "fermo", "messaggio": "", "percentuale": None, "versione": None, "richiesto_alle": None}


class ErroreAggiornamento(Exception):
    pass


def modo() -> str:
    m = os.environ.get("SENTINEL_AGGIORNAMENTO", "")
    return m if m in ("windows", "linux") else ""


def versione_attuale() -> str:
    return os.environ.get("SENTINEL_VERSION", "sviluppo")


def numero(v: str):
    """'v1.0.12' o '1.0.12' -> (1, 0, 12). Le prove della CI ('1.0.0-prova.5') valgono 1.0.0."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def piu_nuova(ultima: str, attuale: str) -> bool:
    a, b = numero(ultima), numero(attuale)
    return bool(a and (b is None or a > b))


# ------------------------------------------------------------------ GitHub

def _get(url: str, timeout=20, accept="application/vnd.github+json"):
    return urllib.request.urlopen(urllib.request.Request(url, headers={**UA, "Accept": accept}), timeout=timeout)


def _scarica(url: str, dest: Path, atteso_max=600 * 1024 * 1024, avanzamento=None) -> None:
    tmp = dest.with_name(dest.name + ".parziale")
    try:
        with _get(url, timeout=60, accept="application/octet-stream") as r:
            tot = int(r.headers.get("Content-Length") or 0)
            if tot > atteso_max:
                raise ErroreAggiornamento("file troppo grande")
            fatto = 0
            with open(tmp, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    fatto += len(b)
                    if fatto > atteso_max:
                        raise ErroreAggiornamento("file troppo grande")
                    f.write(b)
                    if avanzamento and tot:
                        avanzamento(min(99, fatto * 100 // tot))
        os.replace(tmp, dest)
    except (OSError, urllib.error.URLError) as e:
        raise ErroreAggiornamento(f"scaricamento interrotto ({type(e).__name__})") from e
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _scarica_allegato(tag: str, nome: str, dest: Path, allegati: dict, atteso_max=600 * 1024 * 1024, avanzamento=None):
    """1.0.13: prima dall'API (allegato per numero), poi da github.com/.../releases/download. L'8/11/2026 il secondo
    dava 504 per ore mentre l'API funzionava. Chi manda il file non conta: vale solo la firma."""
    errore = None
    aid = allegati.get(nome)
    if aid:
        try:
            return _scarica(f"{ALLEGATI}/{aid}", dest, atteso_max, avanzamento)
        except ErroreAggiornamento as e:
            errore = e
    try:
        return _scarica(f"{SCARICA}/{tag}/{nome}", dest, atteso_max, avanzamento)
    except ErroreAggiornamento:
        raise errore or ErroreAggiornamento("versione non scaricabile da GitHub")


def controlla(forza: bool = False) -> dict:
    """Ultima versione pubblicata. Tenuta 10 minuti: GitHub ammette 60 domande l'ora senza login."""
    now = time.monotonic()
    with _lock:
        if not forza and _cache["dati"] and now - _cache["t"] < CACHE_S:
            dati = _cache["dati"]
        else:
            dati = None
    if dati is None:
        try:
            with _get(API_ULTIMA) as r:
                j = json.load(r)
            nomi = {a.get("name") for a in j.get("assets", [])}
            allegati = {a.get("name"): a.get("id") for a in j.get("assets", []) if str(a.get("id", "")).isdigit()}
            tag = j.get("tag_name", "")
            dati = {"ultima": tag if TAG.fullmatch(tag) else "", "note": (j.get("body") or "")[:2000],
                    "data": j.get("published_at"), "firmata": MANIFESTO in nomi and FIRMA in nomi,
                    "windows": any(NOME_SETUP.fullmatch(n or "") for n in nomi),
                    "linux": any(NOME_LINUX.fullmatch(n or "") for n in nomi), "errore": "", "allegati": allegati}
        except urllib.error.HTTPError as e:
            dati = {"ultima": "", "errore": "nessuna versione pubblicata" if e.code == 404 else f"GitHub ha risposto {e.code}"}
        except (OSError, ValueError) as e:
            dati = {"ultima": "", "errore": f"GitHub non raggiungibile ({type(e).__name__})"}
        with _lock:
            _cache.update(t=now, dati=dati)
    m, att = modo(), versione_attuale()
    pronta = bool(dati.get("ultima") and dati.get("firmata") and m and dati.get(m))
    return {**dati, "attuale": att, "modo": m, "disponibile": pronta and piu_nuova(dati["ultima"], att)}


# ------------------------------------------------------------------ firma

def chiave_pubblica() -> bytes:
    for base in (Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parent):
        p = base / "chiave_pubblica.pem"
        if p.is_file():
            return p.read_bytes()
    raise ErroreAggiornamento("chiave pubblica mancante")


def firma_valida(dati: bytes, firma: bytes, chiave: bytes | None = None) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    k = serialization.load_pem_public_key(chiave or chiave_pubblica())
    try:
        k.verify(firma, dati, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.AUTO),
                 hashes.SHA256())
        return True
    except InvalidSignature:
        return False


def leggi_manifesto(dati: bytes, firma: bytes, tag: str, attuale: str, chiave: bytes | None = None) -> dict:
    """Il certificato è firmato, è proprio della versione `tag` e questa è più nuova di quella in uso."""
    if not firma_valida(dati, firma, chiave):
        raise ErroreAggiornamento(f"la versione {tag} non ha una firma valida: non installata")
    try:
        m = json.loads(dati.decode("utf-8"))
    except ValueError as e:
        raise ErroreAggiornamento("certificato illeggibile") from e
    if m.get("progetto") != "sentinelai" or m.get("tag") != tag or m.get("versione") != tag[1:]:
        raise ErroreAggiornamento(f"il certificato non è della versione {tag}: non installata")
    if not piu_nuova(tag, attuale):
        raise ErroreAggiornamento(f"{tag} non è più nuova della {attuale}")
    return m


def impronta(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ stato

def _imposta(**kw):
    with _lock:
        _stato.update(kw)


def stato() -> dict:
    with _lock:
        s = dict(_stato)
    s["servizio"], s["servizio_recente"] = None, False
    if modo() == "linux":
        try:
            j = json.loads(STATO_LINUX.read_text(encoding="utf-8"))
            s["servizio"] = {k: str(j.get(k, ""))[:300] for k in ("fase", "messaggio", "tag", "ora")}
            # recente = scritto dal servizio root DOPO la nostra richiesta (orologio del CT, non del telefono)
            # (dopo un riavvio questo processo non sa quando è partita la richiesta: valgono gli ultimi 10 minuti)
            ora = datetime.fromisoformat(s["servizio"]["ora"]).timestamp()
            s["servizio_recente"] = ora >= s["richiesto_alle"] - 2 if s["richiesto_alle"] else time.time() - ora < 600
        except (OSError, ValueError, TypeError):
            pass
    return s


def _occupato() -> bool:
    """Un aggiornamento è già in corso? Su Linux la richiesta scade se il servizio root ha finito o dopo 20 minuti."""
    s = stato()
    if s["fase"] in ("scarico", "installo"):
        return True
    if s["fase"] == "richiesto":
        finito = s["servizio_recente"] and s["servizio"]["fase"] in ("errore", "fatto")
        return not finito and time.time() - (s["richiesto_alle"] or 0) < 1200
    return False


def avvia() -> dict:
    """Parte l'aggiornamento (in un thread). Errore se non c'è niente da installare o se è già in corso."""
    info = controlla(forza=True)
    if not info["modo"]:
        raise ErroreAggiornamento("aggiornamento dall'app non disponibile in questa installazione")
    if info.get("errore"):
        raise ErroreAggiornamento(info["errore"])
    if not info["disponibile"]:
        raise ErroreAggiornamento("nessuna versione nuova da installare")
    if _occupato():
        raise ErroreAggiornamento("aggiornamento già in corso")
    with _lock:
        if _stato["fase"] in ("scarico", "installo"):
            raise ErroreAggiornamento("aggiornamento già in corso")
        _stato.update(fase="scarico", messaggio="Scarico la versione nuova…", percentuale=0, versione=info["ultima"],
                      richiesto_alle=None)
    if info["modo"] == "windows":
        args = (info["ultima"], info.get("allegati") or {})
        fn = _windows
    else:
        args, fn = (info["ultima"],), _linux
    threading.Thread(target=fn, args=args, daemon=True, name="aggiornamento").start()
    return stato()


def _linux(tag: str):
    """Lascia la richiesta al servizio root (systemd .path la vede e avvia sentinelai-aggiorna)."""
    try:
        d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "aggiornamento"
        d.mkdir(mode=0o700, exist_ok=True)
        _imposta(richiesto_alle=time.time())
        (d / "richiesta").write_text(tag, encoding="utf-8")
        _imposta(fase="richiesto", messaggio="Installo la versione nuova: SentinelAI si riavvierà da solo…",
                 percentuale=None)
        logger.warning("aggiornamento a %s richiesto al servizio di sistema", tag)
    except OSError as e:
        _imposta(fase="errore", messaggio=f"Richiesta non scritta ({type(e).__name__})", percentuale=None)


def _windows(tag: str, allegati: dict):
    cartella = Path(os.environ.get("DATA_DIR", ".")).resolve() / "aggiornamento"
    try:
        cartella.mkdir(exist_ok=True)
        for f in cartella.glob("SentinelAI-Setup-*.exe"):
            f.unlink(missing_ok=True)
        man, fir = cartella / MANIFESTO, cartella / FIRMA
        _scarica_allegato(tag, MANIFESTO, man, allegati, 1 << 20)
        _scarica_allegato(tag, FIRMA, fir, allegati, 1 << 16)
        m = leggi_manifesto(man.read_bytes(), fir.read_bytes(), tag, versione_attuale())
        w = m.get("windows") or {}
        nome, sha = str(w.get("nome", "")), str(w.get("sha256", ""))
        if not NOME_SETUP.fullmatch(nome) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ErroreAggiornamento("certificato senza installer Windows")
        setup = cartella / nome
        _scarica_allegato(tag, nome, setup, allegati, avanzamento=lambda p: _imposta(percentuale=p))
        if impronta(setup) != sha:
            setup.unlink(missing_ok=True)
            raise ErroreAggiornamento("l'installer scaricato non corrisponde al certificato: non installato")
        logger.warning("aggiornamento: %s scaricato e verificato, installo", nome)
        installa_setup(setup)
    except ErroreAggiornamento as e:
        logger.warning("aggiornamento non riuscito: %s", e)
        _imposta(fase="errore", messaggio=str(e), percentuale=None)
    except Exception as e:  # noqa: BLE001 - qualunque errore va mostrato, non deve fermare il programma
        logger.exception("aggiornamento non riuscito")
        _imposta(fase="errore", messaggio=f"Errore imprevisto ({type(e).__name__})", percentuale=None)


def _cmd(s: str) -> str:
    """Percorso dentro un .cmd fra virgolette: il % va raddoppiato (sennò è una variabile)."""
    return str(s).replace("%", "%%")


def installa_setup(setup: Path):
    """Scrive e lancia aggiorna.cmd (aspetta che SentinelAI si chiuda, installa in silenzio, lo riapre), poi chiude."""
    exe = Path(sys.executable)
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise ErroreAggiornamento("installazione possibile solo dal programma installato (.exe)")
    cartella = setup.parent
    pid = os.getpid()
    esito, registro = cartella / "esito.txt", cartella / "setup.log"
    esito.unlink(missing_ok=True)
    script = cartella / "aggiorna.cmd"
    # Niente "timeout" (senza console non funziona): l'attesa è un ping a 127.0.0.1. Dopo 40 s si chiude per forza.
    script.write_text("\r\n".join([
        "@echo off",
        "set N=0",
        ":attendi",
        f'tasklist /FI "PID eq {pid}" /NH 2>nul | find " {pid} " >nul || goto installa',
        "set /a N+=1",
        f"if %N% GEQ 40 (taskkill /F /PID {pid} >nul 2>&1 & ping -n 3 127.0.0.1 >nul & goto installa)",
        "ping -n 2 127.0.0.1 >nul",
        "goto attendi",
        ":installa",
        f'"{_cmd(setup)}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="{_cmd(registro)}"',
        f'>"{_cmd(esito)}" echo %ERRORLEVEL%',   # "0> file" sarebbe il canale 0, non il numero 0 (CI)
        f'start "" "{_cmd(exe)}"',
        "",
    ]), encoding="oem" if os.name == "nt" else "utf-8")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000  # BREAKAWAY_FROM_JOB
    try:
        subprocess.Popen(["cmd.exe", "/d", "/c", str(script)], cwd=str(cartella), creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:   # alcuni lavori di Windows non permettono di uscire: senza quel permesso
        subprocess.Popen(["cmd.exe", "/d", "/c", str(script)], cwd=str(cartella),
                         creationflags=flags & ~0x01000000, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _imposta(fase="installo", messaggio="Installo la versione nuova: SentinelAI si chiude e si riapre da solo…",
             percentuale=None)

    def chiudi():
        time.sleep(3)   # l'app fa in tempo a leggere lo stato "installo"
        logger.warning("aggiornamento: chiudo SentinelAI per installare %s", setup.name)
        try:
            if chiudi_app:
                chiudi_app()
        except Exception:  # noqa: BLE001
            logger.exception("chiusura per l'aggiornamento")
        time.sleep(6)
        os._exit(0)     # se qualcosa tiene acceso il programma, lo script lo aspetterebbe 40 s: meglio uscire
    threading.Thread(target=chiudi, daemon=True, name="chiudi-per-aggiornare").start()


def esito_ultimo_setup() -> str | None:
    """Dopo il riavvio: codice d'uscita dell'ultimo Setup (0 = bene), poi il file si cancella."""
    p = Path(os.environ.get("DATA_DIR", ".")).resolve() / "aggiornamento" / "esito.txt"
    try:
        v = p.read_text(errors="replace").strip()
        p.unlink()
        return v
    except OSError:
        return None
