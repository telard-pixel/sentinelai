"""SentinelAI per Windows: avvia il server dentro il programma, apre la finestra dell'app e resta
nell'area di notifica (vicino all'orologio).

Finestra (06/11/2026): WebView2 dentro il programma stesso (pywebview), non più Edge in modalità app.
Chiudendo la finestra il programma resta acceso vicino all'orologio e le telecamere continuano a essere
controllate; "Esci" dall'icona lo spegne. Se WebView2 manca si torna alla finestra di Edge.

  SentinelAI.exe                 apre l'app (se è già aperta, mostra solo la finestra)
  SentinelAI.exe --minimizzato   parte solo con l'icona (usato dall'avvio con Windows)
  SentinelAI.exe --prova FILE    prova automatica senza finestra (CI): scrive il risultato in FILE

Dati in %LOCALAPPDATA%\\SentinelAI (database, clip, impostazioni, registro)."""
import json
import os
import re
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
                if self.f.closed or self.f.tell() > LOG_MAX:
                    self.f.close()
                    try:
                        self.path.replace(self.path.with_suffix(".log.1"))
                    except OSError:
                        pass    # file in uso (antivirus, lettura dall'app): si riprova alla prossima scrittura
                    self.f = open(self.path, "a", encoding="utf-8", buffering=1)
                return self.f.write(text)
            except (OSError, ValueError):
                return 0        # il registro non deve mai fermare il programma

    def flush(self):
        with self.lock:
            try:
                self.f.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        return False


if sys.stdout is None or sys.stderr is None or FROZEN:
    # Nel programma con finestra non c'è console: tutto va nel registro (sennò uvicorn si blocca).
    sys.stdout = sys.stderr = RotatingLog(LOG)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def load_config() -> dict:
    p = DATA / "config.json"
    # La password di solito si imposta dall'app (Impostazioni → Password di accesso); "password" qui resta possibile.
    cfg = {"port": DEFAULT_PORT, "password": "", "rete": False}
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


def videos_folder() -> Path:
    """Cartella Video dell'utente (anche se spostata su un altro disco), poi \\SentinelAI."""
    if os.name == "nt":
        try:
            import ctypes
            import uuid as _uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
            u = _uuid.UUID("18989B1D-99B5-455B-841C-AB7C74E4DDFC")      # FOLDERID_Videos
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return Path(path) / APP
        except Exception:
            pass
    return Path.home() / "Videos" / APP


def bundled_ffmpeg():
    """ffmpeg incluso nel programma. Con IMAGEIO_FFMPEG_EXE impostato imageio-ffmpeg non lancia "ffmpeg -version"
    per controllarlo: quel controllo, sui PC col Terminale di Windows 11, poteva far comparire un lampo (agente 106)."""
    try:
        import imageio_ffmpeg
        found = sorted((Path(imageio_ffmpeg.__file__).parent / "binaries").glob("ffmpeg*"))
        exe = [f for f in found if f.suffix.lower() == ".exe"] or found
        return str(exe[0]) if exe else None
    except Exception:
        return None


def make_app(data_dir: Path, password: str, rete: bool = False):
    # Solo questi nomi possono chiamare il server: un sito che si finge 127.0.0.1 (DNS rebinding) viene rifiutato.
    hosts = ["127.0.0.1", "localhost"] + (lan_addresses() if rete else [])
    os.environ.update(MONGO_URL=f"sqlite:///{data_dir.as_posix()}", DB_NAME="sentinelai", DATA_DIR=str(data_dir),
                      APP_PASSWORD=password, SENTINEL_MODEL_DIR=str(MODELS), CORS_ORIGINS="",
                      ALLOWED_HOSTS=",".join(hosts), SENTINEL_LOG=str(LOG), SENTINEL_RETE="1" if rete else "0",
                      SENTINEL_VERSION=VERSION,
                      SENTINEL_CLIPS_DIR=str(videos_folder()))
    if FROZEN and os.name == "nt":
        os.environ["SENTINEL_AGGIORNAMENTO"] = "windows"   # 1.0.12: pulsante "Aggiorna" (backend/aggiornamento.py)
    ff = bundled_ffmpeg()
    if ff and not os.environ.get("IMAGEIO_FFMPEG_EXE"):
        os.environ["IMAGEIO_FFMPEG_EXE"] = ff
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
    cfg = uvicorn.Config(app, host=host, port=port, log_config=None, log_level="warning", ws_max_size=4 * 1024 * 1024,
                         ws_per_message_deflate=False,   # 1.0.12: JPEG in base64 non si comprime, costava CPU
                         # 1.0.22 (agente di prova): senza limite una richiesta lenta in corso (es. prova Telegram con
                         # internet giù, 60 s) rimandava l'arresto vero e le clip in corso non si salvavano
                         timeout_graceful_shutdown=5)
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True, name="server")
    t.start()
    srv.thread = t
    return srv


