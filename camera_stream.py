#!/usr/bin/env python3
import io
import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PIL import Image, ImageChops, ImageStat, ImageFilter, ImageOps
import ipaddress
import cv2
import numpy as np

def is_local_client_ip(client_ip):
    try:
        ip = ipaddress.ip_address(client_ip)
        if ip.is_loopback:
            return True
        # Tailscale CGNAT IP range: 100.64.0.0/10
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return False
        # Private local RFC1918 networks (192.168.x.x, 10.x.x.x, 172.16.x.x)
        return ip.is_private
    except Exception:
        return False

RECORDINGS_DIR = "/home/bejek/recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

class StorageManager:
    def __init__(self, directory=RECORDINGS_DIR):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)

    def get_disk_info(self, is_recording=False):
        try:
            total, used, free = shutil.disk_usage(self.directory)
            total_gb = round(total / (1024**3), 1)
            used_gb = round(used / (1024**3), 1)
            free_gb = round(free / (1024**3), 1)
            free_pct = round((free / total) * 100, 1)
            used_pct = round((used / total) * 100, 1)

            rec_files = [f for f in os.listdir(self.directory) if f.endswith(".mp4")]
            total_rec_bytes = sum(os.path.getsize(os.path.join(self.directory, f)) for f in rec_files)
            total_rec_mb = round(total_rec_bytes / (1024**2), 1)

            return {
                "path": self.directory,
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "free_pct": free_pct,
                "used_pct": used_pct,
                "recordings_count": len(rec_files),
                "recordings_size_mb": total_rec_mb,
                "is_recording": is_recording
            }
        except Exception:
            return {
                "path": self.directory,
                "total_gb": 0, "used_gb": 0, "free_gb": 0, "free_pct": 0, "used_pct": 0,
                "recordings_count": 0, "recordings_size_mb": 0, "is_recording": is_recording
            }

    def cleanup_old_recordings(self, min_free_gb=2.0, target_free_gb=3.0):
        try:
            total, used, free = shutil.disk_usage(self.directory)
            free_gb = free / (1024**3)
            if free_gb >= min_free_gb:
                return

            mp4_files = []
            for f in os.listdir(self.directory):
                if f.endswith('.mp4'):
                    path = os.path.join(self.directory, f)
                    mp4_files.append((os.path.getmtime(path), f))

            mp4_files.sort()
            for mtime, fname in mp4_files:
                try:
                    base = fname[:-4]
                    os.remove(os.path.join(self.directory, fname))
                    thumb = os.path.join(self.directory, base + '.jpg')
                    if os.path.exists(thumb):
                        os.remove(thumb)
                except Exception:
                    pass
                total, used, free = shutil.disk_usage(self.directory)
                if (free / (1024**3)) >= target_free_gb:
                    break
        except Exception:
            pass

    def list_recordings(self):
        items = []
        try:
            for f in os.listdir(self.directory):
                if f.endswith(".mp4") and not f.startswith("."):
                    path = os.path.join(self.directory, f)
                    base = f[:-4]
                    thumb_name = base + ".jpg"
                    has_thumb = os.path.exists(os.path.join(self.directory, thumb_name))
                    mtime = os.path.getmtime(path)
                    size_mb = round(os.path.getsize(path) / (1024**2), 2)
                    dt_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

                    tag = "ruch"
                    if f.startswith("czlowiek_pies_"):
                        tag = "człowiek + pies"
                    elif f.startswith("czlowiek_"):
                        tag = "człowiek"
                    elif f.startswith("pies_"):
                        tag = "pies"
                    elif f.startswith("motion_"):
                        tag = "ruch (archiwalne)"

                    items.append({
                        "id": base,
                        "filename": f,
                        "tag": tag,
                        "thumbnail": f"/thumbnail/{thumb_name}" if has_thumb else None,
                        "video_url": f"/video/{f}",
                        "size_mb": size_mb,
                        "date": dt_str,
                        "timestamp": mtime
                    })
            items.sort(key=lambda x: x["timestamp"], reverse=True)
        except Exception:
            pass
        return items

    def delete_recording(self, filename):
        if not filename.endswith('.mp4') or '..' in filename or '/' in filename or '\\' in filename:
            return False
        base = filename[:-4]
        try:
            p = os.path.join(self.directory, filename)
            if os.path.exists(p):
                os.remove(p)
            t = os.path.join(self.directory, base + '.jpg')
            if os.path.exists(t):
                os.remove(t)
            return True
        except Exception:
            return False

storage_manager = StorageManager(RECORDINGS_DIR)

MODEL_PROTO = "/home/bejek/models/MobileNetSSD_deploy.prototxt"
MODEL_WEIGHTS = "/home/bejek/models/MobileNetSSD_deploy.caffemodel"

VOC_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair", "cow",
    "diningtable", "dog", "horse", "motorbike", "person",
    "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]

