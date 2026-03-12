import json
import logging
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import requests
from ultralytics import YOLO

logging.basicConfig(level=os.environ.get("DETECTOR_LOG_LEVEL", "INFO"))
logger = logging.getLogger("detector")

CAMERA_URL = os.environ.get("CAMERA_URL", "0")
CAMERA_NAME = os.environ.get("CAMERA_NAME", "Camara-1")
MODEL_PATH = os.environ.get("MODEL_PATH", "/app/models/best.pt")
PERSON_MODEL_PATH = os.environ.get("PERSON_MODEL_PATH", "yolov8n.pt")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://web:8000")
EVENT_THROTTLE_SECONDS = int(os.environ.get("EVENT_THROTTLE_SECONDS", "10"))
FRAME_SAVE_DIR = os.environ.get("FRAME_SAVE_DIR", "/app/media/evidence")
STREAM_FRAME_PATH = os.environ.get("STREAM_FRAME_PATH", "/app/media/stream/latest.jpg")
FRAME_WIDTH = int(os.environ.get("FRAME_WIDTH", "960"))
FRAME_HEIGHT = int(os.environ.get("FRAME_HEIGHT", "540"))
INFER_EVERY = int(os.environ.get("INFER_EVERY", "2"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "80"))
IMG_SIZE = int(os.environ.get("IMG_SIZE", "640"))
BOX_IOU_COOLDOWN = float(os.environ.get("BOX_IOU_COOLDOWN", "0.5"))
EVENT_COOLDOWN_SECONDS = int(os.environ.get("EVENT_COOLDOWN_SECONDS", "15"))
CAP_FPS = int(os.environ.get("CAP_FPS", "15"))
CAMERA_BACKEND = os.environ.get("CAMERA_BACKEND", "AUTO").upper()
WARMUP_FRAMES = int(os.environ.get("WARMUP_FRAMES", "5"))
PERSON_CONF = float(os.environ.get("PERSON_CONF", "0.35"))
HELMET_CONF = float(os.environ.get("HELMET_CONF", "0.35"))
IMG_SIZE_PERSON = int(os.environ.get("IMG_SIZE_PERSON", "320"))
IMG_SIZE_HELMET = int(os.environ.get("IMG_SIZE_HELMET", "512"))
ROI_IMG_SIZE = int(os.environ.get("ROI_IMG_SIZE", "640"))
MAX_PERSONS = int(os.environ.get("MAX_PERSONS", "3"))
HEAD_RATIO = float(os.environ.get("HEAD_RATIO", "0.35"))
ROI_PAD = float(os.environ.get("ROI_PAD", "0.15"))
MIN_HELMET_AREA_RATIO = float(os.environ.get("MIN_HELMET_AREA_RATIO", "0.08"))
MIN_HELMET_HEIGHT_RATIO = float(os.environ.get("MIN_HELMET_HEIGHT_RATIO", "0.20"))
MIN_HELMET_PERSON_RATIO = float(os.environ.get("MIN_HELMET_PERSON_RATIO", "0.02"))
USE_OPENVINO = os.environ.get("USE_OPENVINO", "0") == "1"
OPENVINO_DIR = os.environ.get("OPENVINO_DIR", "models_openvino")

cv2.setUseOptimized(True)
try:
    cv2.setNumThreads(1)
except Exception:
    pass

os.makedirs(FRAME_SAVE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STREAM_FRAME_PATH), exist_ok=True)


def load_model():
    if os.path.exists(MODEL_PATH):
        logger.info("Loading model from %s", MODEL_PATH)
        return YOLO(MODEL_PATH)
    logger.warning("Model %s not found. Falling back to yolov8n.pt", MODEL_PATH)
    return YOLO("yolov8n.pt")

MODEL = load_model()
NAMES = MODEL.names

HAS_PERSON = any(name == "person" for name in NAMES.values())
HAS_HELMET = any(name in ("helmet", "hardhat") for name in NAMES.values())
HAS_NO_HELMET = any(name in ("no-helmet", "no_helmet", "no helmet") for name in NAMES.values())

PERSON_MODEL = None
PERSON_NAMES = {}
if not HAS_PERSON:
    logger.info("Helmet model has no 'person' class. Loading person model: %s", PERSON_MODEL_PATH)
    PERSON_MODEL = YOLO(PERSON_MODEL_PATH)
    PERSON_NAMES = PERSON_MODEL.names