STOP_SECONDS = 25


def stop_server(srv, seconds: float = STOP_SECONDS):
    """1.0.22: Esci aspetta che il server abbia finito davvero (clip in corso salvata, mappa di calore scritta,
    database chiuso). Prima aveva 1 secondo: la clip di un allarme in corso andava persa e restava "REC…" per sempre."""
    srv.should_exit = True
    t = getattr(srv, "thread", None)
    if t is not None and t is not threading.current_thread():
        t.join(seconds)
        if t.is_alive():
            log(f"chiusura: il server non ha finito in {seconds:.0f} s, esco lo stesso")


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


# ------------------------------------------------------------------ finestra propria (WebView2)

SHOW_EVENT = "Local\\SentinelAI-mostra"   # il secondo avvio lo segnala: la finestra torna davanti
_APP_WINDOW = [None]   # la finestra per choose_folder (non come attributo di DesktopApi, raggiungibile dalla pagina)


def _harden_pywebview():
    """1.0.9 (revisione di sicurezza): pywebview cerca la funzione chiesta dalla pagina punto per punto, anche nei
    nomi che iniziano con "_" (es. "choose_folder.__globals__..."): uno script nella pagina poteva arrivare ai moduli
    Python ed eseguire comandi su Windows. Qui si accettano solo nomi semplici: niente punti, niente "_" iniziale."""
    import webview.util as wu
    orig = getattr(wu, "js_bridge_call", None)
    if orig is None or getattr(orig, "_sentinel_safe", False):
        return

    def safe_call(window, func_name, param, value_id):
        name = str(func_name or "")
        if "." in name or name.startswith("_") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            log(f"finestra: chiamata rifiutata dalla pagina ({name[:40]!r})")
            return None
        return orig(window, func_name, param, value_id)

    safe_call._sentinel_safe = True
    wu.js_bridge_call = safe_call
    for mod in list(sys.modules.values()):   # moduli già importati con "from webview.util import js_bridge_call"
        if getattr(mod, "__name__", "").startswith("webview") and getattr(mod, "js_bridge_call", None) is orig:
            mod.js_bridge_call = safe_call


class DesktopApi:
    """Comandi che la pagina può chiedere al programma (window.pywebview.api.*), solo nella finestra propria.
    Nessun attributo con riferimenti al programma: la finestra si prende da _APP_WINDOW (vedi _harden_pywebview)."""

    def choose_folder(self, current=""):
        import webview
        start = current if current and Path(current).is_dir() else str(videos_folder().parent)
        res = _APP_WINDOW[0].window.create_file_dialog(webview.FOLDER_DIALOG, directory=start)
        return res[0] if res else ""

    def open_folder(self, path=""):
        # Solo cartelle che esistono già (la predefinita si può creare): mai file o programmi.
        try:
            if not path:
                p = videos_folder()
                p.mkdir(parents=True, exist_ok=True)
            else:
                p = Path(path)
                if not p.is_dir():
                    return False
            os.startfile(str(p))  # noqa: S606 (solo Windows)
            return True
        except OSError:
            return False