class AIClassifier:
    def __init__(self, proto_path=MODEL_PROTO, weights_path=MODEL_WEIGHTS):
        self.net = None
        self.available = False
        self.lock = threading.Lock()
        if os.path.exists(proto_path) and os.path.exists(weights_path):
            try:
                cv2.setNumThreads(2)
                self.net = cv2.dnn.readNetFromCaffe(proto_path, weights_path)
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self.available = True
                print("AIClassifier: MobileNet-SSD zaladowany pomyslnie.")
            except Exception as e:
                print(f"AIClassifier blad ladowania: {e}")
        else:
            print("AIClassifier: Brak plikow modelu MobileNet-SSD.")

    def detect_objects(self, frame_bytes, conf_threshold=0.45):
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

class VideoRecorder:
    def __init__(self, output_dir=RECORDINGS_DIR):
        self.output_dir = output_dir
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

        # AI classification worker
        self.ai = AIClassifier()
        self.detected_labels = set()
        self.last_detection_summary = "Brak"
        self.ai_busy = False
        self.last_ai_sample_time = 0
        self.ai_queue = deque(maxlen=1)
        self.ai_event = threading.Event()
        self.ai_thread = threading.Thread(target=self._ai_worker_loop, daemon=True)
        self.ai_thread.start()

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
                labels, details = self.ai.detect_objects(frame_bytes, conf_threshold=0.45)
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
            if not self.recording_enabled:
                return
            if getattr(motion_detector, 'is_dark', False):
                return
            if not self.is_recording:
                self.start_recording(frame_bytes)

    def start_recording(self, frame_bytes):
        if not self.recording_enabled or getattr(motion_detector, 'is_dark', False):
            return
        storage_manager.cleanup_old_recordings()
        ts_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.current_ts = ts_str
        self.detected_labels = set()
        self.last_ai_sample_time = time.time()

        # Temporary base filename: ruch_<timestamp>.mp4
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
        except Exception as e:
            self.proc = None
            self.is_recording = False

    def feed_frame(self, frame_bytes):
        with self.lock:
            if not self.recording_enabled or not self.is_recording or not self.proc:
                return
            now = time.time()
            # Max 2 minutes (120 seconds) per clip
            if (now - self.start_time) >= 120.0:
                self.stop_recording()
                # If motion occurred within last 15 seconds, start next clip seamlessly
                if (now - self.last_motion_time) <= 15.0 and self.recording_enabled and not getattr(motion_detector, 'is_dark', False):
                    self.start_recording(frame_bytes)
                return

            # Continue recording for 15 seconds after motion ceased
            if (now - self.last_motion_time) > 15.0:
                self.stop_recording()
                return

            try:
                self.proc.stdin.write(frame_bytes)
                self.frames_written += 1
            except Exception:
                self.stop_recording()
                return

            # Periodically sample frames for AI classification (every ~1.5s)
            if (now - self.last_ai_sample_time) >= 1.5 and not self.ai_busy:
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

            # Determine final file prefix:
            # - both person and dog: czlowiek_pies
            # - person only: czlowiek
            # - dog only: pies
            # - generic / unidentified motion: ruch
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
                    print(f"[AI Recorder] Blad zmiany nazwy: {e}")

        threading.Thread(target=finalize, args=(proc, filepath, detected_snapshot, ts_str), daemon=True).start()

video_recorder = VideoRecorder(RECORDINGS_DIR)

