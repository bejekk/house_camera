# System Monitoringu CCTV na Raspberry Pi

Lekki, samodzielny system monitoringu domowego z podglądem na żywo, detekcją ruchu OpenCV MOG2, inteligentną klasyfikacją obiektów AI (człowiek / pies / ruch) przez MobileNet-SSD, bezpośrednim zapisem wideo MP4 (H.264, maks. 2 min) na dysk sieciowy Samba i panelem webowym CCTV.

### 🧠 Inteligentna klasyfikacja nagrań (AI)
System po wykryciu ruchu analizuje klatki w tle siecią neuronową MobileNet-SSD z odpornym algorytmem głosowania wieloklatkowego (eliminacja fałszywych alarmów) i automatycznie nazywa pliki wideo:
* `czlowiek_pies_YYYY-MM-DD_HH-MM-SS.mp4` – gdy w kadrze znajdował się zarówno człowiek, jak i pies
* `czlowiek_YYYY-MM-DD_HH-MM-SS.mp4` – gdy wykryto człowieka
* `pies_YYYY-MM-DD_HH-MM-SS.mp4` – gdy wykryto psa / czworonoga domowego
* `ruch_YYYY-MM-DD_HH-MM-SS.mp4` – ogólny ruch bez identyfikacji postaci

### 📁 Architektura modułowa
Kod został podzielony na czytelne, wyspecjalizowane moduły:
* `config.py` – centralna konfiguracja rozdzielczości, FPS, progów detekcji i ścieżek
* `main.py` – główny orkiestrator spinający strumień, detekcję, zapis i serwer WWW
* `streamer.py` – sprzętowa obsługa sensora kamery przez `rpicam-vid` (profil NoIR)
* `detector.py` – lekka, adaptacyjna detekcja ruchu OpenCV MOG2
* `ai_classifier.py` – asynchroniczna klasyfikacja obiektów AI (MobileNet-SSD: człowiek / pies)
* `recorder.py` – rejestrator nagrań sprzętowym enkoderem GPU H.264 (v4l2m2m)
* `storage.py` – zarządzanie przestrzenią na karcie SD i udostępnianiem Samba
* `web_server.py` – serwer HTTP, routing API i surowy panel podglądu CCTV
* `camera_stream.py` – przezroczysty punkt startowy zgodny z usługą systemd

---

## 🚀 Szybka instalacja na nowym systemie (1 polecenie)

Jeśli instalujesz system na nowo postawionym Raspberry Pi OS (Debian 12 Bookworm lub Debian 13 Trixie), wystarczy sklonować repozytorium i uruchomić skrypt instalacyjny:

```bash
git clone https://github.com/bejekk/house_camera.git ~/camera_domowa
cd ~/camera_domowa
chmod +x install.sh
./install.sh
```

Skrypt automatycznie:
1. Zainstaluje wszystkie wymagane pakiety systemowe (`python3`, `python3-pil`, `python3-numpy`, `python3-opencv`, `ffmpeg`, `rpicam-apps`).
2. Utworzy katalog `/home/$USER/recordings`.
3. Skonfiguruje i uruchomi usługę `camera-stream.service` w systemd, aby monitoring startował automatycznie przy każdym włączeniu Raspberry Pi.

---

## 📦 Instalacja ręczna (krok po kroku)

### 1. Wymagane pakiety systemowe (APT)

Na Raspberry Pi OS zaleca się instalację bibliotek Python przez `apt` (ponieważ system chroni globalne środowisko przed instalacją pipem):

```bash
sudo apt update
sudo apt install -y python3 python3-pil python3-numpy python3-opencv ffmpeg rpicam-apps samba
```

### 2. Wymagania Python (`requirements.txt`)

Jeśli wolisz korzystać ze środowiska wirtualnego Python (venv):

```bash
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
```

Zawartość `requirements.txt`:
- `numpy>=1.24.0` – obliczenia macierzowe dla klatek obrazu
- `opencv-python-headless>=4.8.0` – algorytm detekcji tła i ruchu MOG2 oraz filtracja morfologiczna
- `Pillow>=10.0.0` – obsługa formatów graficznych

### 3. Przygotowanie katalogu na nagrania

```bash
mkdir -p ~/recordings
```

### 4. Uruchomienie jako usługa w tle (autostart)

Utwórz plik `/etc/systemd/system/camera-stream.service`:

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

Następnie aktywuj usługę:

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-stream.service
sudo systemctl start camera-stream.service
```

### 5. Udostępnienie nagrań jako dysk sieciowy (Samba)

Dodaj na końcu pliku `/etc/samba/smb.conf`:

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

Następnie zrestartuj Sambę:
```bash
sudo systemctl restart smbd nmbd
```

Dostęp do nagrań:
- **Windows (Eksplorator plików):** `\\192.168.1.24\nagrania` (można zamapować jako dysk np. `Z:`)
- **Linux (Menedżer plików):** `smb://192.168.1.24/nagrania`
- **Android (VLC / CX File Explorer):** dodaj lokalizację sieciową SMB `192.168.1.24` (użytkownik anonimowy / gość)

---

## 🌐 Dostęp zdalny z internetu (Tailscale - opcjonalnie)

Aby mieć bezpieczny podgląd na żywo z telefonu lub laptopa z dowolnego miejsca bez publicznego IP i bez przekierowywania portów:

1. Zainstaluj Tailscale na Raspberry Pi:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
2. Otwórz podany w terminalu link i zaloguj się na swoje konto.
3. Zainstaluj aplikację Tailscale na telefonie i zaloguj się na to samo konto.
4. Otwórz w przeglądarce telefonu adres IP Raspberry Pi z Tailscale (np. `http://100.92.76.100:8000`).

*Uwaga bezpieczeństwa:* Dostęp do nagrań wideo (plików MP4) jest automatycznie zablokowany poza domową siecią LAN (HTTP 403), chroniąc Twoją prywatność i pakiet danych. Podgląd na żywo działa wszędzie.

---

## 🛠 Zarządzanie usługą

- **Sprawdzenie statusu:** `sudo systemctl status camera-stream.service`
- **Restart usługi:** `sudo systemctl restart camera-stream.service`
- **Podgląd logów w czasie rzeczywistym:** `sudo journalctl -u camera-stream.service -f`
