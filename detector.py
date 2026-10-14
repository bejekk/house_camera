#!/usr/bin/env python3
import threading
import time
from collections import deque
import cv2
import numpy as np

class MotionDetector(threading.Thread):
    def __init__(self, streamer, on_motion=None, get_recorder_status=None):
        super().__init__(daemon=True)
        self.streamer = streamer
        self.on_motion = on_motion
        self.get_recorder_status = get_recorder_status
        self.mode = "auto"
        self.auto_bias = "normal"
        self.manual_threshold = 1.6
        self.effective_threshold = 1.0
        self.base_noise = 0.0
        self.noise_window = deque(maxlen=20)
        self.running = True
        self.motion_active = False
        self.raw_motion = False
        self.last_motion_time = 0
        self.events_total = 0
        self.last_score = 0.0
        self.last_pct = 0.0
        self.last_brightness = 0.0
        self.darkness_threshold = 12.0
        self.ignore_in_dark = True
        self.is_dark = False
        self.warmup_frames = 10
        self.subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=25, detectShadows=True)
        self.morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        self.lock = threading.RLock()

    def set_ignore_in_dark(self, enabled: bool):
        with self.lock:
            self.ignore_in_dark = bool(enabled)

    def set_darkness_threshold(self, val):
        with self.lock:
            try:
                self.darkness_threshold = max(3.0, min(50.0, float(val)))
            except ValueError:
                pass

    def run(self):
        while self.running:
            time.sleep(0.20)
            frame = self.streamer.frame
            if frame is None:
                continue
            try:
                nparr = np.frombuffer(frame, dtype=np.uint8)
                img_gray = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                if img_gray is None:
                    continue
                small = cv2.resize(img_gray, (120, 90))
                brightness = float(np.mean(small))
                blurred = cv2.GaussianBlur(small, (5, 5), 0)

                dark_limit = self.darkness_threshold if not self.is_dark else (self.darkness_threshold + 2.0)
                is_too_dark = (brightness < dark_limit) and self.ignore_in_dark

                with self.lock:
                    self.last_brightness = round(brightness, 1)
                    self.is_dark = is_too_dark

                if is_too_dark:
                    self.subtractor.apply(blurred, learningRate=0.005)
                    with self.lock:
                        self.raw_motion = False
                        self.last_pct = 0.0
                        self.last_score = 0.0
                        self.motion_active = False
                    continue

                if self.warmup_frames > 0:
                    self.subtractor.apply(blurred)
                    self.warmup_frames -= 1
                    continue

                fgmask = self.subtractor.apply(blurred)
                fg_only = (fgmask == 255).astype(np.uint8) * 255
                fg_clean = cv2.morphologyEx(fg_only, cv2.MORPH_OPEN, self.morph_kernel)

                fg_pixels = cv2.countNonZero(fg_clean)
                pct = (fg_pixels / 10800.0) * 100.0

                contours, _ = cv2.findContours(fg_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                max_contour = max([cv2.contourArea(c) for c in contours], default=0.0)
                score = round((max_contour / 10800.0) * 100.0, 2)

                eff_thresh = self.effective_threshold
                min_contour_area = max(20.0, eff_thresh * 25.0)

                now = time.time()
                is_moving = (pct >= eff_thresh) or (max_contour >= min_contour_area and pct >= 0.3)

                with self.lock:
                    self.raw_motion = is_moving
                    self.last_pct = round(pct, 1)
                    self.last_score = score
                    if is_moving:
                        if not self.motion_active:
                            self.events_total += 1
                        self.last_motion_time = now
                        if self.on_motion:
                            self.on_motion(frame)

                    self.motion_active = (now - self.last_motion_time < 3.0)

                    if self.mode == "auto":
                        if not self.motion_active:
                            self.noise_window.append(pct)
                            sorted_w = sorted(self.noise_window)
                            idx = max(0, len(sorted_w) // 5)
                            self.base_noise = sorted_w[idx]

                            margin = 0.5 if self.auto_bias == "sensitive" else (0.9 if self.auto_bias == "normal" else 1.5)
                            target_thresh = max(0.6, min(4.5, self.base_noise + margin))

                            if target_thresh < self.effective_threshold:
                                self.effective_threshold = self.effective_threshold * 0.75 + target_thresh * 0.25
                            else:
                                self.effective_threshold = self.effective_threshold * 0.85 + target_thresh * 0.15
                    else:
                        self.effective_threshold = self.manual_threshold

            except Exception:
                continue

    def set_mode(self, mode):
        with self.lock:
            if mode in ("auto", "manual"):
                self.mode = mode

    def set_auto_bias(self, bias):
        with self.lock:
            if bias in ("sensitive", "normal", "safe"):
                self.auto_bias = bias

    def set_manual_threshold(self, val):
        with self.lock:
            try:
                self.manual_threshold = max(0.4, min(15.0, float(val)))
                if self.mode == "manual":
                    self.effective_threshold = self.manual_threshold
            except ValueError:
                pass

    def get_status(self):
        now = time.time()
        rec_status = self.get_recorder_status() if self.get_recorder_status else {}
        with self.lock:
            active = (now - self.last_motion_time < 3.0) if self.last_motion_time > 0 and not self.is_dark else False
            sec_since = round(now - self.last_motion_time, 1) if self.last_motion_time > 0 else None
            last_str = time.strftime('%H:%M:%S', time.localtime(self.last_motion_time)) if self.last_motion_time > 0 else None

            status = {
                "motion": active,
                "raw_motion": self.raw_motion,
                "score": self.last_score,
                "pct": self.last_pct,
                "threshold": round(self.effective_threshold, 1),
                "mode": self.mode,
                "auto_bias": self.auto_bias,
                "base_noise": round(self.base_noise, 1),
                "last_motion": last_str,
                "seconds_since": sec_since,
                "events_total": self.events_total,
                "brightness": self.last_brightness,
                "is_dark": self.is_dark,
                "ignore_in_dark": self.ignore_in_dark,
                "darkness_threshold": self.darkness_threshold
            }
            status.update(rec_status)
            return status