HTML_PAGE = """<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kamera &bull; CCTV</title>
    <style>
        :root {
            --bg: #09090b;
            --panel: #111114;
            --surface: #18181b;
            --border: #27272a;
            --border-subtle: #1f1f23;
            --border-hover: #3f3f46;
            --text: #f4f4f5;
            --text-muted: #71717a;
            --red: #dc2626;
            --red-dim: rgba(220, 38, 38, 0.15);
            --green: #16a34a;
            --amber: #d97706;
            --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: var(--font-mono);
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 12px;
            font-size: 13px;
            line-height: 1.4;
        }

        .container {
            width: 100%;
            max-width: 960px;
            background: var(--panel);
            border: 1px solid var(--border);
            margin-bottom: 24px;
        }

        /* Top Header Strip */
        .header {
            padding: 8px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border);
            background: #0d0d10;
        }

        .top-status {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .live-tag {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            font-weight: 700;
            color: #ef4444;
            background: var(--red-dim);
            border: 1px solid rgba(239, 68, 68, 0.3);
            padding: 2px 7px;
            letter-spacing: 0.08em;
        }

        .live-dot {
            width: 6px;
            height: 6px;
            background: #ef4444;
        }

        .badge {
            display: inline-block;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 7px;
            border: 1px solid var(--border);
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .badge-idle {
            color: var(--text-muted);
            background: #141418;
            border-color: #222228;
        }

        .badge-alert {
            color: #fecaca;
            background: #7f1d1d;
            border-color: #dc2626;
        }

        .badge-dark {
            color: #93c5fd;
            background: #172554;
            border-color: #2563eb;
        }

        .badge-green {
            color: #86efac;
            background: #14532d;
            border-color: #16a34a;
        }

        .badge-amber {
            color: #fde047;
            background: #713f12;
            border-color: #ca8a04;
        }

        .btn-tech {
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 4px 10px;
            font-family: inherit;
            font-size: 11px;
            letter-spacing: 0.04em;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            transition: border-color 0.15s, background 0.15s;
        }

        .btn-tech:hover {
            border-color: var(--border-hover);
            background: #222228;
        }

        .btn-tech.active {
            background: #27272a;
            border-color: #71717a;
            color: #fff;
        }

        /* Stream Viewport */
        .stream-view {
            position: relative;
            background: #000;
            width: 100%;
            aspect-ratio: 4 / 3;
            max-height: 720px;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            border-bottom: 1px solid var(--border);
        }

        .stream-view img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }

        /* Minimal discreet OSD tags in corner - no view obstruction */
        .osd-tag {
            position: absolute;
            z-index: 10;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
            padding: 2px 7px;
            background: rgba(0, 0, 0, 0.85);
            border: 1px solid #333;
            text-transform: uppercase;
            pointer-events: none;
        }

        .osd-rec {
            top: 10px;
            right: 10px;
            color: #ef4444;
            border-color: #ef4444;
            display: none;
        }

        .osd-paused {
            top: 10px;
            left: 10px;
            color: #f59e0b;
            border-color: #d97706;
            display: none;
        }

        .osd-dark {
            bottom: 10px;
            left: 10px;
            color: #60a5fa;
            border-color: #2563eb;
            display: none;
        }

        /* Primary Control Strip immediately under video */
        .control-strip {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            background: #0f1013;
            border-bottom: 1px solid var(--border);
            flex-wrap: wrap;
            gap: 8px;
        }

        .primary-actions {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }

        .btn-rec {
            background: #141418;
            border: 1px solid #dc2626;
            color: #f87171;
            padding: 5px 12px;
            font-family: inherit;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.15s;
        }

        .btn-rec:hover {
            background: #1f1215;
        }

        .btn-rec.paused {
            border-color: #d97706;
            color: #fbbf24;
            background: #161410;
        }

        .btn-rec.paused .rec-dot {
            background: #d97706;
        }

        .rec-dot {
            width: 7px;
            height: 7px;
            background: #dc2626;
        }

        .quick-metrics {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 11px;
            color: var(--text-muted);
            flex-wrap: wrap;
        }

        .quick-metrics span b {
            color: var(--text);
            font-weight: 600;
        }

        .btn-drawer {
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 4px 10px;
            font-family: inherit;
            font-size: 11px;
            letter-spacing: 0.04em;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .btn-drawer:hover {
            color: var(--text);
            border-color: var(--border-hover);
        }

        /* Collapsible Drawer */
        .telemetry-drawer {
            padding: 10px 12px;
            background: #0a0a0d;
            border-bottom: 1px solid var(--border);
        }

        .drawer-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 8px;
            margin-bottom: 10px;
        }

        .stat-cell {
            background: #111115;
            border: 1px solid var(--border-subtle);
            padding: 6px 8px;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .cell-label {
            font-size: 10px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .cell-val {
            font-size: 12px;
            font-weight: 600;
            color: var(--text);
        }

        .meter-bar {
            width: 100%;
            height: 3px;
            background: #222228;
            margin: 4px 0 2px 0;
            overflow: hidden;
        }

        .meter-bar-fill {
            height: 100%;
            width: 0%;
            background: #71717a;
            transition: width 0.15s ease-out;
        }

        .meter-bar-fill.alert {
            background: #dc2626;
        }

        .drawer-controls {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            padding-top: 6px;
            border-top: 1px solid var(--border-subtle);
        }

        .btn-group {
            display: inline-flex;
            border: 1px solid var(--border);
        }

        .btn-group .btn-tech {
            border: none;
            border-right: 1px solid var(--border);
        }

        .btn-group .btn-tech:last-child {
            border-right: none;
        }

        .sub-group {
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .sound-toggle {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            font-size: 11px;
            color: var(--text-muted);
            cursor: pointer;
            margin-left: auto;
        }

        /* Minimal Footer */
        .footer {
            padding: 8px 12px;
            background: #0d0d10;
            font-size: 10px;
            color: var(--text-muted);
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
        }

        .footer span b {
            color: var(--text);
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Top Status Bar -->
        <div class="header">
            <div class="top-status">
                <div class="live-tag">
                    <span class="live-dot"></span> LIVE
                </div>
                <div id="motion-badge" class="badge badge-idle">BRAK RUCHU</div>
                <div id="dark-badge" class="badge badge-dark" style="display:none;">TRYB NOCNY</div>
            </div>
            <div>
                <button class="btn-tech" onclick="toggleFullscreen()">Pełny ekran</button>
            </div>
        </div>

        <!-- Camera Viewport with clean corner OSD tags only -->
        <div class="stream-view" id="stream-container">
            <div id="rec-hud" class="osd-tag osd-rec">REC</div>
            <div id="rec-disabled-hud" class="osd-tag osd-paused">ZAPIS WYŁ</div>
            <div id="dark-hud" class="osd-tag osd-dark">NOC / UŚPIENIE</div>
            <img id="camera-stream" src="/stream.mjpg" alt="Podgląd kamery">
        </div>

        <!-- Control Strip directly below viewport -->
        <div class="control-strip">
            <div class="primary-actions">
                <button class="btn-rec" id="btn-toggle-rec" onclick="toggleRecording()">
                    <span class="rec-dot"></span>
                    <span id="rec-toggle-text">Zapis: Aktywny</span>
                </button>
                <div class="quick-metrics">
                    <span>Ruch: <b id="quick-pct">0.0%</b></span>
                    <span>Próg: <b id="quick-thresh">1.0%</b></span>
                    <span>Jasność: <b id="quick-bright">--</b></span>
                    <span>Zdarzenia: <b id="quick-events">0</b></span>
                    <span>AI: <b id="quick-ai">Gotowy</b></span>
                </div>
            </div>
            <div>
                <button id="btn-drawer" class="btn-drawer" onclick="toggleTelemetry()">
                    <span id="drawer-arrow">▼</span> Parametry detekcji
                </button>
            </div>
        </div>

        <!-- Collapsible Telemetry & Configuration Drawer -->
        <div id="telemetry-drawer" class="telemetry-drawer" style="display: none;">
            <div class="drawer-grid">
                <div class="stat-cell">
                    <span class="cell-label">Aktywność klatki</span>
                    <div class="meter-bar">
                        <div id="meter-fill" class="meter-bar-fill"></div>
                    </div>
                    <span id="pct-val" class="cell-val">0.0%</span>
                </div>
                <div class="stat-cell">
                    <span class="cell-label">Jasność otoczenia</span>
                    <span id="bright-val" class="cell-val">--</span>
                </div>
                <div class="stat-cell">
                    <span class="cell-label">Próg detekcji</span>
                    <span id="thresh-val" class="cell-val">Auto: 1.0%</span>
                </div>
                <div class="stat-cell">
                    <span class="cell-label">Szum tła</span>
                    <span id="noise-val" class="cell-val">0.0%</span>
                </div>
                <div class="stat-cell">
                    <span class="cell-label">Ostatni ruch</span>
                    <span id="last-motion-val" class="cell-val">Brak</span>
                </div>
                <div class="stat-cell">
                    <span class="cell-label">Licznik zdarzeń</span>
                    <span id="events-count" class="cell-val">0</span>
                </div>
                <div class="stat-cell">
                    <span class="cell-label">Klasyfikacja AI</span>
                    <span id="ai-drawer-val" class="cell-val">Pies / Człowiek / Ruch</span>
                </div>
            </div>

            <div class="drawer-controls">
                <button class="btn-tech active" id="b-dark-guard" onclick="toggleDarkGuard()">Pauza nocna: WŁ</button>

                <div class="btn-group">
                    <button class="btn-tech active" id="btn-mode-auto" onclick="setMode('auto')">Auto</button>
                    <button class="btn-tech" id="btn-mode-manual" onclick="setMode('manual')">Ręczny</button>
                </div>

                <div id="auto-subgroup" class="sub-group">
                    <button class="btn-tech" id="b-sens" onclick="setAutoBias('sensitive')">Wysoka (+0.5%)</button>
                    <button class="btn-tech active" id="b-norm" onclick="setAutoBias('normal')">Standard (+0.9%)</button>
                    <button class="btn-tech" id="b-safe" onclick="setAutoBias('safe')">Niska (+1.5%)</button>
                </div>

                <div id="manual-subgroup" class="sub-group" style="display: none;">
                    <input type="range" id="sens-slider" min="0.4" max="6.0" step="0.1" value="1.6" oninput="changeManualThreshold(this.value)" style="width: 80px; accent-color: #71717a;">
                    <span id="man-thresh-label" class="cell-val" style="font-size: 11px;">1.6%</span>
                </div>

                <label class="sound-toggle">
                    <input type="checkbox" id="sound-toggle" onchange="enableAudioCtx()">
                    <span>Dźwięk alarmu</span>
                </label>
            </div>
        </div>

        <!-- Minimal Technical Footer -->
        <div class="footer">
            <span>Format: <b>1640x1232 @ 15 FPS</b></span>
            <span>Algorytm: <b>MOG2 + MobileNet-SSD</b></span>
            <span>Zapis: <b id="footer-rec-badge">H.264 MP4 (maks. 2m / +15s)</b></span>
            <span>Dysk sieciowy: <b>\\192.168.1.24\nagrania</b></span>
            <span>Sensor: <b>Sony IMX219 NoIR</b></span>
        </div>
    </div>

    <script>
        let wasMotion = false;
        let audioCtx = null;
        let currentMode = "auto";
        let recordingEnabled = true;
        let ignoreInDark = true;

        function toggleTelemetry() {
            const drawer = document.getElementById('telemetry-drawer');
            const arrow = document.getElementById('drawer-arrow');
            const isHidden = drawer.style.display === 'none';
            drawer.style.display = isHidden ? 'block' : 'none';
            if (arrow) arrow.innerText = isHidden ? '▲' : '▼';
        }

        async function toggleDarkGuard() {
            try {
                const next = !ignoreInDark;
                const res = await fetch('/set_dark_guard?val=' + (next ? '1' : '0'));
                if (res.ok) {
                    const data = await res.json();
                    updateDarkGuardUI(data.ignore_in_dark);
                }
            } catch (err) {}
        }

        function updateDarkGuardUI(enabled) {
            ignoreInDark = enabled;
            const btn = document.getElementById('b-dark-guard');
            if (btn) {
                btn.className = 'btn-tech ' + (enabled ? 'active' : '');
                btn.innerText = enabled ? 'Pauza nocna: WŁ' : 'Pauza nocna: WYŁ';
            }
        }

        async function toggleRecording() {
            try {
                const res = await fetch('/toggle_recording');
                if (res.ok) {
                    const data = await res.json();
                    setRecordingEnabledUI(data.recording_enabled);
                }
            } catch (err) {}
        }

        function setRecordingEnabledUI(enabled) {
            recordingEnabled = enabled;
            const btn = document.getElementById('btn-toggle-rec');
            const btnText = document.getElementById('rec-toggle-text');
            const disabledHud = document.getElementById('rec-disabled-hud');
            const footerRecBadge = document.getElementById('footer-rec-badge');

            if (btn) {
                btn.className = 'btn-rec ' + (enabled ? 'active' : 'paused');
            }
            if (btnText) {
                btnText.innerText = enabled ? 'Zapis: Aktywny' : 'Zapis: Wstrzymany';
            }
            if (disabledHud) {
                disabledHud.style.display = enabled ? 'none' : 'block';
            }
            if (footerRecBadge) {
                footerRecBadge.innerText = enabled ? 'H.264 MP4 (maks. 2m / +15s)' : 'Wstrzymany';
            }
        }

        function toggleFullscreen() {
            const container = document.getElementById('stream-container');
            if (!document.fullscreenElement) {
                container.requestFullscreen().catch(err => alert(err.message));
            } else {
                document.exitFullscreen();
            }
        }

        function enableAudioCtx() {
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }
        }

        function playAlertSound() {
            const soundEnabled = document.getElementById('sound-toggle').checked;
            if (!soundEnabled) return;
            try {
                enableAudioCtx();
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(880, audioCtx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.15);
                gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
                gain.gain.linearRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start();
                osc.stop(audioCtx.currentTime + 0.16);
            } catch (err) {}
        }

        function setMode(mode) {
            currentMode = mode;
            document.getElementById('btn-mode-auto').classList.toggle('active', mode === 'auto');
            document.getElementById('btn-mode-manual').classList.toggle('active', mode === 'manual');
            document.getElementById('auto-subgroup').style.display = (mode === 'auto' ? 'inline-flex' : 'none');
            document.getElementById('manual-subgroup').style.display = (mode === 'manual' ? 'inline-flex' : 'none');
            fetch('/set_mode?mode=' + mode).catch(err => {});
        }

        function setAutoBias(bias) {
            document.getElementById('b-sens').classList.remove('active');
            document.getElementById('b-norm').classList.remove('active');
            document.getElementById('b-safe').classList.remove('active');
            if (bias === 'sensitive') document.getElementById('b-sens').classList.add('active');
            if (bias === 'normal') document.getElementById('b-norm').classList.add('active');
            if (bias === 'safe') document.getElementById('b-safe').classList.add('active');
            fetch('/set_auto_bias?bias=' + bias).catch(err => {});
        }

        function changeManualThreshold(val) {
            document.getElementById('man-thresh-label').innerText = parseFloat(val).toFixed(1) + '%';
            fetch('/set_threshold?val=' + encodeURIComponent(val)).catch(err => {});
        }

        async function pollStatus() {
            try {
                const res = await fetch('/status');
                if (!res.ok) return;
                const data = await res.json();

                const badge = document.getElementById('motion-badge');
                const darkBadge = document.getElementById('dark-badge');
                const darkHud = document.getElementById('dark-hud');
                const recHud = document.getElementById('rec-hud');
                const recDisabledHud = document.getElementById('rec-disabled-hud');
                const meterFill = document.getElementById('meter-fill');
                const pctVal = document.getElementById('pct-val');
                const threshVal = document.getElementById('thresh-val');
                const noiseVal = document.getElementById('noise-val');
                const lastMotionVal = document.getElementById('last-motion-val');
                const eventsCount = document.getElementById('events-count');
                const brightVal = document.getElementById('bright-val');

                // Quick strip metrics
                const quickPct = document.getElementById('quick-pct');
                const quickThresh = document.getElementById('quick-thresh');
                const quickBright = document.getElementById('quick-bright');
                const quickEvents = document.getElementById('quick-events');

                if (quickPct) quickPct.innerText = data.is_dark ? '0.0%' : (data.pct.toFixed(1) + '%');
                if (quickThresh) quickThresh.innerText = data.threshold.toFixed(1) + '%';
                if (quickBright) quickBright.innerText = Math.round(data.brightness);
                if (quickEvents) quickEvents.innerText = data.events_total;

                if (brightVal) {
                    brightVal.innerText = `${data.brightness} / 255` + (data.is_dark ? ' (Noc)' : '');
                }

                if (typeof data.ignore_in_dark !== 'undefined' && data.ignore_in_dark !== ignoreInDark) {
                    updateDarkGuardUI(data.ignore_in_dark);
                }

                // Motion badge & OSD tags (no view obstruction)
                if (data.is_dark) {
                    badge.className = 'badge badge-dark';
                    badge.innerText = 'UŚPIENIE (NOC)';
                    if (darkHud) darkHud.style.display = 'block';
                    if (darkBadge) darkBadge.style.display = 'inline-block';
                } else {
                    if (darkHud) darkHud.style.display = 'none';
                    if (darkBadge) darkBadge.style.display = 'none';
                    if (data.motion) {
                        badge.className = 'badge badge-alert';
                        badge.innerText = 'RUCH WYKRYTY';
                        if (!wasMotion) {
                            playAlertSound();
                        }
                    } else {
                        badge.className = 'badge badge-idle';
                        badge.innerText = 'BRAK RUCHU';
                    }
                }
                wasMotion = data.is_dark ? false : data.motion;

                // REC OSD indicator
                if (recHud) {
                    recHud.style.display = data.is_recording ? 'block' : 'none';
                }
                if (recDisabledHud) {
                    recDisabledHud.style.display = data.recording_enabled ? 'none' : 'block';
                }

                // Telemetry drawer values
                if (threshVal) threshVal.innerText = (data.mode === 'auto' ? `Auto: ${data.threshold.toFixed(1)}%` : `Ręczny: ${data.threshold.toFixed(1)}%`);
                if (noiseVal) noiseVal.innerText = `${data.base_noise.toFixed(1)}%`;
                if (pctVal) pctVal.innerText = data.is_dark ? '0.0% (Noc)' : (data.pct.toFixed(1) + '%');
                if (meterFill) {
                    const fillPct = Math.min(100, (data.pct / Math.max(data.threshold * 2, 4.0)) * 100);
                    meterFill.style.width = fillPct + '%';
                    if (data.pct >= data.threshold && !data.is_dark) {
                        meterFill.classList.add('alert');
                    } else {
                        meterFill.classList.remove('alert');
                    }
                }
                if (lastMotionVal) {
                    if (data.last_motion) {
                        const sec = data.seconds_since !== null ? `(${data.seconds_since}s temu)` : '';
                        lastMotionVal.innerText = `${data.last_motion} ${sec}`;
                    } else {
                        lastMotionVal.innerText = 'Brak od startu';
                    }
                }
                if (eventsCount) eventsCount.innerText = data.events_total;

                // AI classification updates
                const quickAi = document.getElementById('quick-ai');
                const aiDrawerVal = document.getElementById('ai-drawer-val');
                if (data.is_recording) {
                    let aiText = "Analiza...";
                    if (data.ai_active_labels && data.ai_active_labels.length > 0) {
                        aiText = data.ai_active_labels.map(l => l === 'czlowiek' ? 'Człowiek' : (l === 'pies' ? 'Pies' : l)).join(' + ');
                    }
                    if (quickAi) quickAi.innerText = aiText;
                    if (aiDrawerVal) aiDrawerVal.innerText = 'W toku: ' + aiText;
                } else {
                    const lastSummary = data.ai_last_detection && data.ai_last_detection !== 'Brak' ? data.ai_last_detection : (data.ai_loaded ? 'Gotowy' : 'Wyłączony');
                    if (quickAi) quickAi.innerText = data.ai_last_detection && data.ai_last_detection !== 'Brak' ? data.ai_last_detection : 'Gotowy';
                    if (aiDrawerVal) aiDrawerVal.innerText = lastSummary;
                }

                // Sync recording enabled state
                if (typeof data.recording_enabled !== 'undefined' && data.recording_enabled !== recordingEnabled) {
                    setRecordingEnabledUI(data.recording_enabled);
                }

            } catch (err) {}
        }

        setInterval(pollStatus, 300);
        pollStatus();
    </script>
</body>
</html>
"""

