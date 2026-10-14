#!/usr/bin/env bash
# ==============================================================================
# Skrypt automatycznej instalacji i uruchomienia monitoringu na nowym Raspberry Pi
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="${SUDO_USER:-$USER}"
USER_HOME=$(eval echo "~$CURRENT_USER")

echo "========================================================"
echo " Instalacja systemu monitoringu CCTV (Raspberry Pi)"
echo " Użytkownik: $CURRENT_USER | Katalog: $SCRIPT_DIR"
echo "========================================================"

# 1. Aktualizacja repozytoriów i instalacja pakietów systemowych
echo "[1/4] Instalacja wymaganych pakietów systemowych (APT)..."
sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-pil \
    python3-numpy \
    python3-opencv \
    ffmpeg \
    rpicam-apps \
    samba

# 2. Utworzenie katalogu na nagrania
echo "[2/5] Przygotowanie katalogu na nagrania wideo..."
RECORDINGS_DIR="$USER_HOME/recordings"
mkdir -p "$RECORDINGS_DIR"
chown -R "$CURRENT_USER:$CURRENT_USER" "$RECORDINGS_DIR"

# 3. Pobranie wag modelu AI (MobileNet-SSD: człowiek / pies)
echo "[3/5] Przygotowanie modelu sieci neuronowej AI (człowiek / pies)..."
MODELS_DIR="$USER_HOME/models"
mkdir -p "$MODELS_DIR"
if [ ! -f "$MODELS_DIR/MobileNetSSD_deploy.prototxt" ]; then
    curl -sSL -o "$MODELS_DIR/MobileNetSSD_deploy.prototxt" https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt
fi
if [ ! -f "$MODELS_DIR/MobileNetSSD_deploy.caffemodel" ]; then
    curl -sSL -o "$MODELS_DIR/MobileNetSSD_deploy.caffemodel" https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/mobilenet_iter_73000.caffemodel
fi
chown -R "$CURRENT_USER:$CURRENT_USER" "$MODELS_DIR"

# 4. Konfiguracja usługi systemowej (systemd)
echo "[4/5] Konfiguracja automatycznego startu (systemd)..."
SERVICE_FILE="/etc/systemd/system/camera-stream.service"

sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=Raspberry Pi Live Camera MJPEG Streamer
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$USER_HOME
ExecStart=/usr/bin/python3 $USER_HOME/camera_stream.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable camera-stream.service
sudo systemctl restart camera-stream.service

# 4. Konfiguracja dysku sieciowego (Samba - tylko sieć lokalna LAN)
echo "[4/5] Konfiguracja dysku sieciowego Samba..."
if ! grep -q "bind interfaces only = yes" /etc/samba/smb.conf 2>/dev/null; then
    sudo sed -i 's/;   interfaces = 127.0.0.0\/8 eth0/   interfaces = 127.0.0.0\/8 192.168.1.0\/24 wlan0 eth0/' /etc/samba/smb.conf || true
    sudo sed -i 's/;   bind interfaces only = yes/   bind interfaces only = yes/' /etc/samba/smb.conf || true
fi
if ! grep -q "\[nagrania\]" /etc/samba/smb.conf 2>/dev/null; then
    sudo bash -c "cat <<EOF >> /etc/samba/smb.conf

[nagrania]
   comment = Nagrania CCTV Raspberry Pi
   path = $RECORDINGS_DIR
   browseable = yes
   read only = no
   guest ok = yes
   create mask = 0775
   directory mask = 0775
   force user = $CURRENT_USER
   hosts allow = 192.168.1. 127.
   hosts deny = 0.0.0.0/0
EOF"
fi
sudo systemctl enable smbd nmbd
sudo systemctl restart smbd nmbd

# 5. Podsumowanie
IP_LOCAL=$(hostname -I | awk '{print $1}')
echo "========================================================"
echo " Instalacja zakończona sukcesem!"
echo "========================================================"
echo "Usługa 'camera-stream.service' została uruchomiona."
echo ""
echo "Dostęp do panelu podglądu:"
echo "  Lokalnie w sieci LAN: http://${IP_LOCAL:-192.168.1.X}:8000"
echo ""
echo "Dysk sieciowy z nagraniami (Samba):"
echo "  Windows:  \\\\${IP_LOCAL:-192.168.1.X}\\nagrania"
echo "  Linux:    smb://${IP_LOCAL:-192.168.1.X}/nagrania"
echo "  Android:  192.168.1.X -> nagrania (gość / bez hasła)"
echo ""
echo "Przydatne polecenia:"
echo "  Status kamery:   sudo systemctl status camera-stream.service"
echo "  Status dysku:    sudo systemctl status smbd"
echo "  Restart kamery:  sudo systemctl restart camera-stream.service"
echo "  Logi na żywo:    sudo journalctl -u camera-stream.service -f"
echo "========================================================"