class AppWindow:
    """Finestra WebView2 di SentinelAI. webview.start() deve girare nel thread principale."""

    def __init__(self, port: int):
        self.port = port
        self.window = None
        self.quitting = False
        self.ready = threading.Event()
        self.close_hint_done = False
        self.tray = None
        self.minimized = False
        self.session_ending = -1e9    # istante dell'ultimo "Windows si sta spegnendo"
        self.mode = "avvio"           # avvio → webview, oppure edge se WebView2 manca
        self.pending_show = False     # "mostra" arrivato prima che la finestra esistesse

    def create(self, hidden: bool):
        import webview
        # Grande ma dentro lo schermo (su un portatile 1366x768 la 1440x900 usciva dai bordi), centrata.
        w, h, x, y = 1440, 900, None, None
        try:
            sc = webview.screens[0]
            w, h = min(w, int(sc.width * 0.92)), min(h, int(sc.height * 0.88))
            x, y = sc.x + (sc.width - w) // 2, sc.y + (sc.height - h) // 3
        except Exception:
            pass
        _harden_pywebview()
        _APP_WINDOW[0] = self
        self.window = webview.create_window(
            "SentinelAI", f"http://127.0.0.1:{self.port}/", width=w, height=h, x=x, y=y,
            min_size=(min(900, w), min(600, h)), hidden=hidden, background_color="#090D14", text_select=True,
            js_api=DesktopApi())
        self.window.events.closing += self.on_closing
        self.window.events.loaded += lambda: self.ready.set()
        self.window.events.minimized += lambda: setattr(self, "minimized", True)
        self.window.events.restored += lambda: setattr(self, "minimized", False)
        self.window.events.maximized += lambda: setattr(self, "minimized", False)

    def on_closing(self):
        if self.quitting or self.tray is None or time.monotonic() - self.session_ending < 20:
            return True      # senza icona vicino all'orologio la X chiude davvero (sennò non si spegnerebbe più)
        # La X nasconde e basta: il server e le telecamere restano accesi (come chiudere Edge prima).
        # Con "Chiedi la password a ogni apertura" la pagina si richiude prima di sparire (1.0.5).
        def lock():
            try:
                self.window.evaluate_js("window.__sentinelLock && window.__sentinelLock()")
            except Exception:
                pass

        def hide():
            # evaluate_js aspetta che la pagina sia pronta (fino a 20 s): la X non deve aspettare
            if self.ready.is_set():
                t = threading.Thread(target=lock, daemon=True)
                t.start()
                t.join(2)
            self.window.hide()
        threading.Thread(target=hide, daemon=True).start()
        if not self.close_hint_done and self.tray is not None:
            self.close_hint_done = True
            try:
                self.tray.notify("SentinelAI resta acceso qui vicino all'orologio. Per spegnerlo: tasto destro → Esci.",
                                 "SentinelAI")
            except Exception:
                pass
        return False

    def show(self):
        if self.window is None:
            self.pending_show = True
            return
        try:
            self.window.show()
            if self.minimized:          # una finestra ingrandita resta ingrandita
                self.window.restore()
        except Exception:
            log("finestra: impossibile mostrarla:\n" + traceback.format_exc())

    def watch_session_end(self):
        """Spegnimento o disconnessione di Windows: la X non deve "annullare" la chiusura (bloccherebbe Windows)."""
        try:
            from Microsoft.Win32 import SystemEvents  # pythonnet, già caricato da pywebview

            def ending(sender, args):
                # non quitting=True: se lo spegnimento viene annullato la X deve tornare a nascondere (agente 104)
                self.session_ending = time.monotonic()
            SystemEvents.SessionEnding += ending
            self._session_handler = ending
        except Exception:
            log("avviso: spegnimento di Windows non intercettato:\n" + traceback.format_exc())

    def quit(self):
        self.quitting = True
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

    def run(self, hidden: bool) -> bool:
        """Blocca finché la finestra non viene chiusa con Esci. False se WebView2 non è disponibile."""
        if self.quitting:
            return True     # "Esci" premuto mentre partiva: niente finestra
        try:
            import webview
            if os.name == "nt":
                # Senza WebView2 pywebview NON dà errore: ripiega in silenzio su Internet Explorer (MSHTML),
                # dove l'app non funziona (agente di prova 104). Qui lo si scopre e si passa a Edge.
                import webview.platforms.winforms as wf
                if getattr(wf, "renderer", None) != "edgechromium":
                    raise RuntimeError(f"WebView2 non presente (motore disponibile: {getattr(wf, 'renderer', '?')})")
                self.watch_session_end()
            webview.settings["ALLOW_DOWNLOADS"] = True                 # clip ed Excel si scaricano
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # link esterni nel browser normale
            self.create(hidden and not self.pending_show)
            webview.start(gui="edgechromium", private_mode=False, storage_path=str(DATA / "finestra-app"))
            return True
        except Exception:
            log("finestra WebView2 non disponibile, uso Edge:\n" + traceback.format_exc())
            self.window = None
            self.mode = "edge"
            return False


def listen_show_requests(callback):
    """Aspetta il segnale del secondo avvio (doppio clic sull'icona del desktop) e mostra la finestra."""
    if os.name != "nt":
        return
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateEventW.restype = ctypes.c_void_p
    h = k32.CreateEventW(None, False, False, SHOW_EVENT)
    if not h:
        return

    def loop():
        while True:
            if k32.WaitForSingleObject(ctypes.c_void_p(h), 0xFFFFFFFF) == 0:
                callback()

    threading.Thread(target=loop, daemon=True, name="mostra").start()