if USE_OPENVINO:
    try:
        # Export to OpenVINO on first run to accelerate Intel iGPU
        if os.path.isdir(OPENVINO_DIR):
            logger.info("Loading OpenVINO model from %s", OPENVINO_DIR)
            MODEL = YOLO(OPENVINO_DIR)
            NAMES = MODEL.names
        else:
            logger.info("Exporting to OpenVINO for Intel acceleration...")
            MODEL.export(format="openvino", imgsz=IMG_SIZE_HELMET, half=False)
            ov_path = f"{MODEL_PATH.split('.')[0]}_openvino_model"
            if os.path.isdir(ov_path):
                os.makedirs(OPENVINO_DIR, exist_ok=True)
                # keep the exported dir as OPENVINO_DIR
                MODEL = YOLO(ov_path)
                NAMES = MODEL.names
    except Exception as exc:
        logger.warning("OpenVINO not available, using default runtime: %s", exc)

if not (HAS_HELMET or HAS_NO_HELMET):
    logger.warning("Model does not include helmet/no-helmet classes. All persons will be flagged as no-helmet.")


def open_capture():
    if CAMERA_URL.isdigit():
        cam_index = int(CAMERA_URL)
        if os.name == "nt":
            backends = []
            if CAMERA_BACKEND in ("DSHOW", "AUTO"):
                backends.append(cv2.CAP_DSHOW)
            if CAMERA_BACKEND in ("MSMF", "AUTO"):
                backends.append(cv2.CAP_MSMF)

            for backend in backends:
                cap = cv2.VideoCapture(cam_index, backend)
                if cap.isOpened():
                    if FRAME_WIDTH > 0 and FRAME_HEIGHT > 0:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
                    return cap
            return cv2.VideoCapture(cam_index)
        cap = cv2.VideoCapture(cam_index)
        if FRAME_WIDTH > 0 and FRAME_HEIGHT > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        return cap
    return cv2.VideoCapture(CAMERA_URL)

class FrameGrabber:
    def __init__(self, cap):
        self.cap = cap
        self.lock = threading.Lock()
        self.frame = None
        self.ts = 0.0
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            with self.lock:
                self.frame = frame
                self.ts = time.time()

    def read(self):
        with self.lock:
            if self.frame is None:
                return None, 0.0
            return self.frame.copy(), self.ts

    def stop(self):
        self.running = False


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / float(area_a + area_b - inter + 1e-6)


