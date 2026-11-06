"""SentinelAI per Windows: avvia il server dentro il programma, apre la finestra dell'app e resta
nell'area di notifica (vicino all'orologio).

  SentinelAI.exe                 apre l'app (se è già aperta, mostra solo la finestra)
  SentinelAI.exe --minimizzato   parte solo con l'icona (usato dall'avvio con Windows)
  SentinelAI.exe --prova FILE    prova automatica senza finestra (CI): scrive il risultato in FILE

Dati in %LOCALAPPDATA%\\SentinelAI (database, clip, impostazioni, registro)."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

APP = "SentinelAI"
FROZEN = getattr(sys, "frozen", False)
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
try:
    VERSION = (BASE / "VERSIONE").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "sviluppo"
BACKEND = BASE / "backend"
STATIC = BASE / "static" if FROZEN else BASE / "frontend" / "build"
MODELS = BASE / "models"
ICON = BASE / "icon-192.png" if FROZEN else BASE / "frontend" / "public" / "icon-192.png"
DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP
DEFAULT_PORT = 8765

DATA.mkdir(parents=True, exist_ok=True)
LOG = DATA / "sentinelai.log"
PORT_FILE = DATA / "porta.txt"
LOG_MAX = 5_000_000


class RotatingLog:
    """Registro che resta sotto i 5 MB anche se il programma non si chiude mai (più la copia precedente)."""

    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        self.f = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, text):
        with self.lock:
            try:
                if self.f.tell() > LOG_MAX:
                    self.f.close()
                    self.path.replace(self.path.with_suffix(".log.1"))
                    self.f = open(self.path, "a", encoding="utf-8", buffering=1)
            except OSError:
                pass
            return self.f.write(text)

    def flush(self):
        with self.lock:
            self.f.flush()

    def isatty(self):
        return False


if sys.stdout is None or sys.stderr is None or FROZEN:
    # Nel programma con finestra non c'è console: tutto va nel registro (sennò uvicorn si blocca).
    sys.stdout = sys.stderr = RotatingLog(LOG)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def load_config() -> dict:
    p = DATA / "config.json"
    cfg = {"port": DEFAULT_PORT, "password": "", "rete": False,
           # Login con Google: client "App desktop" creato su console.cloud.google.com + indirizzi ammessi.
           "google_client_id": "", "google_client_secret": "", "google_emails": []}
    try:
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            return r.status == 200 and json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


def port_free(port: int, host="127.0.0.1") -> bool:
    with socket.socket() as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def lan_addresses() -> list:
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)} | {socket.gethostname().lower()})
    except OSError:
        return []


def make_app(data_dir: Path, password: str, rete: bool = False, google: dict = None):
    # Solo questi nomi possono chiamare il server: un sito che si finge 127.0.0.1 (DNS rebinding) viene rifiutato.
    hosts = ["127.0.0.1", "localhost"] + (lan_addresses() if rete else [])
    os.environ.update(MONGO_URL=f"sqlite:///{data_dir.as_posix()}", DB_NAME="sentinelai", DATA_DIR=str(data_dir),
                      APP_PASSWORD=password, SENTINEL_MODEL_DIR=str(MODELS), CORS_ORIGINS="",
                      ALLOWED_HOSTS=",".join(hosts), SENTINEL_LOG=str(LOG),
                      GOOGLE_CLIENT_ID=(google or {}).get("google_client_id", "") or "",
                      GOOGLE_CLIENT_SECRET=(google or {}).get("google_client_secret", "") or "",
                      GOOGLE_EMAILS=",".join((google or {}).get("google_emails") or []))
    sys.path.insert(0, str(BACKEND))
    import server  # noqa: E402  (legge le variabili qui sopra)
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    app = server.app
    app.mount("/static", StaticFiles(directory=str(STATIC / "static")), name="static")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(404, "Non trovato")
        f = (STATIC / path).resolve()
        if path and f.is_file() and STATIC.resolve() in f.parents:
            headers = {"Cache-Control": "no-cache"} if path in ("sw.js", "manifest.json") else None
            return FileResponse(str(f), headers=headers)
        return FileResponse(str(STATIC / "index.html"), headers={"Cache-Control": "no-cache"})

    return app


def start_server(app, host: str, port: int):
    import uvicorn
    cfg = uvicorn.Config(app, host=host, port=port, log_config=None, log_level="warning", ws_max_size=4 * 1024 * 1024)
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True, name="server")
    t.start()
    return srv


def find_browser():
    pf = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for base in pf:
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = Path(base) / rel
            if base and p.exists():
                return p
    return None


WINDOW_TITLE = "SentinelAI · Vision Guard"   # titolo della pagina = titolo della finestra
WINDOW_CLASS = "Chrome_WidgetWin_1"          # finestre di Edge/Chrome (non la cartella "SentinelAI" di Esplora file)
_open_lock = threading.Lock()
_last_open = 0.0


def focus_existing_window() -> bool:
    """Se la finestra di SentinelAI è già aperta la porta davanti (anche se ridotta a icona) e risponde True."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith(WINDOW_TITLE):
                    cls = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(hwnd, cls, 64)
                    if cls.value == WINDOW_CLASS:
                        found.append(hwnd)
                        return False
        return True

    user32.EnumWindows(each, 0)
    if not found:
        return False
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)            # SW_RESTORE
    # Windows lascia passare in primo piano solo se il processo "ha appena ricevuto un input":
    # il trucco del tasto ALT premuto e rilasciato sblocca SetForegroundWindow.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    return True