class CameraStreamer:
    def __init__(self, width=1640, height=1232, framerate=15, quality=65):
        self.width = width
        self.height = height
        self.framerate = framerate
        self.quality = quality
        self.frame = None
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.running = False
        self.process = None
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self):
        cmd = [
            "rpicam-vid",
            "-t", "0",
            "--mode", "1640:1232:10",
            "--width", str(self.width),
            "--height", str(self.height),
            "--framerate", str(self.framerate),
            "--codec", "mjpeg",
            "-q", str(self.quality),
            "--tuning-file", "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json",
            "-o", "-",
            "--nopreview"
        ]
        while self.running:
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=65536
                )
                buffer = b""
                while self.running:
                    chunk = self.process.stdout.read(8192)
                    if not chunk:
                        break
                    buffer += chunk
                    while True:
                        start = buffer.find(b"\xff\xd8")
                        if start == -1:
                            buffer = buffer[-2:]
                            break
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end == -1:
                            if start > 0:
                                buffer = buffer[start:]
                            break
                        jpg = buffer[start:end+2]
                        buffer = buffer[end+2:]
                        with self.condition:
                            self.frame = jpg
                            self.condition.notify_all()
                        # Pass frame to recorder
                        video_recorder.feed_frame(jpg)
            except Exception:
                time.sleep(1)
            finally:
                if self.process:
                    try:
                        self.process.terminate()
                        self.process.wait(timeout=2)
                    except Exception:
                        self.process.kill()
                    self.process = None

    def get_frame(self):
        with self.condition:
            if self.condition.wait(timeout=2.0):
                return self.frame
            return self.frame