def signal_show() -> bool:
    """Dal secondo avvio: chiede al SentinelAI già acceso di mostrare la sua finestra."""
    if os.name != "nt":
        return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenEventW.restype = ctypes.c_void_p
    h = k32.OpenEventW(0x0002, False, SHOW_EVENT)   # EVENT_MODIFY_STATE
    if not h:
        return False
    ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY: l'altro processo può venire davanti
    ok = bool(k32.SetEvent(ctypes.c_void_p(h)))
    k32.CloseHandle(ctypes.c_void_p(h))
    return ok


def run_tray(port: int, srv, show=None, on_exit=None, background=False):
    import pystray
    from PIL import Image

    def apri(icon=None, item=None):
        (show or (lambda: open_window(port)))()

    def autostart(icon, item):
        set_autostart(not autostart_enabled())

    def cartella(icon, item):
        os.startfile(str(DATA))  # noqa: S606 (solo Windows)

    def registro(icon, item):
        os.startfile(str(LOG))  # si apre col Blocco note

    def esci(icon, item):
        srv.should_exit = True
        icon.stop()
        if on_exit:
            on_exit()

    menu = pystray.Menu(
        pystray.MenuItem("Apri SentinelAI", apri, default=True),
        pystray.MenuItem("Avvia con Windows", autostart, checked=lambda item: autostart_enabled()),
        pystray.MenuItem("Apri registro", registro),
        pystray.MenuItem("Cartella dei dati", cartella),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Esci", esci),
    )
    icon = pystray.Icon(APP, Image.open(ICON), f"SentinelAI {VERSION}", menu)
    if background:
        threading.Thread(target=icon.run, daemon=True, name="icona").start()
        return icon
    icon.run()


# ------------------------------------------------------------------ prova automatica (CI)