def post_event(tipo_evento, confianza, bbox, image_path):
    url = f"{BACKEND_URL}/api/eventos/"
    data = {
        "camara": CAMERA_NAME,
        "tipo_evento": tipo_evento,
        "confianza": str(confianza),
        "bounding_box": json.dumps(bbox),
        "fecha": datetime.utcnow().isoformat() + "Z",
    }
    with open(image_path, "rb") as f:
        files = {"imagen": f}
        try:
            resp = requests.post(url, data=data, files=files, timeout=5)
            if resp.status_code >= 300:
                logger.error("Failed to send event: %s - %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.error("Error sending event: %s", exc)


def draw_box(frame, bbox, color, label, conf):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    text = f"{label} {conf:.2f}"
    cv2.putText(frame, text, (x1, max(y1 - 5, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def main():
    last_event_time = 0.0
    frame_idx = 0
    recent_events = []
    infer_lock = threading.Lock()
    infer_running = {"value": False}
    last_result = {"persons": [], "helmets": [], "no_helmets": []}
    last_frame_ts = time.time()
    freeze_timeout = int(os.environ.get("FREEZE_TIMEOUT", "5"))

    def run_inference(frame_bgr):
        with infer_lock:
            infer_running["value"] = True
        try:
            results = MODEL.predict(
                source=frame_bgr,
                verbose=False,
                conf=HELMET_CONF,
                imgsz=IMG_SIZE_HELMET,
                device="cpu",
            )
            result = results[0]

            persons_local = []
            helmets_local = []
            no_helmets_local = []

            if PERSON_MODEL is not None:
                presults = PERSON_MODEL.predict(
                    source=frame_bgr,
                    verbose=False,
                    conf=PERSON_CONF,
                    imgsz=IMG_SIZE_PERSON,
                    device="cpu",
                )
                presult = presults[0]
                for box in presult.boxes:
                    cls = int(box.cls[0])
                    label = PERSON_NAMES.get(cls, str(cls))
                    if label != "person":
                        continue
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    persons_local.append(([x1, y1, x2, y2], conf))
            else:
                # Use helmet model if it also has person class
                for box in result.boxes:
                    cls = int(box.cls[0])
                    label = NAMES.get(cls, str(cls))
                    if label != "person":
                        continue
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    persons_local.append(([x1, y1, x2, y2], conf))

            if HAS_NO_HELMET:
                for box in result.boxes:
                    cls = int(box.cls[0])
                    label = NAMES.get(cls, str(cls))
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    bbox = [x1, y1, x2, y2]
                    if label in ("no-helmet", "no_helmet", "no helmet"):
                        no_helmets_local.append((bbox, conf))

            if HAS_HELMET:
                for box in result.boxes:
                    cls = int(box.cls[0])
                    label = NAMES.get(cls, str(cls))
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    bbox = [x1, y1, x2, y2]
                    if label in ("helmet", "hardhat"):
                        helmets_local.append((bbox, conf))

            persons_info = []
            if HAS_HELMET:
                for bbox, pconf in persons_local[:MAX_PERSONS]:
                    x1, y1, x2, y2 = [int(v) for v in bbox]
                    h = max(y2 - y1, 1)
                    head_h = int(h * HEAD_RATIO)
                    head_y1 = y1
                    head_y2 = y1 + head_h
                    has_helmet = False
                    for hbbox, hconf in helmets_local:
                        hx1, hy1, hx2, hy2 = [int(v) for v in hbbox]
                        cx = (hx1 + hx2) // 2
                        cy = (hy1 + hy2) // 2
                        if x1 <= cx <= x2 and head_y1 <= cy <= head_y2:
                            hb_w = max(hx2 - hx1, 1)
                            hb_h = max(hy2 - hy1, 1)
                            person_area = max((x2 - x1) * (y2 - y1), 1)
                            area_ratio = (hb_w * hb_h) / person_area
                            height_ratio = hb_h / max(head_h, 1)
                            if area_ratio >= MIN_HELMET_PERSON_RATIO and height_ratio >= MIN_HELMET_HEIGHT_RATIO:
                                has_helmet = True
                                break
                    persons_info.append({"bbox": bbox, "conf": pconf, "has_helmet": has_helmet})
            else:
                for bbox, pconf in persons_local[:MAX_PERSONS]:
                    persons_info.append({"bbox": bbox, "conf": pconf, "has_helmet": False})

            last_result["persons"] = persons_info
            last_result["helmets"] = helmets_local
            last_result["no_helmets"] = no_helmets_local
        except Exception as exc:
            logger.error("Inference error: %s", exc)
        finally:
            with infer_lock:
                infer_running["value"] = False

    while True:
        cap = open_capture()
        if not cap.isOpened():
            logger.error("No se pudo abrir la camara. Reintentando en 5s...")
            time.sleep(5)
            continue

        logger.info("Camara conectada.")
        if CAP_FPS > 0:
            cap.set(cv2.CAP_PROP_FPS, CAP_FPS)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Warmup to avoid stale/black frames
        for _ in range(max(WARMUP_FRAMES, 0)):
            cap.read()

        grabber = FrameGrabber(cap)

        while cap.isOpened():
            frame, ts = grabber.read()
            if frame is None:
                time.sleep(0.01)
                continue
            last_frame_ts = ts

            frame_idx += 1
            if FRAME_WIDTH > 0 and FRAME_HEIGHT > 0:
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))

            if frame_idx % INFER_EVERY != 0:
                cv2.imwrite(STREAM_FRAME_PATH, frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                continue
            if not infer_running["value"]:
                threading.Thread(target=run_inference, args=(frame.copy(),), daemon=True).start()

            persons = last_result["persons"]
            no_helmets = last_result["no_helmets"]

            no_helmet_events = []

            if HAS_NO_HELMET:
                for bbox, conf in no_helmets:
                    draw_box(frame, bbox, (0, 0, 255), "no-helmet", conf)
                    no_helmet_events.append((bbox, conf))
            elif HAS_HELMET:
                for info in persons:
                    bbox = info["bbox"]
                    conf = info["conf"]
                    if info.get("has_helmet"):
                        draw_box(frame, bbox, (0, 255, 0), "helmet", conf)
                    else:
                        draw_box(frame, bbox, (0, 0, 255), "no-helmet", conf)
                        no_helmet_events.append((bbox, conf))
            else:
                for bbox, conf in persons:
                    draw_box(frame, bbox, (0, 0, 255), "no-helmet", conf)
                    no_helmet_events.append((bbox, conf))

            cv2.imwrite(STREAM_FRAME_PATH, frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])

            # Watchdog: si la camara se congela, reabrir
            if time.time() - last_frame_ts > freeze_timeout:
                logger.warning("Camara congelada. Reabriendo...")
                break

            now = time.time()
            if no_helmet_events and (now - last_event_time) >= EVENT_THROTTLE_SECONDS:
                bbox, conf = no_helmet_events[0]

                # Deduplicar por IoU y ventana temporal
                recent_events = [
                    (rb, ts) for rb, ts in recent_events if (now - ts) <= EVENT_COOLDOWN_SECONDS
                ]
                is_duplicate = any(iou(bbox, rb) >= BOX_IOU_COOLDOWN for rb, _ in recent_events)

                if not is_duplicate:
                    last_event_time = now
                    recent_events.append((bbox, now))
                    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    image_path = os.path.join(FRAME_SAVE_DIR, f"no_helmet_{ts}.jpg")
                    cv2.imwrite(image_path, frame)
                    post_event("no-helmet", conf, bbox, image_path)

        grabber.stop()
        cap.release()
        time.sleep(3)


if __name__ == "__main__":
    main()
