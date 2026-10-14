#!/usr/bin/env python3
import subprocess
import threading
import time
from config import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS, CAMERA_QUALITY

class CameraStreamer:
    def __init__(self, width=CAMERA_WIDTH, height=CAMERA_HEIGHT, framerate=CAMERA_FPS, quality=CAMERA_QUALITY, on_frame=None):
        self.width = width
        self.height = height
        self.framerate = framerate
        self.quality = quality
        self.on_frame = on_frame
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
            "--inline",
            "--codec", "mjpeg",
            "--width", str(self.width),
            "--height", str(self.height),
            "--framerate", str(self.framerate),
            "-q", str(self.quality),
            "--nopreview",
            "-o", "-"
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
                        if self.on_frame:
                            self.on_frame(jpg)
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
