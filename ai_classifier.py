#!/usr/bin/env python3
import os
import threading
import cv2
import numpy as np
from config import MODEL_PROTO, MODEL_WEIGHTS, VOC_CLASSES

class AIClassifier:
    def __init__(self, proto_path=MODEL_PROTO, weights_path=MODEL_WEIGHTS):
        self.net = None
        self.available = False
        self.lock = threading.RLock()
        if os.path.exists(proto_path) and os.path.exists(weights_path):
            try:
                # 1 wątek na rdzeń CPU - nie koliduje ze strumieniem i enkoderem
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

    def detect_objects(self, frame_bytes):
        """
        Zwraca listę detekcji [('czlowiek' | 'pies', confidence), ...]
        W zbiorze Pascal VOC czworonogi domowe (psy) w warunkach domowych
        i przy sztucznym świetle są często klasyfikowane wymiennie jako 'dog' lub 'cat'.
        Dlatego 'dog', 'cat' oraz 'sheep' są mapowane jako czworonóg domowy ('pies').
        """
        if not self.available or not self.net or not frame_bytes:
            return []
        try:
            nparr = np.frombuffer(frame_bytes, dtype=np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return []

            blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 0.007843, (300, 300), 127.5)
            with self.lock:
                self.net.setInput(blob)
                detections = self.net.forward()

            found = []
            for i in range(detections.shape[2]):
                confidence = float(detections[0, 0, i, 2])
                idx = int(detections[0, 0, i, 1])
                if idx < len(VOC_CLASSES):
                    raw_label = VOC_CLASSES[idx]
                    if raw_label == "person" and confidence >= 0.40:
                        found.append(("czlowiek", confidence))
                    elif raw_label in ("dog", "cat", "sheep") and confidence >= 0.35:
                        found.append(("pies", confidence))
            return found
        except Exception:
            return []