def open_window(port: int):
    """Una sola finestra: doppio clic sull'icona o programma lanciato due volte la portano solo davanti."""
    global _last_open
    with _open_lock:
        if focus_existing_window():
            return
        if time.monotonic() - _last_open < 8:
            return          # la finestra sta ancora aprendo: il secondo clic non ne apre un'altra
        _last_open = time.monotonic()
        url = f"http://127.0.0.1:{port}/"
        exe = find_browser()
        if exe:
            # Finestra a sé (modalità app), con un profilo suo: i permessi della webcam restano salvati.
            subprocess.Popen([str(exe), f"--app={url}", f"--user-data-dir={DATA / 'finestra'}", "--no-first-run",
                              "--no-default-browser-check", "--window-size=1440,900"], close_fds=True)
        else:
            webbrowser.open(url)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, f'"{sys.executable}" --minimizzato')
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass


def run_tray(port: int, srv):
    import pystray
    from PIL import Image

    def apri(icon=None, item=None):
        open_window(port)

    def autostart(icon, item):
        set_autostart(not autostart_enabled())

    def cartella(icon, item):
        os.startfile(str(DATA))  # noqa: S606 (solo Windows)

    def registro(icon, item):
        os.startfile(str(LOG))  # si apre col Blocco note

    def esci(icon, item):
        srv.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Apri SentinelAI", apri, default=True),
        pystray.MenuItem("Avvia con Windows", autostart, checked=lambda item: autostart_enabled()),
        pystray.MenuItem("Apri registro", registro),
        pystray.MenuItem("Cartella dei dati", cartella),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Esci", esci),
    )
    icon = pystray.Icon(APP, Image.open(ICON), f"SentinelAI {VERSION}", menu)
    icon.run()


# ------------------------------------------------------------------ prova automatica (CI)

