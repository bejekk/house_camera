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
        self.lock = threading.RLock()
        self.frames_written = 0

        # Asynchroniczna kolejka klatek wideo do zapisu (brak blokowania strumienia kamery)
        self.rec_queue = deque(maxlen=30)
        self.rec_event = threading.Event()
        self.writer_thread = None

        # Asynchroniczny worker klasyfikacji AI
        self.ai = AIClassifier()
        self.person_confs = []
        self.dog_confs = []
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
                dets = self.ai.detect_objects(frame_bytes)
                if dets:
                    with self.lock:
                        for label, conf in dets:
                            if label == "czlowiek":
                                self.person_confs.append(conf)
                            elif label == "pies":
                                self.dog_confs.append(conf)

                        # Wieloklatkowa weryfikacja na żywo
                        is_p = (len([c for c in self.person_confs if c >= 0.50]) >= 2) or any(c >= 0.65 for c in self.person_confs)
                        is_d = (len([c for c in self.dog_confs if c >= 0.38]) >= 2) or any(c >= 0.55 for c in self.dog_confs)

                        labels = set()
                        summary_parts = []
                        if is_p:
                            labels.add("czlowiek")
                            max_p = max(self.person_confs, default=0.0)
                            summary_parts.append(f"człowiek ({round(max_p*100)}%)")
                        if is_d:
                            labels.add("pies")
                            max_d = max(self.dog_confs, default=0.0)
                            summary_parts.append(f"pies ({round(max_d*100)}%)")

                        self.detected_labels = labels
                        if summary_parts:
                            self.last_detection_summary = ", ".join(summary_parts)
                self.ai_busy = False

    def _writer_loop(self, proc, queue, event):
        """Dedykowany wątek piszący do potoku ffmpeg w tle - zapobiega jakimkolwiek przycięciom kamery."""
        while self.is_recording or len(queue) > 0:
            event.wait(timeout=0.1)
            event.clear()
            while len(queue) > 0:
                try:
                    frame = queue.popleft()
                except IndexError:
                    break
                if proc and proc.stdin:
                    try:
                        proc.stdin.write(frame)
                        self.frames_written += 1
                    except (BrokenPipeError, OSError):
                        return

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
        self.person_confs = []
        self.dog_confs = []
        self.detected_labels = set()
        self.last_ai_sample_time = time.time()
        self.rec_queue.clear()
        self.rec_event.clear()

        # Domyślna nazwa bazowa podczas nagrywania: ruch_<ts>.mp4
        self.current_filename = f"ruch_{ts_str}.mp4"
        self.current_filepath = os.path.join(self.output_dir, self.current_filename)

        # Użycie sprzętowego enkodera VideoCore IV (h264_v4l2m2m) - minimalne zużycie CPU na Pi 3B!
        cmd = [
            "ffmpeg", "-y",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-framerate", "15",
            "-i", "-",
            "-c:v", "h264_v4l2m2m",
            "-b:v", "2500k",
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

            # Uruchomienie wątku zapisującego w tle
            self.writer_thread = threading.Thread(
                target=self._writer_loop,
                args=(self.proc, self.rec_queue, self.rec_event),
                daemon=True
            )
            self.writer_thread.start()

            if frame_bytes:
                self.rec_queue.append(frame_bytes)
                self.rec_event.set()
                if not self.ai_busy:
                    self.ai_queue.append(frame_bytes)
                    self.ai_event.set()
        except Exception:
            # Rezerwowy enkoder programowy libx264, gdyby enkoder sprzętowy był niedostępny
            fallback_cmd = [
                "ffmpeg", "-y",
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "-framerate", "15",
                "-i", "-",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "26",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                self.current_filepath
            ]
            try:
                self.proc = subprocess.Popen(
                    fallback_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.is_recording = True
                self.start_time = time.time()
                self.frames_written = 0
                self.writer_thread = threading.Thread(
                    target=self._writer_loop,
                    args=(self.proc, self.rec_queue, self.rec_event),
                    daemon=True
                )
                self.writer_thread.start()
                if frame_bytes:
                    self.rec_queue.append(frame_bytes)
                    self.rec_event.set()
            except Exception:
                self.proc = None
                self.is_recording = False

    def feed_frame(self, frame_bytes):
        should_stop = False
        should_restart = False
        with self.lock:
            if not self.recording_enabled or not self.is_recording:
                return
            now = time.time()
            # Ograniczenie do maksymalnie 2 minut na klip
            if (now - self.start_time) >= MAX_CLIP_DURATION:
                should_stop = True
                if (now - self.last_motion_time) <= POST_MOTION_DURATION and not self._is_dark():
                    should_restart = True
            elif (now - self.last_motion_time) > POST_MOTION_DURATION:
                should_stop = True
            else:
                # Wrzucenie klatki do kolejki w tle (operacja natychmiastowa, ~0.001 ms, brak blokowania)
                self.rec_queue.append(frame_bytes)
                self.rec_event.set()

                # Próbkowanie klatek dla AI (co ok. 1.8s)
                if (now - self.last_ai_sample_time) >= AI_SAMPLE_INTERVAL and not self.ai_busy:
                    self.last_ai_sample_time = now
                    self.ai_queue.append(frame_bytes)
                    self.ai_event.set()

        if should_stop:
            self.stop_recording()
            if should_restart:
                self.start_recording(frame_bytes)

    def stop_recording(self):
        with self.lock:
            if not self.is_recording:
                return
            self.is_recording = False
            proc = self.proc
            self.proc = None
            filepath = self.current_filepath
            ts_str = self.current_ts
            p_confs = list(self.person_confs)
            d_confs = list(self.dog_confs)
            rec_q = self.rec_queue
            rec_ev = self.rec_event

        def finalize(p, fpath, p_list, d_list, ts, queue, event):
            # Opróżnij pozostałe klatki z bufora
            event.set()
            time.sleep(0.3)
            while len(queue) > 0:
                try:
                    f = queue.popleft()
                    if p and p.stdin:
                        p.stdin.write(f)
                except Exception:
                    break

            try:
                if p and p.stdin:
                    p.stdin.close()
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

            time.sleep(0.5)
            with self.lock:
                final_p = p_list + [c for c in self.person_confs if c not in p_list]
                final_d = d_list + [c for c in self.dog_confs if c not in d_list]

            # Odporna weryfikacja wieloklatkowa (eliminuje fałszywe trafienia z pojedynczych klatek)
            # Człowiek: minimum 2 trafienia >= 50% LUB 1 bardzo wyraźne trafienie >= 65%
            is_person = (len([c for c in final_p if c >= 0.50]) >= 2) or any(c >= 0.65 for c in final_p)
            # Pies: minimum 2 trafienia >= 38% LUB 1 wyraźne trafienie >= 55%
            is_dog = (len([c for c in final_d if c >= 0.38]) >= 2) or any(c >= 0.55 for c in final_d)

            if is_person and is_dog:
                prefix = "czlowiek_pies"
            elif is_person:
                prefix = "czlowiek"
            elif is_dog:
                prefix = "pies"
            else:
                prefix = "ruch"

            target_filename = f"{prefix}_{ts}.mp4"
            target_filepath = os.path.join(self.output_dir, target_filename)

            if fpath and os.path.exists(fpath) and fpath != target_filepath:
                try:
                    os.rename(fpath, target_filepath)
                    print(f"[AI Recorder] Nagranie zapisane: {target_filename} (człowiek: {len(final_p)} próbek, pies: {len(final_d)} próbek)")
                except Exception as e:
                    print(f"[AI Recorder] Błąd zmiany nazwy: {e}")

        threading.Thread(
            target=finalize,
            args=(proc, filepath, p_confs, d_confs, ts_str, rec_q, rec_ev),
            daemon=True
        ).start()

video_recorder = VideoRecorder(RECORDINGS_DIR)
