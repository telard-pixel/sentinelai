import math
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = Path(__file__).parent / "models" / "yolov8n.pt"

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


class Detector:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()

    def load(self):
        from ultralytics import YOLO
        MODEL_PATH.parent.mkdir(exist_ok=True)
        self.model = YOLO(str(MODEL_PATH) if MODEL_PATH.exists() else "yolov8n.pt")
        if not MODEL_PATH.exists() and Path("yolov8n.pt").exists():
            Path("yolov8n.pt").rename(MODEL_PATH)
        self.model.predict(np.zeros((320, 320, 3), dtype=np.uint8), verbose=False)

    def detect(self, frame, conf, iou, classes):
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


class Track:
    def __init__(self, tid, cls, conf, box, cx, cy, now):
        self.id, self.cls, self.conf, self.box = tid, cls, conf, box
        self.first = (cx, cy)
        self.history = deque([(cx, cy)], maxlen=20)
        self.last_seen = now
        self.hits = 1
        self.side = None
        self.snap = None
        self.snap_conf = 0.0
        self.crossed = False


class Tracker:
    def __init__(self, max_dist=0.12, ttl=1.5):
        self.tracks: dict[int, Track] = {}
        self.next_id = 1
        self.max_dist = max_dist
        self.ttl = ttl

    def update(self, dets, now):
        pairs = []
        cents = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, _, b in dets]
        for ti, tr in self.tracks.items():
            lx, ly = tr.history[-1]
            for di, (c, _, _) in enumerate(dets):
                if c != tr.cls:
                    continue
                d = math.hypot(cents[di][0] - lx, cents[di][1] - ly)
                if d < self.max_dist:
                    pairs.append((d, ti, di))
        pairs.sort()
        used_t, used_d, active = set(), set(), []
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            tr = self.tracks[ti]
            c, conf, box = dets[di]
            tr.conf, tr.box, tr.last_seen = conf, box, now
            tr.history.append(cents[di])
            tr.hits += 1
            active.append(tr)
        for di, (c, conf, box) in enumerate(dets):
            if di in used_d:
                continue
            tr = Track(self.next_id, c, conf, box, *cents[di], now)
            self.tracks[self.next_id] = tr
            self.next_id += 1
            active.append(tr)
        expired = [t for t in self.tracks.values() if now - t.last_seen > self.ttl]
        for t in expired:
            del self.tracks[t.id]
        return active, expired
