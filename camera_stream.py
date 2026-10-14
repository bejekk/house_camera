#!/usr/bin/env python3
"""
System Monitoringu CCTV na Raspberry Pi
Główny punkt wejściowy (kompatybilny z usługą systemd camera-stream.service).
Architektura została rozdzielona na wyspecjalizowane moduły:
 - config.py: konfiguracja parametrów kamery, sieci i AI
 - storage.py: zarządzanie dyskiem i nagraniami Samba
 - streamer.py: obsługa sprzętowa sensora kamery (rpicam-vid)
 - detector.py: algorytm detekcji ruchu OpenCV MOG2
 - ai_classifier.py: sieć neuronowa MobileNet-SSD (człowiek / pies)
 - recorder.py: asynchroniczny rejestrator wideo H.264 MP4
 - web_server.py: serwer HTTP i panel WWW
 - main.py: orkiestracja komponentów
"""
from main import main

if __name__ == '__main__':
    main()
