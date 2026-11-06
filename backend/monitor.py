"""Monitoraggio continuo delle telecamere RTSP/NVR (05/11/2026, richiesta di Roberto: "il flusso deve essere
sempre attivo anche se cambio e vado in impostazioni").

Prima il flusso viveva dentro la connessione della finestra: chiusa o persa quella, si fermava tutto.
Ora ogni telecamera di rete ha un CameraWorker nel server: legge il video, riconosce, salva eventi e clip,
si ricollega da solo se la telecamera si interrompe. Le finestre aperte si limitano a guardare."""
import asyncio
import base64
import logging
import re
import time
from datetime import datetime
from typing import Optional

import cv2

from models import Camera, stream_url
from session import LatestFrame, StreamSession, open_capture
from detection import encode_jpeg

logger = logging.getLogger("monitor")

FIRST_FRAME_TIMEOUT = 40     # alcune telecamere impiegano più di 10 s a mandare il primo fotogramma
FRAME_TIMEOUT = 20
MIN_LOOP_SECONDS = 0.1       # al massimo ~10 analisi al secondo per telecamera: basta per seguire chi passa
IDLE_LOOP_SECONDS = 0.2      # scena ferma (niente AI): 5 controlli del movimento al secondo bastano
BACKOFF = (3, 5, 10, 20, 30, 60)


def safe_url(url: str) -> str:
    from models import mask_url_password
    return mask_url_password(url)


from session import local_tz_offset  # noqa: E402,F401  (spostata in session.py)


async def open_cancellable(url):
    """Apre il flusso in un thread. Se nel frattempo arriva Ferma, la connessione aperta in ritardo viene
    chiusa appena pronta (06/11/2026, agente di prova: restava aperta per sempre)."""
    fut = asyncio.ensure_future(asyncio.to_thread(open_capture, url))
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        def release(f):
            if not f.cancelled() and f.exception() is None:
                f.result().release()
        fut.add_done_callback(release)
        raise


