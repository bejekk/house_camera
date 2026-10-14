#!/usr/bin/env python3
import os
import shutil
from datetime import datetime
from config import RECORDINGS_DIR

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
                    os.remove(os.path.join(self.directory, fname))
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
                        "thumbnail": None,
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
        try:
            p = os.path.join(self.directory, filename)
            if os.path.exists(p):
                os.remove(p)
            return True
        except Exception:
            return False

storage_manager = StorageManager(RECORDINGS_DIR)
