#!/usr/bin/env python3
import os

# Ścieżki dyskowe
RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", os.path.expanduser("~/recordings"))
MODELS_DIR = os.getenv("MODELS_DIR", os.path.expanduser("~/models"))

MODEL_PROTO = os.path.join(MODELS_DIR, "MobileNetSSD_deploy.prototxt")
MODEL_WEIGHTS = os.path.join(MODELS_DIR, "MobileNetSSD_deploy.caffemodel")

# Profil kalibracji NoIR (usuwa różowe/fioletowe zabarwienie sensora bez filtra IR)
NOIR_TUNING_FILE = "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json"

# Parametry sensora kamery (1280x960 4:3 - natywny aspekt sensora, optymalny dla GPU VideoCore)
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 960
CAMERA_FPS = 15
CAMERA_QUALITY = 65

# Parametry sieciowe serwera HTTP
HTTP_PORT = 8000
HTTP_HOST = "0.0.0.0"

# Parametry klasyfikacji obiektów AI (MobileNet-SSD)
AI_CONFIDENCE_THRESHOLD = 0.45
AI_SAMPLE_INTERVAL = 1.8  # sekundy między analizowanymi klatkami

# Limity nagrań wideo
MAX_CLIP_DURATION = 120.0     # maksymalny czas jednego klipu: 2 minuty (120 s)
POST_MOTION_DURATION = 15.0   # czas dogrywania po ustaniu ruchu (15 s)

# Klasy modelu Pascal VOC
VOC_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair", "cow",
    "diningtable", "dog", "horse", "motorbike", "person",
    "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]
