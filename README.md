# Raspberry Pi CCTV Surveillance System

*Available languages: **English** | [Polski](README.pl.md)*

A lightweight, standalone home surveillance system featuring live streaming, OpenCV MOG2 motion detection, intelligent AI object classification (person / dog / motion) using MobileNet-SSD, direct MP4 video recording (H.264, up to 2 min clips) to a Samba network share, and a web-based CCTV monitoring dashboard.

### 🧠 Intelligent Recording Classification (AI)
When motion is detected, the system analyzes frames in the background using a MobileNet-SSD neural network with a robust multi-frame voting algorithm (preventing false alarms) and automatically names video files:
* `czlowiek_pies_YYYY-MM-DD_HH-MM-SS.mp4` – when both a person and a dog are in frame
* `czlowiek_YYYY-MM-DD_HH-MM-SS.mp4` – when a person is detected
* `pies_YYYY-MM-DD_HH-MM-SS.mp4` – when a dog / pet is detected
* `ruch_YYYY-MM-DD_HH-MM-SS.mp4` – general motion without identifying a subject

### 📁 Modular Architecture
The codebase is structured into clear, specialized modules:
* `config.py` – central configuration for resolution, FPS, detection thresholds, and paths
* `main.py` – main orchestrator connecting camera stream, detection, recording, and HTTP server
* `streamer.py` – hardware camera sensor control via `rpicam-vid` (NoIR profile)
* `detector.py` – lightweight, adaptive OpenCV MOG2 motion detection
* `ai_classifier.py` – asynchronous AI object classification (MobileNet-SSD: person / dog)
* `recorder.py` – hardware GPU H.264 video recorder (`v4l2m2m`)
* `storage.py` – storage space management on SD card and Samba sharing
* `web_server.py` – HTTP server, API routing, and raw CCTV monitoring web panel
* `camera_stream.py` – transparent systemd service entry point

---

## 🚀 Quick Installation on a Fresh System (1 Command)

If installing on a fresh Raspberry Pi OS install (Debian 12 Bookworm or Debian 13 Trixie), simply clone the repository and run the setup script:

```bash
git clone https://github.com/bejekk/house_camera.git ~/camera_domowa
cd ~/camera_domowa
chmod +x install.sh
./install.sh
```

The script will automatically:
1. Install all required system packages (`python3`, `python3-pil`, `python3-numpy`, `python3-opencv`, `ffmpeg`, `rpicam-apps`).
2. Create the `/home/$USER/recordings` directory.
3. Configure and start the `camera-stream.service` in systemd so monitoring starts on boot.

---

## 📦 Manual Installation (Step-by-step)

### 1. Required System Packages (APT)

On Raspberry Pi OS, installing Python libraries via `apt` is recommended (to adhere to PEP 668 externally managed environment protections):

```bash
sudo apt update
sudo apt install -y python3 python3-pil python3-numpy python3-opencv ffmpeg rpicam-apps samba
```

### 2. Python Requirements (`requirements.txt`)

If using a Python virtual environment (venv):

```bash
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
```

Contents of `requirements.txt`:
- `numpy>=1.24.0` – matrix operations for image frames
- `opencv-python-headless>=4.8.0` – MOG2 background subtraction and morphological filtering
- `Pillow>=10.0.0` – image processing support

### 3. Prepare Recordings Directory

```bash
mkdir -p ~/recordings
```

### 4. Run as a Background Service (Autostart)

Create `/etc/systemd/system/camera-stream.service`:

```ini
[Unit]
Description=Raspberry Pi Live Camera MJPEG Streamer
After=network.target

[Service]
Type=simple
User=bejek
WorkingDirectory=/home/bejek
ExecStart=/usr/bin/python3 /home/bejek/camera_stream.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Then enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-stream.service
sudo systemctl start camera-stream.service
```

### 5. Network Share for Recordings (Samba)

Append to `/etc/samba/smb.conf`:

```ini
[nagrania]
   comment = Nagrania CCTV Raspberry Pi
   path = /home/bejek/recordings
   browseable = yes
   read only = no
   guest ok = yes
   create mask = 0775
   directory mask = 0775
   force user = bejek
```

Restart Samba:
```bash
sudo systemctl restart smbd nmbd
```

Accessing recordings:
- **Windows (File Explorer):** `\\192.168.1.24\nagrania` (can be mapped as e.g. drive `Z:`)
- **Linux (File Manager):** `smb://192.168.1.24/nagrania`
- **Android (VLC / CX File Explorer):** add SMB share `192.168.1.24` (anonymous / guest)

---

## 🌐 Remote Access over the Internet (Tailscale - Optional)

For secure live streaming from a phone or laptop anywhere without a public IP or port forwarding:

1. Install Tailscale on the Raspberry Pi:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
2. Open the URL printed in the terminal and authenticate your account.
3. Install the Tailscale app on your phone/device and log into the same account.
4. Access the Raspberry Pi's Tailscale IP address in your browser (e.g., `http://100.92.76.100:8000`).

*Security Note:* Access to recorded video files (MP4 files) is automatically blocked outside the local home LAN (HTTP 403), preserving your privacy and bandwidth. Live streaming remains accessible everywhere.

---

## 🛠 Service Management

- **Check status:** `sudo systemctl status camera-stream.service`
- **Restart service:** `sudo systemctl restart camera-stream.service`
- **View live logs:** `sudo journalctl -u camera-stream.service -f`
