#!/usr/bin/env python3
import json
import os
import ipaddress
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from config import RECORDINGS_DIR

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
            <span>Format: <b>1280x960 @ 15 FPS</b></span>
            <span>Algorytm: <b>MOG2 + MobileNet-SSD</b></span>
            <span>Zapis: <b id="footer-rec-badge">H.264 MP4 (GPU V4L2 M2M)</b></span>
            <span>Dysk sieciowy: <b>\\192.168.1.24\nagrania</b></span>
            <span>Sensor: <b>Sony IMX219 NoIR (profil NoIR)</b></span>
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

ctx = {
    "streamer": None,
    "detector": None,
    "recorder": None,
    "storage": None
}

def init_web_context(streamer, detector, recorder, storage):
    ctx["streamer"] = streamer
    ctx["detector"] = detector
    ctx["recorder"] = recorder
    ctx["storage"] = storage

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

def serve_range_file(handler, filepath, content_type):
    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        handler.send_error(404)
        return

    range_header = handler.headers.get("Range")
    if not range_header:
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(file_size))
        handler.send_header("Accept-Ranges", "bytes")
        handler.end_headers()
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(65536):
                    handler.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return

    try:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        if end >= file_size:
            end = file_size - 1
        length = end - start + 1

        handler.send_response(206)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        handler.send_header("Content-Length", str(length))
        handler.send_header("Accept-Ranges", "bytes")
        handler.end_headers()

        with open(filepath, "rb") as f:
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
        streamer = ctx["streamer"]
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
        elif parsed.path == "/snapshot.jpg":
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
        elif parsed.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
        elif parsed.path.startswith("/video/"):
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            fname = parsed.path[len("/video/"):]
            fpath = os.path.join(RECORDINGS_DIR, fname)
            if os.path.exists(fpath) and fname.endswith(".mp4"):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(os.path.getsize(fpath)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_GET(self):
        streamer = ctx["streamer"]
        detector = ctx["detector"]
        recorder = ctx["recorder"]
        storage = ctx["storage"]

        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            content = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif parsed.path == "/stream.mjpg":
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            try:
                while True:
                    frame = streamer.get_frame() if streamer else None
                    if frame is None:
                        continue
                    self.wfile.write(b"--FRAME\r\n")
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (ConnectionResetError, BrokenPipeError):
                pass
        elif parsed.path == "/snapshot.jpg":
            frame = streamer.frame if streamer else None
            if frame:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_error(503, "Camera warming up")
        elif parsed.path == "/status":
            status = detector.get_status() if detector else {}
            status["is_local"] = self.is_local_client()
            data = json.dumps(status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/api/storage":
            is_rec = recorder.is_recording if recorder else False
            rec_enabled = recorder.recording_enabled if recorder else False
            info = storage.get_disk_info(is_recording=is_rec) if storage else {}
            info["is_local"] = self.is_local_client()
            info["recording_enabled"] = rec_enabled
            data = json.dumps(info).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/api/recordings":
            if not self.is_local_client():
                data = json.dumps({"error": "forbidden", "is_local": False, "message": "Nagrania wideo są dostępne wyłącznie w sieci lokalnej (LAN)"}).encode("utf-8")
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            recs = storage.list_recordings() if storage else []
            data = json.dumps(recs).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path.startswith("/video/"):
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            filename = parsed.path[len("/video/"):]
            filepath = os.path.join(RECORDINGS_DIR, filename)
            if os.path.exists(filepath) and filename.endswith(".mp4"):
                serve_range_file(self, filepath, "video/mp4")
            else:
                self.send_error(404, "Video not found")
        elif parsed.path == "/api/delete_recording":
            if not self.is_local_client():
                self.send_error(403, "Forbidden")
                return
            query = parse_qs(parsed.query)
            fname = query.get("file", [""])[0]
            ok = storage.delete_recording(fname) if storage else False
            data = json.dumps({"status": "ok" if ok else "error"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/toggle_recording":
            query = parse_qs(parsed.query)
            if recorder:
                if "enabled" in query:
                    val = query["enabled"][0].lower()
                    enabled = val in ("1", "true", "yes", "on")
                else:
                    enabled = not recorder.recording_enabled
                recorder.set_recording_enabled(enabled)
                rec_enabled = recorder.recording_enabled
                is_rec = recorder.is_recording
            else:
                rec_enabled = False
                is_rec = False
            data = json.dumps({
                "status": "ok",
                "recording_enabled": rec_enabled,
                "is_recording": is_rec
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/set_mode":
            query = parse_qs(parsed.query)
            mode = "auto"
            if detector and "mode" in query:
                detector.set_mode(query["mode"][0])
                mode = detector.mode
            data = json.dumps({"status": "ok", "mode": mode}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/set_auto_bias":
            query = parse_qs(parsed.query)
            bias = "normal"
            if detector and "bias" in query:
                detector.set_auto_bias(query["bias"][0])
                bias = detector.auto_bias
            data = json.dumps({"status": "ok", "auto_bias": bias}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/set_threshold":
            query = parse_qs(parsed.query)
            thresh = 1.0
            if detector and "val" in query:
                detector.set_manual_threshold(query["val"][0])
                thresh = detector.effective_threshold
            data = json.dumps({"status": "ok", "threshold": thresh}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/set_dark_guard":
            query = parse_qs(parsed.query)
            guard = True
            if detector and "val" in query:
                val = query["val"][0].lower()
                enabled = val in ("1", "true", "yes", "on")
                detector.set_ignore_in_dark(enabled)
                guard = detector.ignore_in_dark
            data = json.dumps({"status": "ok", "ignore_in_dark": guard}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/set_dark_threshold":
            query = parse_qs(parsed.query)
            dark_thresh = 12.0
            if detector and "val" in query:
                detector.set_darkness_threshold(query["val"][0])
                dark_thresh = detector.darkness_threshold
            data = json.dumps({"status": "ok", "darkness_threshold": dark_thresh}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)
