import logging
import math
import os
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

# 06/11/2026: YOLO11s al posto di YOLOv8n. Prova sulla clip del garage di notte (IR): YOLOv8n vedeva una
# "persona" (bici appesa) in 51 fotogrammi su 110 (fino a 0,50); YOLO11s in nessuno (max 0,13) e trova più
# persone vere nel demo (16 contro 13). È circa 3 volte più lento.
MODEL_NAME = "yolo11s"
MODEL_PATH = Path(__file__).parent / "models" / f"{MODEL_NAME}.pt"

COCO_IT = [
    "persona", "bicicletta", "auto", "moto", "aereo", "autobus", "treno", "camion", "barca", "semaforo",
    "idrante", "segnale di stop", "parchimetro", "panchina", "uccello", "gatto", "cane", "cavallo", "pecora", "mucca",
    "elefante", "orso", "zebra", "giraffa", "zaino", "ombrello", "borsa", "cravatta", "valigia", "frisbee",
    "sci", "snowboard", "pallone", "aquilone", "mazza da baseball", "guantone", "skateboard", "tavola da surf", "racchetta", "bottiglia",
    "calice", "tazza", "forchetta", "coltello", "cucchiaio", "ciotola", "banana", "mela", "panino", "arancia",
    "broccoli", "carota", "hot dog", "pizza", "ciambella", "torta", "sedia", "divano", "pianta", "letto",
    "tavolo", "wc", "tv", "portatile", "mouse", "telecomando", "tastiera", "cellulare", "microonde", "forno",
    "tostapane", "lavandino", "frigorifero", "libro", "orologio", "vaso", "forbici", "orsacchiotto", "asciugacapelli", "spazzolino",
]


def category_of(cls_id: int) -> str:
    if cls_id == 0:
        return "persona"
    if 1 <= cls_id <= 8:
        return "veicolo"
    if 14 <= cls_id <= 23:
        return "animale"
    return "oggetto"


DEFAULT_CLASSES = [0, 1, 2, 3, 5, 7, 14, 15, 16, 17, 24, 25, 26, 28, 36]

HEADINGS = [
    (0, "Destra", "→"), (45, "Basso-Destra", "↘"), (90, "Basso", "↓"), (135, "Basso-Sinistra", "↙"),
    (180, "Sinistra", "←"), (225, "Alto-Sinistra", "↖"), (270, "Alto", "↑"), (315, "Alto-Destra", "↗"),
]