def prova(out_file: str) -> int:
    import tempfile
    lines, ok = [], True

    def check(cond, what):
        nonlocal ok
        ok &= bool(cond)
        lines.append(("OK  " if cond else "NO  ") + what)

    try:
        data = Path(tempfile.mkdtemp(prefix="sentinel-prova-"))
        app = make_app(data, "")
        port = next(p for p in range(18765, 18865) if port_free(p))
        start_server(app, "127.0.0.1", port)
        for _ in range(240):
            if health(port):
                break
            time.sleep(0.5)
        check(health(port), f"server avviato (porta {port})")
        get = lambda path: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=20).read())
        h = get("/api/health")
        check(h["model_loaded"], f"modello caricato: {h}")
        import detection
        check(detection.detector.kind == "onnx", f"motore: {detection.detector.kind}")
        cams = get("/api/cameras")
        check(cams and cams[0]["type"] == "demo", "telecamera demo")
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read()
        check(b'id="root"' in page, "pagina dell'app")
        man = get("/manifest.json")
        check(man.get("display") == "standalone", "manifest installabile")

        import cv2
        cap = cv2.VideoCapture(str(STATIC / "demo.mp4"))
        frames = []
        while len(frames) < 90:
            r, f = cap.read()
            if not r:
                break
            frames.append(f)
        check(len(frames) >= 30, f"video demo letto ({len(frames)} fotogrammi)")
        t0 = time.time()
        dets = [detection.detector.detect(f, 0.4, 0.5, detection.DEFAULT_CLASSES) for f in frames[::6]]
        ms = (time.time() - t0) / max(1, len(dets)) * 1000
        people = sum(1 for d in dets for c, _, _ in d if c == 0)
        check(people >= 3, f"persone riconosciute nel demo: {people} in {len(dets)} fotogrammi ({ms:.0f} ms a fotogramma)")

        from websockets.sync.client import connect
        with connect(f"ws://127.0.0.1:{port}/api/ws/stream?token=", max_size=8 * 1024 * 1024) as ws:
            ws.send(json.dumps({"type": "start", "camera_id": cams[0]["id"], "tz_offset": -60}))
            check(json.loads(ws.recv(timeout=30))["type"] == "ready", "streaming pronto")
            tracks = 0
            for f in frames[:40]:
                ws.send(cv2.imencode(".jpg", cv2.resize(f, (640, 360)))[1].tobytes())
                m = json.loads(ws.recv(timeout=30))
                tracks = max(tracks, len(m["tracks"]))
            check(tracks >= 1, f"streaming con oggetti tracciati (max {tracks})")

        import clips
        jpgs = [(i / 10, cv2.imencode(".jpg", cv2.resize(f, (640, 360)))[1].tobytes()) for i, f in enumerate(frames[:30])]
        mp4, dur = clips.encode_mp4(jpgs)
        check(len(mp4) > 5000 and mp4[4:8] == b"ftyp", f"clip MP4 H.264: {len(mp4)} byte, {dur} s")
        x = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events/export?format=xlsx", timeout=20).read()
        check(x[:2] == b"PK", "esportazione Excel")
        from zoneinfo import ZoneInfo
        check(ZoneInfo("Europe/Rome") is not None, "fusi orari (Europe/Rome) disponibili")
        lg = get("/api/log?lines=200")
        check(lg["available"] and "YOLOv8 caricato" in lg["text"], "registro leggibile dall'app")
        check(get("/api/monitor") == {}, "nessuna telecamera di rete accesa all'avvio")
    except Exception:
        ok = False
        lines.append("ERRORE\n" + traceback.format_exc())
    lines.append("PROVA OK" if ok else "PROVA FALLITA")
    Path(out_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


_MUTEX = None


def single_instance() -> bool:
    """True se questo è l'unico SentinelAI acceso per l'utente. 06/11/2026 (agente di prova): prima bastava
    che la porta del config fosse occupata da un altro programma per avere due server sugli stessi dati."""
    global _MUTEX
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _MUTEX = k32.CreateMutexW(None, False, "Local\\SentinelAI-istanza")
    return ctypes.get_last_error() != 183   # ERROR_ALREADY_EXISTS


def running_port():
    try:
        return int(PORT_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def main():
    args = sys.argv[1:]
    if args[:1] == ["--prova"]:
        os._exit(prova(args[1] if len(args) > 1 else "prova.txt"))
    cfg = load_config()
    if not single_instance():
        # Già acceso (anche se sta ancora caricando il modello): solo la finestra, nessun secondo server.
        for _ in range(60):
            p = running_port()
            if p and health(p):
                if "--minimizzato" not in args:
                    open_window(p)
                return
            time.sleep(0.5)
        return
    port = int(cfg.get("port") or DEFAULT_PORT)
    if not port_free(port):
        port = next(p for p in range(port + 1, port + 50) if port_free(p))
    PORT_FILE.write_text(str(port))
    rete = bool(cfg.get("rete"))
    if rete and not (cfg.get("password") or cfg.get("google_client_id")):
        # Aperto alla rete senza login = chiunque in casa (o un ospite sul Wi-Fi) comanda le telecamere.
        log('"rete": true ignorato: serve anche una "password" o il login con Google in config.json')
        rete = False
    host = "0.0.0.0" if rete else "127.0.0.1"
    log(f"avvio SentinelAI {VERSION} su {host}:{port}, dati in {DATA}")
    srv = start_server(make_app(DATA, cfg.get("password", ""), rete, cfg), host, port)
    for _ in range(120):
        if health(port):
            break
        time.sleep(0.5)
    if "--minimizzato" not in args:
        open_window(port)
    try:
        run_tray(port, srv)
    except Exception:
        log("icona di notifica non disponibile:\n" + traceback.format_exc())
        while not srv.should_exit:
            time.sleep(1)
    srv.should_exit = True
    time.sleep(1)


if __name__ == "__main__":
    main()