def _ffmpeg_3s(kwargs):
    import imageio_ffmpeg
    return subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                             "-i", "nullsrc=s=64x64:d=3", "-f", "null", "-"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def console_windows_during(start) -> int:
    """Quante finestre del prompt (classico o Terminale di Windows 11) nuove e visibili compaiono mentre gira."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kinds = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow")

    def visible():
        found = set()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value in kinds and user32.IsWindowVisible(hwnd):
                found.add(hwnd)
            return True
        user32.EnumWindows(each, 0)
        return found

    base = visible()
    proc = start()
    new = set()
    limit = time.monotonic() + 15        # un ffmpeg bloccato non deve fermare la CI
    while proc.poll() is None and time.monotonic() < limit:
        new |= visible() - base
        time.sleep(0.02)
    if proc.poll() is None:
        proc.kill()
    return len(new)

def prova(out_file: str) -> int:
    import tempfile
    lines, ok = [], True

    def check(cond, what):
        nonlocal ok
        ok &= bool(cond)
        lines.append(("OK  " if cond else "NO  ") + what)
        try:   # scritto man mano: se il programma muore (crash nativo) si vede fin dove è arrivato
            Path(out_file).write_text("\n".join(lines) + "\n(in corso)\n", encoding="utf-8")
        except OSError:
            pass

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
        # 1.0.16: scelta automatica. Sul runner di GitHub non c'è una scheda vera (solo quella software di Windows):
        # DirectML va scartato e si usa OpenVINO sul processore.
        check(detection.detector.engine.startswith(("DirectML", "OpenVINO")), f"motore IA scelto: {detection.detector.engine}")
        lines.append(f"INFO schede video: {detection.schede_video()}")
        # Il plugin della scheda video deve essere nell'exe. Solo il file: chiedere get_versions("GPU") su un PC
        # senza scheda Intel (il runner) fa morire il processo (0xC0000005, CI 8/11/2026).
        import openvino
        gpu_dll = sorted(Path(openvino.__file__).parent.rglob("openvino_intel_gpu_plugin*.dll"))
        check(bool(gpu_dll), f"plugin GPU di OpenVINO incluso: {[p.name for p in gpu_dll]}")
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

        # 1.0.19: monitor risorse su Windows (memoria via ctypes: l'agente di prova temeva un errore a 64 bit)
        try:
            import risorse
            mp, mu, mt = risorse._memoria()
            check(mp and mu and mt and mp < mt, f"monitor risorse, memoria: programma {mp} MB, sistema {mu}/{mt} MB")
            check(risorse._cpu_sistema() is not None, f"monitor risorse, processore di sistema: {risorse._cpu_sistema()}")
        except Exception as exc:  # noqa: BLE001
            check(False, f"monitor risorse: {exc}")

        # 1.0.16: DirectML incluso nell'exe. Sul runner (Hyper-V) non c'è una scheda DirectX 12: onnxruntime ripiega
        # sul processore e il programma deve scartarlo (visto sopra: motore scelto). Con una scheda vera (PC di casa)
        # si confronta anche con OpenCV.
        import numpy as np
        try:
            import onnxruntime as ort
            dml = sorted(p.name for p in Path(ort.__file__).parent.rglob("DirectML*.dll"))
            check("DmlExecutionProvider" in ort.get_available_providers() and dml,
                  f"DirectML incluso: {dml}, motori {ort.get_available_providers()}")
            try:
                sess, hh, dms, dcpu = detection._sessione_directml()
            except RuntimeError as exc:
                lines.append(f"INFO DirectML non usabile qui (nessuna scheda DirectX 12): {exc}")
            else:
                ref = detection._opencv_net()
                diff = 0.0
                for f in frames[::30]:
                    blob = cv2.dnn.blobFromImage(cv2.resize(f, (detection.IMGSZ, hh)), 1 / 255.0,
                                                 (detection.IMGSZ, hh), swapRB=True)
                    ref.setInput(blob)
                    a = ref.forward()
                    b = sess.run(None, {sess.get_inputs()[0].name: blob})[0]
                    diff = max(diff, float(np.abs(a[0, 4:] - b[0, 4:]).max()))
                check(diff < 0.01, f"DirectML uguale a OpenCV (differenza max {diff:.4f}; {dms:.0f} ms, {dcpu:.2f} s di CPU)")
        except Exception as exc:  # noqa: BLE001
            check(False, f"DirectML: {exc}")

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
        if os.name == "nt":
            # 1.0.6: a ogni clip si apriva e chiudeva una finestra del prompt (ffmpeg). Controllo che si verifica da
            # solo: senza la correzione la finestra DEVE comparire (sennò il controllo non vede niente), con la
            # correzione no.
            seen_plain = console_windows_during(lambda: _ffmpeg_3s({}))
            seen_fixed = console_windows_during(lambda: _ffmpeg_3s(clips._no_window()))
            lines.append(f"INFO finestre del prompt: senza correzione {seen_plain}, con correzione {seen_fixed}")
            lines.append(f"INFO IMAGEIO_FFMPEG_EXE = {os.environ.get('IMAGEIO_FFMPEG_EXE')}")
            check(bool(os.environ.get("IMAGEIO_FFMPEG_EXE")) and Path(os.environ["IMAGEIO_FFMPEG_EXE"]).is_file(),
                  "ffmpeg incluso indicato a imageio-ffmpeg (niente controllo con finestra)")
            check(seen_fixed == 0, "clip senza finestra del prompt" + ("" if seen_plain else " (controllo non verificabile qui)"))
        x = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events/export?format=xlsx", timeout=20).read()
        check(x[:2] == b"PK", "esportazione Excel")
        from zoneinfo import ZoneInfo
        check(ZoneInfo("Europe/Rome") is not None, "fusi orari (Europe/Rome) disponibili")
        lg = get("/api/log?lines=200")
        check(lg["available"] and "YOLO11s caricato" in lg["text"], "registro leggibile dall'app")
        check(get("/api/monitor") == {}, "nessuna telecamera di rete accesa all'avvio")
        # 1.0.12: aggiornamento dall'app. La chiave pubblica e cryptography devono essere nell'exe; una firma falsa
        # va rifiutata (senza eccezioni); l'API risponde (la rete verso GitHub può mancare: conta solo che risponda).
        import aggiornamento
        check(b"BEGIN PUBLIC KEY" in aggiornamento.chiave_pubblica(), "chiave pubblica per gli aggiornamenti inclusa")
        check(aggiornamento.firma_valida(b"prova", b"\0" * 384) is False, "firma falsa rifiutata")
        info = get("/api/aggiornamento")
        lines.append(f"INFO aggiornamento: {info}")
        check(info["attuale"] == VERSION and info["modo"] == ("windows" if FROZEN and os.name == "nt" else ""),
              "controllo aggiornamenti")
    except Exception:
        ok = False
        lines.append("ERRORE\n" + traceback.format_exc())
    lines.append("PROVA OK" if ok else "PROVA FALLITA")
    Path(out_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


def stored_password_ok() -> bool:
    """Password impostata dall'app e valida (un file vuoto o rovinato NON conta: 4° giro dell'agente)."""
    import re
    try:
        return bool(re.fullmatch(r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}", (DATA / ".app_password").read_text().strip()))
    except OSError:
        return False


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


def _hook_aggiornamento(srv, win, args):
    """1.0.12: l'aggiornamento dall'app chiude il programma così (server, icona, finestra). Con
    --prova-aggiornamento <Setup.exe> (solo CI) reinstalla quel Setup con lo stesso percorso del pulsante."""
    try:
        import aggiornamento
    except Exception:
        log("aggiornamento dall'app non disponibile:\n" + traceback.format_exc())
        return

    def chiudi():
        srv.should_exit = True
        if win is not None:
            try:
                if win.tray is not None:
                    win.tray.stop()
            except Exception:
                pass
            win.quit()
        stop_server(srv, 20)     # l'aggiornamento aspetta il server (lo script dell'installer ne aspetta 40)
    aggiornamento.chiudi_app = chiudi
    if args[:1] == ["--prova-aggiornamento"] and len(args) > 1:
        import shutil

        def prova_agg():
            time.sleep(10)
            d = DATA / "aggiornamento"
            d.mkdir(exist_ok=True)
            dest = d / Path(args[1]).name
            shutil.copyfile(args[1], dest)
            log(f"prova aggiornamento: reinstallo {dest.name}")
            aggiornamento.installa_setup(dest)
        threading.Thread(target=prova_agg, daemon=True, name="prova-aggiornamento").start()


def main():
    args = sys.argv[1:]
    if args[:1] == ["--prova"]:
        os._exit(prova(args[1] if len(args) > 1 else "prova.txt"))
    cfg = load_config()
    if not single_instance():
        # Già acceso (anche se sta ancora caricando il modello): solo la finestra, nessun secondo server.
        for _ in range(240):   # fino a 2 minuti: su un PC lento il modello impiega un po' a caricarsi
            p = running_port()
            if p and health(p):
                if "--minimizzato" not in args and not signal_show():
                    open_window(p)     # SentinelAI vecchio (finestra di Edge) o segnale non disponibile
                return
            time.sleep(0.5)
        return
    port = int(cfg.get("port") or DEFAULT_PORT)
    if not port_free(port):
        port = next(p for p in range(port + 1, port + 50) if port_free(p))
    PORT_FILE.write_text(str(port))
    win = None
    if not os.environ.get("SENTINEL_FINESTRA_EDGE"):
        win = AppWindow(port)

        def show_any():   # finestra propria; se WebView2 manca quella di Edge
            open_window(port) if win.mode == "edge" else win.show()

        # Subito, prima del server: un secondo avvio durante il caricamento trova già il segnale (agente 104).
        listen_show_requests(show_any)
    rete = bool(cfg.get("rete"))
    if rete and not (cfg.get("password") or stored_password_ok()):
        # Aperto alla rete senza password = chiunque in casa (o un ospite sul Wi-Fi) comanda le telecamere.
        log('"rete": true ignorato: prima imposta una password (Impostazioni → Password di accesso)')
        rete = False
    host = "0.0.0.0" if rete else "127.0.0.1"
    log(f"avvio SentinelAI {VERSION} su {host}:{port}, dati in {DATA}")
    srv = start_server(make_app(DATA, cfg.get("password", ""), rete), host, port)
    _hook_aggiornamento(srv, win, args)
    for _ in range(120):
        if health(port):
            break
        time.sleep(0.5)
    hidden = "--minimizzato" in args
    if win is not None:
        try:
            win.tray = run_tray(port, srv, show=show_any, on_exit=win.quit, background=True)
        except Exception:
            log("icona di notifica non disponibile:\n" + traceback.format_exc())
        if win.run(hidden):
            stop_server(srv)
            return
        if win.tray is not None:
            # WebView2 mancante: finestra di Edge, l'icona c'è già e resta finché non si sceglie Esci.
            if not hidden or win.pending_show:
                open_window(port)
            while not srv.should_exit:
                time.sleep(1)
            stop_server(srv)
            return
    if win is None:
        listen_show_requests(lambda: open_window(port))
    else:
        win.mode = "edge"
    if not hidden:
        open_window(port)
    try:
        run_tray(port, srv)
    except Exception:
        log("icona di notifica non disponibile:\n" + traceback.format_exc())
        while not srv.should_exit:
            time.sleep(1)
    stop_server(srv)


if __name__ == "__main__":
    main()