class MotionDetector(threading.Thread):
    def __init__(self, streamer):
        super().__init__(daemon=True)
        self.streamer = streamer
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
        self.lock = threading.Lock()

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
                # Fast OpenCV JPEG decoding & preprocessing
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

                # If darkness guard triggered, update model slowly without triggering motion
                if is_too_dark:
                    self.subtractor.apply(blurred, learningRate=0.005)
                    with self.lock:
                        self.raw_motion = False
                        self.last_pct = 0.0
                        self.last_score = 0.0
                        self.motion_active = False
                    continue

                # Warmup frames at start to initialize background model
                if self.warmup_frames > 0:
                    self.subtractor.apply(blurred)
                    self.warmup_frames -= 1
                    continue

                # Apply MOG2 background subtraction
                fgmask = self.subtractor.apply(blurred)

                # Filter: keep only moving foreground (255), ignore shadows (127) and background (0)
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
                        # Trigger motion video recording!
                        video_recorder.trigger_motion(frame)

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
        with self.lock:
            active = (now - self.last_motion_time < 3.0) if self.last_motion_time > 0 and not self.is_dark else False
            sec_since = round(now - self.last_motion_time, 1) if self.last_motion_time > 0 else None
            last_str = time.strftime('%H:%M:%S', time.localtime(self.last_motion_time)) if self.last_motion_time > 0 else None

            with video_recorder.lock:
                rec_active_labels = list(video_recorder.detected_labels) if video_recorder.is_recording else []
                last_ai = video_recorder.last_detection_summary

            return {
                "motion": active,
                "raw_motion": self.raw_motion,
                "score": self.last_score,
                "pct": self.last_pct,
                "threshold": round(self.effective_threshold, 1),
                "mode": self.mode,
                "auto_bias": self.auto_bias,
                "base_noise": round(self.base_noise, 1),
                "is_recording": video_recorder.is_recording,
                "recording_enabled": video_recorder.recording_enabled,
                "last_motion": last_str,
                "seconds_since": sec_since,
                "events_total": self.events_total,
                "brightness": self.last_brightness,
                "is_dark": self.is_dark,
                "ignore_in_dark": self.ignore_in_dark,
                "darkness_threshold": self.darkness_threshold,
                "ai_loaded": video_recorder.ai.available,
                "ai_last_detection": last_ai,
                "ai_active_labels": rec_active_labels
            }