def heading_of(dx: float, dy: float, min_mag: float = 0.012):
    if math.hypot(dx, dy) < min_mag:
        return "Fermo", "•", None
    ang = (math.degrees(math.atan2(dy, dx)) + 360) % 360
    idx = int(((ang + 22.5) % 360) // 45)
    _, name, arrow = HEADINGS[idx]
    return name, arrow, round(ang, 1)


ONNX_PATH = Path(os.environ.get("SENTINEL_MODEL_DIR", MODEL_PATH.parent)) / f"{MODEL_NAME}.onnx"
IMGSZ = 640                # larghezza d'ingresso del modello
# 06/11/2026 (1.0.5, CPU): modello esportato 640x448 invece di 640x640. Con le telecamere 3:2 e 16:9 un terzo
# del quadrato era solo bordo grigio: circa il 30% di calcolo in meno, stesso dettaglio. Un modello quadrato
# (vecchia cache) funziona ancora: in load() si prova e si ripiega.
IMG_H = 448


logger = logging.getLogger("detection")

# 08/11/2026 (1.0.14): OpenVINO, il motore di Intel, al posto di OpenCV DNN dove c'è. Misurato sul CT 111
# (i5-7600T + Intel HD 630), YOLO11s 640x448, una analisi:
#   OpenCV DNN (prima)          234 ms, 0,44 s di CPU
#   OpenVINO processore         123 ms, 0,22 s di CPU
#   OpenVINO scheda video f32    68 ms, 0,07 s di CPU   (punteggi identici a OpenCV)
# Sulla scheda video si resta in f32: in f16 sarebbe 38 ms ma i punteggi cambiano fino a 0,04, e cambierebbe
# cosa supera le soglie. Su Windows (1.0.15) lo stesso: scheda video Intel se c'è (le NVIDIA/AMD OpenVINO non le
# usa), altrimenti processore. SENTINEL_AI_MOTORE: auto (scheda video, poi processore, poi OpenCV) | cpu | opencv.
AI_MOTORE = os.environ.get("SENTINEL_AI_MOTORE", "auto").strip().lower()


def _ai_threads() -> int:
    try:
        return max(1, int(os.environ.get("SENTINEL_AI_THREADS", "2")))
    except ValueError:
        return 2


def _opencv_net():
    net = cv2.dnn.readNetFromONNX(str(ONNX_PATH))
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    # 07/11/2026: misurato sul CT 111 (i5-7600T): 4 thread 0,87 s di CPU per analisi, 2 thread 0,67 (-23%),
    # 350 ms invece di 270: basta per seguire chi passa. Più thread = più tempo perso a coordinarli.
    cv2.setNumThreads(_ai_threads())
    return net


def _uscite_attese(h: int, w: int) -> int:
    """Quante caselle dà YOLO11 per un ingresso h x w (passi 8, 16, 32)."""
    return sum((h // s) * (w // s) for s in (8, 16, 32))


class _OpenVinoNet:
    """Stessa interfaccia di cv2.dnn (setInput/forward). Se la scheda video si guasta mentre gira si passa a
    OpenCV per sempre (fino al riavvio): meglio lenti che ciechi."""

    def __init__(self, request, device, detector=None):
        self.request, self.device, self.blob, self.riserva = request, device, None, None
        self.detector, self.avvisato = detector, False

    def setInput(self, blob):
        self.blob = blob

    def forward(self):
        if self.riserva is None:
            try:
                self.request.infer({0: self.blob})
                return self.request.get_output_tensor(0).data.copy()
            except Exception as exc:  # noqa: BLE001 - qualsiasi errore del motore: si ripiega
                if not self.avvisato:   # un errore solo nel registro, anche se il ripiego non parte
                    logger.error("IA: OpenVINO %s non risponde (%s): passo a OpenCV", self.device, exc)
                    self.avvisato = True
                self.riserva = _opencv_net()
                if self.detector is not None:     # le Impostazioni mostrano il motore vero
                    self.detector.engine = "OpenCV DNN (ripiego)"
        self.riserva.setInput(self.blob)
        return self.riserva.forward()


class Detector:
    """YOLO11s. Con models/yolo11s.onnx gira con OpenCV DNN (versione Windows: niente PyTorch);
    altrimenti con Ultralytics come nel progetto originale (versione Docker)."""

    def __init__(self):
        self.model = None
        self.kind = None
        self.lock = threading.Lock()
        self.engine = ""

    def _load_openvino(self) -> bool:
        """Prova OpenVINO: scheda video (GPU), poi processore. False = resta OpenCV DNN."""
        global IMG_H
        if AI_MOTORE == "opencv":
            return False
        try:
            import openvino as ov
        except Exception:  # noqa: BLE001 - non installato (Windows) o libreria rotta
            return False
        try:
            core = ov.Core()
            cache = os.environ.get("SENTINEL_DATI") or os.environ.get("DATA_DIR")   # Linux / Windows
            if cache:   # il modello compilato per la scheda video si tiene: riavvio in 1-2 s invece di 8
                try:
                    core.set_property({"CACHE_DIR": str(Path(cache) / "cache-openvino")})
                except Exception:  # noqa: BLE001
                    pass
            devices = core.available_devices
        except Exception as exc:  # noqa: BLE001
            logger.warning("IA: OpenVINO non parte (%s): uso OpenCV", exc)
            return False
        order = ["CPU"] if AI_MOTORE == "cpu" else ["GPU", "CPU"]
        for dev in order:
            # con più schede video OpenVINO le chiama GPU.0, GPU.1 (es. Intel + NVIDIA su Windows): "GPU" = la prima
            if not any(d == dev or d.startswith(dev + ".") for d in devices):
                continue
            for h in dict.fromkeys((IMG_H, IMGSZ)):     # 640x448, poi modello quadrato (vecchia cache)
                try:
                    model = core.read_model(str(ONNX_PATH))
                    model.reshape([1, 3, h, IMGSZ])
                    cfg = {"PERFORMANCE_HINT": "LATENCY"}
                    if dev == "GPU":
                        cfg["INFERENCE_PRECISION_HINT"] = "f32"
                    else:
                        cfg["INFERENCE_NUM_THREADS"] = _ai_threads()
                    request = core.compile_model(model, dev, cfg).create_infer_request()
                    request.infer({0: np.zeros((1, 3, h, IMGSZ), dtype=np.float32)})
                    shape = tuple(request.get_output_tensor(0).data.shape)
                    if shape != (1, 84, _uscite_attese(h, IMGSZ)):
                        raise ValueError(f"uscita {shape}")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("IA: OpenVINO %s %dx%d non va (%s)", dev, IMGSZ, h, exc)
                    continue
                IMG_H = h
                self.model, self.kind = _OpenVinoNet(request, dev, self), "onnx"
                name = dev
                if dev == "GPU":
                    try:
                        name = f"GPU ({core.get_property('GPU', 'FULL_DEVICE_NAME')})"
                    except Exception:  # noqa: BLE001
                        pass
                self.engine = f"OpenVINO {name}"
                return True
        return False

    def load(self):
        if ONNX_PATH.exists():
            if self._load_openvino():
                return
            net = _opencv_net()
            self.model, self.kind, self.engine = net, "onnx", "OpenCV DNN"
            global IMG_H
            try:
                self._detect_onnx(np.zeros((360, 640, 3), dtype=np.uint8), 0.5, 0.5, None)
            except cv2.error:
                IMG_H = IMGSZ          # modello quadrato
                self._detect_onnx(np.zeros((360, 640, 3), dtype=np.uint8), 0.5, 0.5, None)
            return
        from ultralytics import YOLO
        MODEL_PATH.parent.mkdir(exist_ok=True)
        self.model = YOLO(str(MODEL_PATH) if MODEL_PATH.exists() else f"{MODEL_NAME}.pt")
        self.kind = self.engine = "ultralytics"
        if not MODEL_PATH.exists() and Path(f"{MODEL_NAME}.pt").exists():
            Path(f"{MODEL_NAME}.pt").rename(MODEL_PATH)
        self.model.predict(np.zeros((320, 320, 3), dtype=np.uint8), verbose=False)

    def _detect_onnx(self, frame, conf, iou, classes):
        h, w = frame.shape[:2]
        r = min(IMGSZ / w, IMG_H / h)
        nw, nh = int(round(w * r)), int(round(h * r))
        px, py = (IMGSZ - nw) // 2, (IMG_H - nh) // 2
        canvas = np.full((IMG_H, IMGSZ, 3), 114, dtype=np.uint8)
        canvas[py:py + nh, px:px + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (IMGSZ, IMG_H), swapRB=True, crop=False)
        with self.lock:
            self.model.setInput(blob)
            pred = self.model.forward()
        pred = np.squeeze(pred, 0).T                    # (N, 84): cx, cy, w, h, 80 punteggi
        scores = pred[:, 4:]
        cls = scores.argmax(1)
        best = scores[np.arange(len(cls)), cls]
        keep = best >= conf
        if classes:
            keep &= np.isin(cls, np.array(classes))
        if not keep.any():
            return []
        p, cls, best = pred[keep], cls[keep], best[keep]
        x1 = (p[:, 0] - p[:, 2] / 2 - px) / r
        y1 = (p[:, 1] - p[:, 3] / 2 - py) / r
        bw, bh = p[:, 2] / r, p[:, 3] / r
        boxes = np.stack([x1, y1, bw, bh], 1)
        # NMS per classe, come fa Ultralytics (agnostic=False).
        idx = cv2.dnn.NMSBoxesBatched(boxes.tolist(), best.tolist(), cls.tolist(), conf, iou)
        out = []
        for i in np.array(idx).flatten():
            bx, by, bw_, bh_ = boxes[i]
            a, b = max(0.0, bx / w), max(0.0, by / h)
            c, d = min(1.0, (bx + bw_) / w), min(1.0, (by + bh_) / h)
            if c > a and d > b:
                out.append((int(cls[i]), float(best[i]), (a, b, c, d)))
        return out

    def detect(self, frame, conf, iou, classes):
        if self.kind == "onnx":
            return self._detect_onnx(frame, conf, iou, classes)
        h, w = frame.shape[:2]
        with self.lock:
            res = self.model.predict(frame, conf=conf, iou=iou, classes=classes or None, imgsz=640, verbose=False)[0]
        out = []
        for b in res.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            out.append((int(b.cls[0]), float(b.conf[0]), (x1 / w, y1 / h, x2 / w, y2 / h)))
        return out


detector = Detector()


def line_side(line, px, py):
    v = (line["x2"] - line["x1"]) * (py - line["y1"]) - (line["y2"] - line["y1"]) * (px - line["x1"])
    return 1 if v > 0 else (-1 if v < 0 else 0)


def within_segment(line, px, py, margin=0.08):
    lx, ly = line["x2"] - line["x1"], line["y2"] - line["y1"]
    l2 = lx * lx + ly * ly or 1e-9
    t = ((px - line["x1"]) * lx + (py - line["y1"]) * ly) / l2
    return -margin <= t <= 1 + margin


def encode_jpeg(img, width=480, quality=75):
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


def annotated_snapshot(frame, box, label):
    img = frame.copy()
    h, w = img.shape[:2]
    x1, y1, x2, y2 = int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)
    cv2.rectangle(img, (x1, y1), (x2, y2), (129, 185, 16), 2)
    cv2.putText(img, label, (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (129, 185, 16), 2)
    return encode_jpeg(img, 640)


STATIC_MOVE_MIN = 0.03     # spostamento (mediana) oltre cui un oggetto "si è mosso": almeno questo...
STATIC_MOVE_REL = 0.15     # ...o il 15% della diagonale del riquadro (un'auto vicina trema di più di una persona lontana)
MOVE_CONFIRM = 3           # analisi di fila oltre la soglia per dire "si è mosso" (un riquadro storto non basta)
SURE_CONF = 0.6            # riconosciuto "con sicurezza" (mai cosa ferma)...
SURE_HITS = 3              # ...se succede in almeno 3 analisi (un riquadro storto al 60% non basta)
INHERIT_SECONDS = 10       # una traccia persa da meno di così e ricomparsa lì vicino passa la sua storia alla nuova


def box_iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def area_ratio(a, b) -> float:
    aa, bb = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    return aa / bb if bb > 0 else 0.0


def same_spot(spot_box, box) -> bool:
    """Stesso punto fisso: riquadro sovrapposto e di grandezza simile."""
    return box_iou(spot_box, box) >= 0.6 and 0.6 <= area_ratio(box, spot_box) <= 1.67


def _median(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _median_point(points):
    return _median([p[0] for p in points]), _median([p[1] for p in points])


class Track:
    def __init__(self, tid, cls, conf, box, cx, cy, now):
        self.id, self.cls, self.conf, self.box = tid, cls, conf, box
        self.first = (cx, cy)
        self.born = now
        self.first_points = [(cx, cy)]   # primi 5 punti: la loro mediana è il punto di partenza "stabile"
        self.move_run = 0
        self.moved = False        # si è mosso davvero almeno una volta (mai più "cosa ferma")
        self.max_conf = conf
        self.sure_hits = int(conf >= SURE_CONF)
        self.fixed = False        # "cosa ferma" (es. bici appesa scambiata per persona): niente eventi
        self.vel = (0.0, 0.0)     # velocità stimata (inquadrature/s) per prevedere dove sarà
        self.history = deque([(cx, cy)], maxlen=20)
        self.last_seen = now
        self.misses = 0           # analisi di fila in cui non è stata vista
        self.hits = 1
        self.side = None
        self.snap = None
        self.snap_conf = 0.0
        self.crossed = False
        self.inherited_crossed = False

    def inherit(self, old):
        """Stessa cosa ripresa dopo una breve perdita: la nuova traccia ne eredita la storia di movimento e lo
        stato della linea (2° giro agente 104: senza, chi passava la linea e veniva coperto un attimo era contato
        due volte). Lo spostamento per transiti e bilancio della linea riparte dall'ultimo punto visto."""
        self.first = old.history[-1]
        self.born, self.first_points = old.born, list(old.first_points)
        for k in ("side", "armed", "last_cross", "pending"):
            if hasattr(old, k):
                setattr(self, k, getattr(old, k))
        # Il "già passato la linea" ereditato serve solo a non ricontare il bilancio di fine traccia; il transito
        # resta della traccia nuova (3° giro agente 104: una persona diversa uscita dalla stessa porta perdeva
        # il suo transito).
        self.inherited_crossed = old.crossed or getattr(old, "inherited_crossed", False)
        self.moved, self.max_conf = old.moved, max(self.max_conf, old.max_conf)
        self.sure_hits += old.sure_hits
        self.fixed = old.fixed and not self.moved and self.sure_hits < SURE_HITS

    def update_motion(self, cx, cy):
        if len(self.first_points) < 5:
            self.first_points.append((cx, cy))
        start = _median_point(self.first_points)
        now_pos = _median_point(list(self.history)[-5:])
        b = self.box
        thr = max(STATIC_MOVE_MIN, STATIC_MOVE_REL * math.hypot(b[2] - b[0], b[3] - b[1]))
        if math.hypot(now_pos[0] - start[0], now_pos[1] - start[1]) >= thr:
            self.move_run += 1
            if self.move_run >= MOVE_CONFIRM:
                self.moved = True
        else:
            self.move_run = 0


class Tracker:
    MAX_GATE = 0.35       # frazione dell'inquadratura
    GATE_SPEED = 0.5      # inquadrature al secondo: più veloce di una persona che attraversa tutta l'immagine in 2 s
    MAX_SPEED = 1.5       # oltre questa velocità stimata è un errore di associazione, non un movimento
    MISS_MAX = 3

    def __init__(self, max_dist=0.12, ttl=1.5):
        self.tracks: dict[int, Track] = {}
        self.next_id = 1
        self.max_dist = max_dist
        self.ttl = ttl
        self.frame_dt = None      # intervallo medio fra due analisi
        self.last_update = None
        self.gone: list[Track] = []   # tracce scadute da poco (per l'eredità)
        self.spots: list[dict] = []   # punti fissi della sessione (li aggiorna session.update_fixed)

    def update(self, dets, now):
        if self.last_update is not None:
            dt = now - self.last_update
            if 0 < dt < 1.0:   # le pause del risparmio CPU (scena ferma) non contano come ritmo di analisi
                self.frame_dt = dt if self.frame_dt is None else 0.8 * self.frame_dt + 0.2 * dt
        self.last_update = now
        fdt = self.frame_dt or 0.2
        pairs = []
        cents = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, _, b in dets]
        for ti, tr in self.tracks.items():
            lx, ly = tr.history[-1]
            dt = now - tr.last_seen
            # 06/11/2026 (agente di prova 104): previsione a velocità costante, così due persone che si incrociano
            # con 2 analisi al secondo non si scambiano la traccia.
            pdt = min(dt, 1.0)
            px, py = lx + tr.vel[0] * pdt, ly + tr.vel[1] * pdt
            # Con YOLO11s le analisi sono 2-3 al secondo: tra una e l'altra ci si sposta di più. Il limite cresce
            # col tempo, ma al massimo di 2 intervalli di analisi (non 1,5 s: a 10 analisi/s un oggetto nuovo
            # comparso lontano poco dopo non deve prendersi la traccia di uno sparito).
            # Con una storia (>= 5 rilevamenti) si conosce la velocità: chi va piano non può "saltare" lontano su un
            # oggetto nuovo dopo un'analisi mancata (agente di prova 105: una persona lenta si prendeva la traccia di
            # una appena comparsa a 0,36 di distanza, che perdeva il suo allarme d'ingresso).
            rate = self.GATE_SPEED if tr.hits < 5 else min(self.GATE_SPEED, 2 * math.hypot(*tr.vel) + 0.15)
            gate = min(self.MAX_GATE, self.max_dist + max(0.0, min(dt, 2 * fdt) - 0.2) * rate)
            for di, (c, dconf, dbox) in enumerate(dets):
                if c != tr.cls:
                    continue
                # distanza minore fra posizione prevista e ultima: la velocità stimata dal tremolio di chi sta
                # fermo non deve portare fuori la previsione (2° giro agente 104)
                d = min(math.hypot(cents[di][0] - px, cents[di][1] - py), math.hypot(cents[di][0] - lx, cents[di][1] - ly))
                if d < gate:
                    # Una "cosa ferma" cede il rilevamento a chi si muove se il rilevamento è sicuro (persona davanti
                    # alla bici appesa) o non è nel suo punto; un rilevamento poco sicuro nel suo punto resta suo
                    # (2° giro agente 104: chi passava davanti, coperto per 2 analisi, si prendeva la bici).
                    yields = tr.fixed and (dconf >= SURE_CONF or not same_spot(tr.box, dbox))
                    pairs.append((yields, d, ti, di))
        pairs.sort()
        used_t, used_d, active = set(), set(), []
        for _, _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            tr = self.tracks[ti]
            c, conf, box = dets[di]
            dt = now - tr.last_seen
            if dt > 0:
                lx, ly = tr.history[-1]
                vx, vy = (cents[di][0] - lx) / dt, (cents[di][1] - ly) / dt
                sp = math.hypot(vx, vy)
                if sp > self.MAX_SPEED:
                    vx, vy = vx * self.MAX_SPEED / sp, vy * self.MAX_SPEED / sp
                tr.vel = (vx, vy) if tr.hits == 1 else (0.5 * tr.vel[0] + 0.5 * vx, 0.5 * tr.vel[1] + 0.5 * vy)
            tr.conf, tr.box, tr.last_seen, tr.misses = conf, box, now, 0
            tr.max_conf = max(tr.max_conf, conf)
            tr.sure_hits += conf >= SURE_CONF
            tr.history.append(cents[di])
            tr.update_motion(*cents[di])
            tr.hits += 1
            active.append(tr)
        self.gone = [g for g in self.gone if now - g.last_seen <= INHERIT_SECONDS]
        for di, (c, conf, box) in enumerate(dets):
            if di in used_d:
                continue
            tr = Track(self.next_id, c, conf, box, *cents[di], now)
            diag = math.hypot(box[2] - box[0], box[3] - box[1])
            near = [(math.hypot(g.history[-1][0] - cents[di][0], g.history[-1][1] - cents[di][1]), g)
                    for g in self.gone if g.cls == c]
            # solo con riquadro di grandezza simile, e mai se il rilevamento è su un punto fisso (2° giro agente 104:
            # la bici ferma ereditava la storia della persona che le era stata davanti e tornava a dare allarmi)
            near = [(d, g) for d, g in near if d < max(0.08, 0.5 * diag) and 0.6 <= area_ratio(box, g.box) <= 1.67]
            if near and any(sp["cls"] == c and same_spot(sp["box"], box) for sp in self.spots):
                near = []
            if near:
                old = min(near, key=lambda x: x[0])[1]
                tr.inherit(old)
                self.gone.remove(old)
            self.tracks[self.next_id] = tr
            self.next_id += 1
            active.append(tr)
        for t in self.tracks.values():
            if t.last_seen != now:
                t.misses += 1
        # Scade se non vista da ttl secondi E in almeno MISS_MAX analisi: col risparmio CPU (un'analisi ogni 3 s a
        # scena ferma) un'auto parcheggiata o una persona in sosta non vengono "perse" e ricreate a ogni controllo.
        expired = [t for t in self.tracks.values() if now - t.last_seen > self.ttl and t.misses >= self.MISS_MAX]
        for t in expired:
            del self.tracks[t.id]
        self.gone += expired
        return active, expired