class CameraWorker:
    def __init__(self, db, camera: Camera, settings):
        self.db, self.camera, self.settings = db, camera, settings
        self.session = StreamSession(db, camera, settings, None)   # None = ora locale, segue l'ora legale
        self.stopping = False
        self.viewers: set[asyncio.Queue] = set()
        self.status = {"state": "connecting", "message": "Connessione alla telecamera…"}
        self.last: Optional[dict] = None
        self.restart = asyncio.Event()
        self.task = asyncio.create_task(self.run(), name=f"camera-{camera.id}")

    # --- finestre che guardano
    def attach(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=3)
        self.viewers.add(q)
        return q

    def detach(self, q):
        self.viewers.discard(q)

    def broadcast(self, msg: dict):
        for q in list(self.viewers):
            if q.full():
                try:
                    q.get_nowait()          # chi è lento perde un fotogramma, non rallenta l'analisi
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)

    def set_status(self, state, message=""):
        self.status = {"state": state, "message": message}
        if state == "live":
            self.broadcast({"type": "ready"})
        elif state in ("error", "connecting"):
            self.broadcast({"type": "error", "message": message})

    # --- impostazioni cambiate
    def reload(self, camera: Camera, settings):
        url_changed = stream_url(camera) != stream_url(self.camera)
        self.camera, self.settings = camera, settings
        self.session.update(camera, settings)
        if url_changed:
            self.restart.set()

    async def stop(self):
        self.stopping = True
        self.task.cancel()
        try:
            await self.task
        except (asyncio.CancelledError, Exception):
            pass
        await asyncio.shield(self.session.close())
        # Tutte le finestre aperte su questa telecamera lo sanno subito (non solo quella che ha premuto Ferma).
        self.broadcast({"type": "stopped"})

    # --- ciclo principale
    async def run(self):
        attempt = 0
        while True:
            url = stream_url(self.camera)
            name = self.camera.name
            if not url:
                self.set_status("error", "Telecamera disattivata: manca l'indirizzo.")
                await self._wait(30)
                continue
            self.set_status("connecting", f"Connessione a {name}…" if not attempt else f"Ricollegamento a {name} (tentativo {attempt + 1})…")
            logger.info("[%s] apro %s", name, safe_url(url))
            cap = await open_cancellable(url)
            if not cap.isOpened():
                await asyncio.to_thread(cap.release)
                delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
                logger.warning("[%s] impossibile aprire il flusso, riprovo tra %d s", name, delay)
                self.set_status("error", f"Impossibile aprire il flusso: controlla indirizzo, utente e password. Riprovo tra {delay} s.")
                attempt += 1
                await self._wait(delay)
                continue
            fourcc = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
            codec = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)).strip("\x00") or "?"
            logger.info("[%s] collegato: %dx%d, %.1f fps dichiarati, codec %s", name, cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                        cap.get(cv2.CAP_PROP_FRAME_HEIGHT), cap.get(cv2.CAP_PROP_FPS) or 0, codec)
            reader = LatestFrame(cap)
            frames, seq, started = 0, 0, time.monotonic()
            reason = ""
            try:
                while not self.restart.is_set():
                    t0 = time.monotonic()
                    # Attesa a pezzi da 1 s: se intanto cambia l'indirizzo si riparte subito, non dopo 40 s.
                    limit = FIRST_FRAME_TIMEOUT if not frames else FRAME_TIMEOUT
                    waited, frame = 0.0, None
                    while waited < limit and not self.restart.is_set():
                        frame, seq = await asyncio.to_thread(reader.wait, seq, 1.0)
                        if frame is not None or not reader.ok:
                            break
                        waited += 1.0
                    if self.restart.is_set():
                        break
                    if frame is None:
                        reason = ("nessun fotogramma nei primi %d s" % FIRST_FRAME_TIMEOUT if not frames
                                  else "nessun fotogramma da %d s" % FRAME_TIMEOUT) if reader.ok else "la telecamera ha chiuso il flusso"
                        break
                    if not frames:
                        logger.info("[%s] primo fotogramma dopo %.1f s (%dx%d)", name, time.monotonic() - started, frame.shape[1], frame.shape[0])
                        self.set_status("live")
                        attempt = 0
                    frames += 1
                    result = await self.session.process(frame)
                    self.last = result
                    if self.viewers:
                        img = await asyncio.to_thread(encode_jpeg, frame, 960, 70)
                        h, w = frame.shape[:2]
                        self.broadcast({"type": "frame", "image": base64.b64encode(img).decode(), "width": w, "height": h, **result})
                    rest = (IDLE_LOOP_SECONDS if result.get("idle") else MIN_LOOP_SECONDS) - (time.monotonic() - t0)
                    if rest > 0:
                        await asyncio.sleep(rest)
            except asyncio.CancelledError:
                reader.stop()
                raise
            except Exception as exc:
                reason = f"errore: {exc}"
                logger.exception("[%s] errore nell'analisi", name)
            finally:
                reader.stop()
            if self.restart.is_set():
                self.restart.clear()
                logger.info("[%s] indirizzo cambiato: riparto", name)
                attempt = 0
                continue
            delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            logger.warning("[%s] flusso interrotto (%s) dopo %d fotogrammi: riprovo tra %d s", name, reason, frames, delay)
            self.set_status("error", f"Flusso interrotto ({reason}). Riprovo tra {delay} s…")
            attempt += 1
            await self._wait(delay)

    async def _wait(self, seconds):
        try:
            await asyncio.wait_for(self.restart.wait(), seconds)
            self.restart.clear()
        except asyncio.TimeoutError:
            pass


class Manager:
    def __init__(self, db):
        self.db = db
        self.workers: dict[str, CameraWorker] = {}

    def get(self, camera_id) -> Optional[CameraWorker]:
        return self.workers.get(camera_id)

    def ensure(self, camera: Camera, settings) -> CameraWorker:
        w = self.workers.get(camera.id)
        if w is None or w.task.done() or w.stopping:
            w = self.workers[camera.id] = CameraWorker(self.db, camera, settings)
            logger.info("[%s] monitoraggio avviato", camera.name)
        return w

    async def stop(self, camera_id):
        w = self.workers.pop(camera_id, None)   # tolto dalla tabella PRIMA di qualunque await
        if w:
            w.stopping = True
            await w.stop()
            logger.info("[%s] monitoraggio fermato", w.camera.name)

    def reload_camera(self, camera: Camera, settings):
        w = self.workers.get(camera.id)
        if w:
            w.reload(camera, settings)

    def reload_settings(self, settings):
        for w in self.workers.values():
            w.reload(w.camera, settings)

    async def shutdown(self):
        for cid in list(self.workers):
            await self.stop(cid)