streamer = CameraStreamer(width=1640, height=1232, framerate=15, quality=65)
motion_detector = MotionDetector(streamer)

def serve_range_file(handler, filepath, content_type):
    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        handler.send_error(404)
        return

    range_header = handler.headers.get('Range')
    if not range_header:
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Length', str(file_size))
        handler.send_header('Accept-Ranges', 'bytes')
        handler.end_headers()
        try:
            with open(filepath, 'rb') as f:
                while chunk := f.read(65536):
                    handler.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return

    try:
        parts = range_header.replace('bytes=', '').split('-')
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        if end >= file_size:
            end = file_size - 1
        length = end - start + 1

        handler.send_response(206)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
        handler.send_header('Content-Length', str(length))
        handler.send_header('Accept-Ranges', 'bytes')
        handler.end_headers()

        with open(filepath, 'rb') as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(remaining, 65536))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception:
        handler.send_error(500)

class StreamingHandler(BaseHTTPRequestHandler):
    def is_local_client(self):
        return is_local_client_ip(self.client_address[0])

    def log_message(self, format, *args):
        try:
            msg = format % args
            if any(p in msg for p in ("/stream.mjpg", "/status", "/api/")):
                return
        except Exception:
            pass
        super().log_message(format, *args)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
        elif parsed.path == '/snapshot.jpg':
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.end_headers()
        elif parsed.path == '/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
        elif parsed.path.startswith('/video/'):
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            fname = parsed.path[len('/video/'):]
            fpath = os.path.join(RECORDINGS_DIR, fname)
            if os.path.exists(fpath) and fname.endswith('.mp4'):
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Length', str(os.path.getsize(fpath)))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
            else:
                self.send_error(404)
        elif parsed.path.startswith('/thumbnail/'):
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            fname = parsed.path[len('/thumbnail/'):]
            fpath = os.path.join(RECORDINGS_DIR, fname)
            if os.path.exists(fpath) and fname.endswith('.jpg'):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(os.path.getsize(fpath)))
                self.end_headers()
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            content = HTML_PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif parsed.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    frame = streamer.get_frame()
                    if frame is None:
                        continue
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except (ConnectionResetError, BrokenPipeError):
                pass
        elif parsed.path == '/snapshot.jpg':
            frame = streamer.frame
            if frame:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(frame)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_error(503, "Camera warming up")
        elif parsed.path == '/status':
            status = motion_detector.get_status()
            status["is_local"] = self.is_local_client()
            data = json.dumps(status).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/api/storage':
            info = storage_manager.get_disk_info(is_recording=video_recorder.is_recording)
            info["is_local"] = self.is_local_client()
            info["recording_enabled"] = video_recorder.recording_enabled
            data = json.dumps(info).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/api/recordings':
            if not self.is_local_client():
                data = json.dumps({"error": "forbidden", "is_local": False, "message": "Nagrania wideo są dostępne wyłącznie w sieci lokalnej (LAN)"}).encode('utf-8')
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            recs = storage_manager.list_recordings()
            data = json.dumps(recs).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path.startswith('/video/'):
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            filename = parsed.path[len('/video/'):]
            filepath = os.path.join(RECORDINGS_DIR, filename)
            if os.path.exists(filepath) and filename.endswith('.mp4'):
                serve_range_file(self, filepath, 'video/mp4')
            else:
                self.send_error(404, "Video not found")
        elif parsed.path.startswith('/thumbnail/'):
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            filename = parsed.path[len('/thumbnail/'):]
            filepath = os.path.join(RECORDINGS_DIR, filename)
            if os.path.exists(filepath) and filename.endswith('.jpg'):
                serve_range_file(self, filepath, 'image/jpeg')
            else:
                self.send_error(404, "Thumbnail not found")
        elif parsed.path == '/api/delete_recording':
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            query = parse_qs(parsed.query)
            fname = query.get('file', [''])[0]
            ok = storage_manager.delete_recording(fname)
            data = json.dumps({"status": "ok" if ok else "error"}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/toggle_recording':
            query = parse_qs(parsed.query)
            if 'enabled' in query:
                val = query['enabled'][0].lower()
                enabled = val in ('1', 'true', 'yes', 'on')
            else:
                enabled = not video_recorder.recording_enabled
            video_recorder.set_recording_enabled(enabled)
            data = json.dumps({
                "status": "ok",
                "recording_enabled": video_recorder.recording_enabled,
                "is_recording": video_recorder.is_recording
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/set_mode':
            query = parse_qs(parsed.query)
            if 'mode' in query:
                motion_detector.set_mode(query['mode'][0])
            data = json.dumps({"status": "ok", "mode": motion_detector.mode}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/set_auto_bias':
            query = parse_qs(parsed.query)
            if 'bias' in query:
                motion_detector.set_auto_bias(query['bias'][0])
            data = json.dumps({"status": "ok", "auto_bias": motion_detector.auto_bias}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/set_threshold':
            query = parse_qs(parsed.query)
            if 'val' in query:
                motion_detector.set_manual_threshold(query['val'][0])
            data = json.dumps({"status": "ok", "threshold": motion_detector.effective_threshold}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/set_dark_guard':
            query = parse_qs(parsed.query)
            if 'val' in query:
                val = query['val'][0].lower()
                enabled = val in ('1', 'true', 'yes', 'on')
                motion_detector.set_ignore_in_dark(enabled)
            data = json.dumps({"status": "ok", "ignore_in_dark": motion_detector.ignore_in_dark}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == '/set_dark_threshold':
            query = parse_qs(parsed.query)
            if 'val' in query:
                motion_detector.set_darkness_threshold(query['val'][0])
            data = json.dumps({"status": "ok", "darkness_threshold": motion_detector.darkness_threshold}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

def main():
    streamer.start()
    motion_detector.start()
    server_address = ('0.0.0.0', 8000)
    httpd = ThreadingHTTPServer(server_address, StreamingHandler)
    print("Camera server with Motion Recording & Storage Manager running at http://0.0.0.0:8000")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        streamer.running = False
        motion_detector.running = False
        video_recorder.stop_recording()
        if streamer.process:
            streamer.process.terminate()

if __name__ == '__main__':
    main()
