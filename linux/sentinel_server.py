"""SentinelAI come servizio Linux (CT Proxmox): stesso motore della versione Windows (YOLO11s ONNX + OpenCV + SQLite),
niente finestra: si apre dal browser su http://<indirizzo>:<porta>.

Uso:  python3 sentinel_server.py [--porta 8765] [--dati /var/lib/SentinelAI]
Verso la rete si apre SOLO se c'è una password (Impostazioni → Password di accesso, oppure imposta-password.py);
senza password resta su 127.0.0.1, come la versione Windows.
"""
import argparse
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def lan_ipv4() -> list:
    """Indirizzi IPv4 veri della macchina (nel CT il nome host spesso risolve solo a 127.0.1.1)."""
    out = set()
    try:
        txt = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True, timeout=5).stdout
        out |= {ln.split()[3].split("/")[0] for ln in txt.splitlines() if len(ln.split()) > 3}
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))     # nessun pacchetto parte: serve solo a sapere l'indirizzo d'uscita
            out.add(s.getsockname()[0])
    except OSError:
        pass
    host = socket.gethostname().lower()
    extra = [h.strip().lower() for h in os.environ.get("SENTINEL_NOMI", "").split(",") if h.strip()]
    return sorted(out | {host, f"{host}.local", f"{host}.lan"} | set(extra))


def password_ok(data: Path) -> bool:
    """Password impostata e valida (un file vuoto o rovinato NON conta: si resta su 127.0.0.1)."""
    try:
        return bool(re.fullmatch(r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}", (data / ".app_password").read_text().strip()))
    except OSError:
        return False


class Tee:
    """Scrive su due flussi: il primo (journal) e il registro su file. Un errore del file non ferma niente."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    def write(self, text):
        try:
            self.b.write(text)
        except Exception:   # noqa: BLE001 - il registro non deve mai fermare il servizio
            pass
        return self.a.write(text)

    def flush(self):
        for f in (self.a, self.b):
            try:
                f.flush()
            except Exception:   # noqa: BLE001
                pass

    def isatty(self):
        return False

    def fileno(self):
        return self.a.fileno()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=int(os.environ.get("SENTINEL_PORTA", 8765)))
    ap.add_argument("--dati", default=os.environ.get("SENTINEL_DATI", "/var/lib/SentinelAI"))
    a = ap.parse_args()
    data = Path(a.dati)
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:   # 1.0.9: database (password RTSP) e registro non leggibili dagli altri utenti del CT
        data.chmod(0o700)
    except OSError:
        pass
    # sentinel_desktop calcola DATA da LOCALAPPDATA all'import: lo puntiamo qui (niente ~/AppData su Linux).
    os.environ["LOCALAPPDATA"] = str(data.parent)
    sys.path.insert(0, str(BASE / "desktop"))
    import sentinel_desktop as d

    try:
        d.VERSION = (BASE / "VERSIONE").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    d.MODELS = Path(os.environ.get("SENTINEL_MODELLI", BASE / "models"))
    d.lan_addresses = lan_ipv4
    clips = Path(os.environ.get("SENTINEL_VIDEO", data / "video"))
    d.videos_folder = lambda: clips      # cartella predefinita dei video; dall'app se ne può scegliere un'altra
    os.environ["SENTINEL_LOG"] = str(data / "sentinelai.log")
    # 1.0.9: su Linux tutto andava solo nel journal e Impostazioni -> "Copia registro" diceva "non disponibile".
    # Ora ogni riga va sia nel journal (come prima) sia nel file del registro, che ruota a 5 MB come su Windows.
    # make_app usa d.LOG per SENTINEL_LOG: deve essere lo stesso file del Tee anche se --dati non si chiama SentinelAI
    d.LOG = data / "sentinelai.log"
    try:
        rlog = d.RotatingLog(d.LOG)
    except OSError as exc:   # agente di prova 1.0.9: file non scrivibile = il servizio non partiva più
        rlog = None
        print(f"registro su file non disponibile ({exc}): resta solo il journal", file=sys.stderr, flush=True)
    if rlog is not None:
        sys.stdout, sys.stderr = Tee(sys.stdout, rlog), Tee(sys.stderr, rlog)

    rete = password_ok(data)
    host = "0.0.0.0" if rete else "127.0.0.1"
    if not rete:
        d.log("nessuna password: resto su 127.0.0.1 (impostala con imposta-password.py, poi riavvia il servizio)")
    app = d.make_app(data, "", rete)
    # i gestori di logging creati prima (server, monitor) scrivono ancora sul vecchio stderr: li si sposta sul Tee
    import logging
    for lg in [logging.getLogger()] + [logging.getLogger(n) for n in list(logging.root.manager.loggerDict)]:
        for h in getattr(lg, "handlers", []):
            if isinstance(sys.stderr, Tee) and isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) in (sys.stdout.a, sys.stderr.a):
                h.setStream(sys.stderr)
    d.log(f"avvio SentinelAI {d.VERSION} su {host}:{a.porta}, dati in {data}, nomi ammessi: {', '.join(lan_ipv4())}")
    import uvicorn
    uvicorn.run(app, host=host, port=a.porta, log_level="warning", ws_max_size=4 * 1024 * 1024,
                # 1.0.12: niente compressione dei messaggi della diretta (JPEG in base64: non si comprime, costava CPU)
                ws_per_message_deflate=False,
                # 1.0.22: una richiesta lenta in corso non rimanda l'arresto (clip in corso salvate entro lo stop di systemd)
                timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
