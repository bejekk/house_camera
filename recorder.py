#!/usr/bin/env python3
import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from config import RECORDINGS_DIR, MAX_CLIP_DURATION, POST_MOTION_DURATION, AI_SAMPLE_INTERVAL
from storage import storage_manager
from ai_classifier import AIClassifier

class VideoRecorder:
    def __init__(self, output_dir=RECORDINGS_DIR, motion_detector_getter=None):
        self.output_dir = output_dir
        self.motion_detector_getter = motion_detector_getter
        self.is_recording = False
        self.recording_enabled = True
        self.proc = None
        self.current_filename = None
        self.current_filepath = None
        self.current_ts = ""
        self.start_time = 0
        self.last_motion_time = 0
        self.lock = threading.Lock()
        self.frames_written = 0

        # Asynchroniczny worker klasyfikacji AI
        self.ai = AIClassifier()
        self.detected_labels = set()
        self.last_detection_summary = "Brak"
        self.ai_busy = False
        self.last_ai_sample_time = 0
        self.ai_queue = deque(maxlen=1)
        self.ai_event = threading.Event()
        self.ai_thread = threading.Thread(target=self._ai_worker_loop, daemon=True)
        self.ai_thread.start()

    def _is_dark(self):
        if self.motion_detector_getter:
            detector = self.motion_detector_getter()
            if detector:
                return getattr(detector, 'is_dark', False)
        return False

    def _ai_worker_loop(self):
        while True:
            self.ai_event.wait()
            self.ai_event.clear()
            frame_bytes = None
            try:
                if self.ai_queue:
                    frame_bytes = self.ai_queue.popleft()
            except IndexError:
                continue

            if frame_bytes:
                self.ai_busy = True
                labels, details = self.ai.detect_objects(frame_bytes)
                if labels:
                    with self.lock:
                        self.detected_labels.update(labels)
                        summary_parts = [f"{lbl} ({round(conf*100)}%)" for lbl, conf in details]
                        self.last_detection_summary = ", ".join(summary_parts)
                self.ai_busy = False

    def set_recording_enabled(self, enabled: bool):
        with self.lock:
            self.recording_enabled = bool(enabled)
            if not self.recording_enabled and self.is_recording:
                self.stop_recording()

    def trigger_motion(self, frame_bytes):
        with self.lock:
            now = time.time()
            self.last_motion_time = now
            if not self.recording_enabled or self._is_dark():
                return
            if not self.is_recording:
                self.start_recording(frame_bytes)

    def start_recording(self, frame_bytes):
        if not self.recording_enabled or self._is_dark():
            return
        storage_manager.cleanup_old_recordings()
        ts_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.current_ts = ts_str
        self.detected_labels = set()
        self.last_ai_sample_time = time.time()

        # Domyślna nazwa bazowa podczas nagrywania: ruch_<ts>.mp4
        self.current_filename = f"ruch_{ts_str}.mp4"
        self.current_filepath = os.path.join(self.output_dir, self.current_filename)

        cmd = [
            "ffmpeg", "-y",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-framerate", "15",
            "-i", "-",
            "-vf", "scale=820:616",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            self.current_filepath
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.is_recording = True
            self.start_time = time.time()
            self.frames_written = 0
            if frame_bytes:
                try:
                    self.proc.stdin.write(frame_bytes)
                    self.frames_written += 1
                except Exception:
                    pass
                if not self.ai_busy:
                    self.ai_queue.append(frame_bytes)
                    self.ai_event.set()
        except Exception:
            self.proc = None
            self.is_recording = False

    def feed_frame(self, frame_bytes):
        with self.lock:
            if not self.recording_enabled or not self.is_recording or not self.proc:
                return
            now = time.time()
            # Ograniczenie do maksymalnie 2 minut na klip
            if (now - self.start_time) >= MAX_CLIP_DURATION:
                self.stop_recording()
                # Jeśli ruch nadal trwa w ostatnich 15 sekundach, rozpocznij kolejny klip
                if (now - self.last_motion_time) <= POST_MOTION_DURATION and self.recording_enabled and not self._is_dark():
                    self.start_recording(frame_bytes)
                return

            # Dogrywanie przez 15 sekund po ustaniu ruchu
            if (now - self.last_motion_time) > POST_MOTION_DURATION:
                self.stop_recording()
                return

            try:
                self.proc.stdin.write(frame_bytes)
                self.frames_written += 1
            except Exception:
                self.stop_recording()
                return

            # Próbkowanie klatek dla AI (co ok. 1.5s bez blokowania strumienia)
            if (now - self.last_ai_sample_time) >= AI_SAMPLE_INTERVAL and not self.ai_busy:
                self.last_ai_sample_time = now
                self.ai_queue.append(frame_bytes)
                self.ai_event.set()

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        proc = self.proc
        self.proc = None
        filepath = self.current_filepath
        ts_str = self.current_ts
        detected_snapshot = set(self.detected_labels)

        def finalize(p, fpath, detected_classes, ts):
            try:
                if p.stdin:
                    p.stdin.close()
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

            time.sleep(0.6)
            with self.lock:
                final_detected = set(detected_classes).union(self.detected_labels)

            # Ustalenie ostatecznego prefiksu pliku:
            # - człowiek i pies: czlowiek_pies
            # - tylko człowiek: czlowiek
            # - tylko pies: pies
            # - inny/niezidentyfikowany ruch: ruch
            if "czlowiek" in final_detected and "pies" in final_detected:
                prefix = "czlowiek_pies"
            elif "czlowiek" in final_detected:
                prefix = "czlowiek"
            elif "pies" in final_detected:
                prefix = "pies"
            else:
                prefix = "ruch"

            target_filename = f"{prefix}_{ts}.mp4"
            target_filepath = os.path.join(self.output_dir, target_filename)

            if fpath and os.path.exists(fpath) and fpath != target_filepath:
                try:
                    os.rename(fpath, target_filepath)
                    print(f"[AI Recorder] Nagranie zapisane: {target_filename} (wykryto: {final_detected})")
                except Exception as e:
                    print(f"[AI Recorder] Błąd zmiany nazwy: {e}")

        threading.Thread(target=finalize, args=(proc, filepath, detected_snapshot, ts_str), daemon=True).start()

video_recorder = VideoRecorder(RECORDINGS_DIR)
