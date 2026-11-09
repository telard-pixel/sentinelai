"""Monitor risorse in tempo reale (1.0.19, richiesta di Roberto: "un monitor risorse in real time sarebbe comodo").

Ogni PASSO secondi si prende un campione: processore e memoria del programma e del sistema, lavoro dell'IA
(analisi al secondo, durata media, quanto è occupato il motore) e, per ogni telecamera sorvegliata dal server,
fotogrammi ricevuti e analizzati. Si tengono gli ultimi STORIA campioni (2 minuti) per i grafici.
Niente librerie in più: /proc su Linux, funzioni di sistema (ctypes) su Windows; altrove i valori mancano (None).
"""
import asyncio
import logging
import os
import sys
import time
from collections import deque

from temperatura import leggi_processore, termico

logger = logging.getLogger("risorse")

PASSO = 2.0
STORIA = 60


# ------------------------------------------------------------------ sistema
def _cpu_sistema():
    """(occupato, totale) in unità qualsiasi, cumulativi dall'avvio; None se non si sa."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/stat") as f:
                v = [int(x) for x in f.readline().split()[1:]]
            idle = v[3] + (v[4] if len(v) > 4 else 0)       # idle + iowait
            tot = sum(v[:8])                                 # senza guest (già dentro user)
            return tot - idle, tot
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            i, k, u = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u)):
                return None
            f = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime   # noqa: E731
            idle, tot = f(i), f(k) + f(u)                    # il tempo del kernel comprende già l'idle
            return tot - idle, tot
    except Exception:  # noqa: BLE001
        return None
    return None


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    class _MSX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _memoria_windows():
    """Agente di prova (1.0.19): argtypes/restype espliciti, altrimenti lo pseudo-handle a 64 bit non passa;
    processo e sistema in due prove separate (un errore sul primo non cancella il secondo)."""
    proc = usati = totale = None
    k32 = ctypes.windll.kernel32
    try:
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        gpmi = ctypes.windll.psapi.GetProcessMemoryInfo
        gpmi.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        gpmi.restype = wintypes.BOOL
        pmc = _PMC(); pmc.cb = ctypes.sizeof(_PMC)
        if gpmi(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            proc = pmc.WorkingSetSize / 1048576
    except Exception:  # noqa: BLE001
        pass
    try:
        k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MSX)]
        k32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        m = _MSX(); m.dwLength = ctypes.sizeof(_MSX)
        if k32.GlobalMemoryStatusEx(ctypes.byref(m)):
            totale = m.ullTotalPhys / 1048576
            usati = (m.ullTotalPhys - m.ullAvailPhys) / 1048576
    except Exception:  # noqa: BLE001
        pass
    return proc, usati, totale


def _memoria():
    """(MB usati dal programma, MB usati dal sistema, MB totali); i valori che non si sanno sono None."""
    proc = usati = totale = None
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/status") as f:
                for riga in f:
                    if riga.startswith("VmRSS:"):
                        proc = int(riga.split()[1]) / 1024
            info = {}
            with open("/proc/meminfo") as f:
                for riga in f:
                    k, v = riga.split(":", 1)
                    info[k] = int(v.split()[0])
            if "MemTotal" in info and "MemAvailable" in info:
                totale = info["MemTotal"] / 1024
                usati = (info["MemTotal"] - info["MemAvailable"]) / 1024
        elif os.name == "nt":
            proc, usati, totale = _memoria_windows()
    except Exception:  # noqa: BLE001
        pass
    return proc, usati, totale


def _core():
    try:
        return len(os.sched_getaffinity(0))    # Linux: i core davvero assegnati (CT/contenitore)
    except Exception:  # noqa: BLE001
        return os.cpu_count() or 1


def _r(x, n=1):
    return None if x is None else round(x, n)


# ------------------------------------------------------------------ misuratore
class Misuratore:
    def __init__(self):
        self.storia: deque = deque(maxlen=STORIA)
        self.ultimo: dict = {}
        self._prima = None
        self._seq: dict = {}       # camera_id -> (seq del lettore, istante)

    def campione(self, manager, detector) -> dict:
        # 1.0.21: prima di tutto la temperatura, in una prova a sé: un errore nel resto del campione non deve
        # congelare la regolazione (agente di prova)
        try:
            termico.aggiorna(leggi_processore())
        except Exception:  # noqa: BLE001
            logger.exception("lettura della temperatura non riuscita")
        ora, cpu_proc = time.monotonic(), time.process_time()
        sis = _cpu_sistema()
        n_ai, t_ai = getattr(detector, "n_analisi", 0), getattr(detector, "t_analisi", 0.0)
        out = {"ora": time.time(), "core": _core(), "motore": getattr(detector, "engine", None)}
        p = self._prima
        if p:
            dt = max(ora - p["ora"], 1e-6)
            out["cpu_programma"] = _r((cpu_proc - p["cpu"]) / dt * 100)            # % di UN core (può superare 100)
            if sis and p["sis"] and sis[1] > p["sis"][1]:
                out["cpu_sistema"] = _r((sis[0] - p["sis"][0]) / (sis[1] - p["sis"][1]) * 100)   # % di tutti i core
            dn, dtai = n_ai - p["n_ai"], t_ai - p["t_ai"]
            out["ia_al_secondo"] = _r(dn / dt)
            out["ia_ms"] = _r(dtai / dn * 1000, 0) if dn else None
            out["ia_occupata"] = _r(min(dtai / dt * 100, 100), 0)
        out["termico"] = termico.stato()
        out["temperatura"] = out["termico"]["temperatura"]
        mp, mu, mt = _memoria()
        out.update(mem_programma=_r(mp, 0), mem_sistema=_r(mu, 0), mem_totale=_r(mt, 0))
        tel = []
        for cid, w in list(getattr(manager, "workers", {}).items()):
            reader = getattr(w, "reader", None)
            ricevuti = None
            if reader is not None:
                prima = self._seq.get(cid)    # (lettore, seq, istante): lettore nuovo = si riparte da capo
                if prima and prima[0] == id(reader) and prima[1] <= reader.seq and ora > prima[2]:
                    ricevuti = _r((reader.seq - prima[1]) / (ora - prima[2]))
                self._seq[cid] = (id(reader), reader.seq, ora)
            else:
                self._seq.pop(cid, None)
            last = w.last or {}
            tel.append({"id": cid, "nome": w.camera.name, "stato": w.status.get("state"), "prova": bool(w.camera.prova),
                        "ricevuti": ricevuti, "elaborati": last.get("fps"), "analizzati": last.get("ai_fps"),
                        "spettatori": len(w.viewers)})
        for cid in [c for c in self._seq if c not in getattr(manager, "workers", {})]:
            self._seq.pop(cid, None)
        out["telecamere"] = tel
        self._prima = {"ora": ora, "cpu": cpu_proc, "sis": sis, "n_ai": n_ai, "t_ai": t_ai}
        self.ultimo = out
        if p:
            self.storia.append({k: out.get(k) for k in ("ora", "cpu_programma", "cpu_sistema", "mem_programma",
                                                        "ia_al_secondo", "ia_occupata", "temperatura")})
        return out

    def stato(self) -> dict:
        # 1.0.21 (agente di prova): impostazioni della temperatura lette ADESSO, non quelle del campione di 2 s fa
        # (altrimenti un limite appena salvato tornava per un attimo al valore vecchio e si poteva perdere)
        ultimo = {**self.ultimo, "termico": termico.stato()} if self.ultimo else self.ultimo
        return {"passo": PASSO, "ultimo": ultimo, "storia": list(self.storia)}

    async def giro(self, manager, detector):
        ultimo_errore = None
        while True:
            try:
                self.campione(manager, detector)
                ultimo_errore = None
            except Exception as exc:  # noqa: BLE001 - il monitor non deve mai fermare il server
                if repr(exc) != ultimo_errore:     # scritto una volta, non ogni 2 s
                    logger.exception("campione risorse non riuscito")
                ultimo_errore = repr(exc)
            await asyncio.sleep(PASSO)


misuratore = Misuratore()
