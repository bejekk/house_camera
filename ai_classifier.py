#!/usr/bin/env python3
import os
import threading
import cv2
import numpy as np
from config import MODEL_PROTO, MODEL_WEIGHTS, VOC_CLASSES, AI_CONFIDENCE_THRESHOLD

class AIClassifier:
    def __init__(self, proto_path=MODEL_PROTO, weights_path=MODEL_WEIGHTS):
        self.net = None
        self.available = False
        self.lock = threading.Lock()
        if os.path.exists(proto_path) and os.path.exists(weights_path):
            try:
                # 1 wątek na Cortex-A53 gwarantuje brak walki o zasoby z procesami kamery
                cv2.setNumThreads(1)
                self.net = cv2.dnn.readNetFromCaffe(proto_path, weights_path)
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self.available = True
                print("AIClassifier: MobileNet-SSD załadowany pomyślnie (1 wątek CPU).")
            except Exception as e:
                print(f"AIClassifier błąd ładowania: {e}")
        else:
            print(f"AIClassifier: Brak plików modelu ({proto_path}).")

    def detect_objects(self, frame_bytes, conf_threshold=AI_CONFIDENCE_THRESHOLD):
        if not self.available or not self.net or not frame_bytes:
            return set(), []
        try:
            nparr = np.frombuffer(frame_bytes, dtype=np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return set(), []

            blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 0.007843, (300, 300), 127.5)
            with self.lock:
                self.net.setInput(blob)
                detections = self.net.forward()

            found_labels = set()
            details = []
            for i in range(detections.shape[2]):
                confidence = float(detections[0, 0, i, 2])
                if confidence >= conf_threshold:
                    idx = int(detections[0, 0, i, 1])
                    if idx < len(VOC_CLASSES):
                        raw_label = VOC_CLASSES[idx]
                        if raw_label == "person":
                            found_labels.add("czlowiek")
                            details.append(("człowiek", confidence))
                        elif raw_label == "dog":
                            found_labels.add("pies")
                            details.append(("pies", confidence))
            return found_labels, details
        except Exception:
            return set(), []
