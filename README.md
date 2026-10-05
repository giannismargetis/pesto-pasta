# PESTO + PASTA

> 🇬🇷 **Τεκμηρίωση στα ελληνικά**: [docs/el/README.md](docs/el/README.md) · [Αρχιτεκτονική](docs/el/ARCHITECTURE.md) · [Αξιολόγηση](docs/el/EVALUATION.md) · [Πρωτόκολλο Μελέτης](docs/el/STUDY_PROTOCOL.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-lightgrey.svg)](https://microsoft.com/windows)
[![CUDA 12](https://img.shields.io/badge/CUDA-12.x%20ready-green.svg)](https://developer.nvidia.com/cuda-toolkit)
[![License MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![Latency p50](https://img.shields.io/badge/engine%20latency-450%20ms%20(p50)-success.svg)](#what-it-does-well-measured)

**PESTO** is a fully local, bilingual (Greek & English) push-to-talk speech input system for Windows: hold a key, speak, release, and the text appears instantly at the cursor.

**PASTA** extends it into a voice automation agent (*"Πάστα, άνοιξε το Chrome και ψάξε..."*): commands are parsed with a deterministic sub-millisecond grammar, grounded in the live desktop via Windows UI Automation, safety-gated, executed, and **verified**.

Both run **100% offline** on local GPU hardware after model caching. This repository also serves as the experimental research platform for a **CEID (University of Patras) HCI diploma thesis** on perceived latency and cognitive load in Greek voice typing.

---

## 🎬 60-Second Showcase

Experience **PESTO** (real-time Greek & English push-to-talk voice typing) and **PASTA** (local desktop voice commands and UI automation) in action:

<p align="center">
  <img src="docs/promo/PESTO_PASTA_showcase.gif" alt="PESTO + PASTA 60s Showcase" width="100%" style="border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
</p>

---

## 📸 Interface & Visual Walkthrough

### PESTO Push-to-Talk HUD (Non-Stealing Floating Overlay)

The non-focus heads-up display communicates state, voice amplitude, and latency milestones without stealing window focus:

| State | HUD Preview | Description |
|---|---|---|
| **Listening** | ![Listening HUD](docs/img/hud-listening.png) | Real-time audio waveform amplitude with live streaming preview and language indicators. |
| **Transcribing** | ![Transcribing HUD](docs/img/hud-transcribing.png) | Rotating progress arc driven by an asynchronous, non-blocking GPU ASR worker. |
| **Completed** | ![Done HUD](docs/img/hud-done.png) | Direct `SendInput` Unicode typing with verified latency badge (e.g. `286 ms`). |

### PASTA Voice Commands & Safety Gating

Commands are automatically routed to the PASTA desktop agent, parsed with a sub-millisecond deterministic grammar, and verified against the live Windows UI:

| Phase | HUD Preview | Description |
|---|---|---|
| **Executing** | ![Command Running](docs/img/hud-command-running.png) | Multi-step task plan grounded in active windows, installed apps, and browser targets. |
| **Safety Confirmation** | ![Safety Confirm](docs/img/hud-command-confirm.png) | Interactive confirmation gate for sensitive actions (`Enter` to confirm, `Esc` to abort). |
| **Verified Outcome** | ![Command Done](docs/img/hud-command-done.png) | Completed action report with observed system outcome and total execution time. |

### Control & Telemetry Dashboard

Access the full diagnostic suite, latency distributions, and audio device configuration from the system tray:

| Overview & Activity | Latency Timeline & History |
|:---:|:---:|
| ![Dashboard Overview](docs/img/dashboard-overview.png) | ![Dashboard History](docs/img/dashboard-history.png) |
| **Hardware Health & Diagnostics** | **Audio Input & Device Selection** |
| ![Dashboard Diagnostics](docs/img/dashboard-diagnostics.png) | ![Dashboard Settings](docs/img/dashboard-settings.png) |

---

## ⚡ Measured Benchmarks & Empirical Claims

All claims are backed by reproducible evaluations on the **FLEURS test sets** (200 Greek + 200 English utterances, fixed seed `20261004`, NVIDIA RTX 3050 8 GB, Windows 10/11). Detailed methodology: [`docs/ENGINEERING_LOG.md`](docs/ENGINEERING_LOG.md) and [`docs/EVALUATION.md`](docs/EVALUATION.md).

### 1. Speech Recognition Accuracy (WER / CER)

| Engine / Configuration | Greek WER | English WER | Greek CER | Latency (p50) |
|---|---|---|---|---|
| **Baseline (v2)** *(auto LID, beam 2, Greek prompt)* | 12.61% [11.1–14.3] | **51.02%** *(prompt contamination)* | 4.91% | 804 ms |
| **PESTO v3 Whisper (beam 1)** | 13.09% | 5.54% | 5.11% | 410 ms |
| **PESTO v3 Whisper (beam 2, default)** | **12.28% [10.8–14.1]** | **5.52%** | **4.57%** | **450 ms** |
| **NVIDIA Parakeet TDT 0.6B (CUDA)** | 34.88% *(no final ς)* | **5.96%** | 11.30% | **124 ms** |

> ℹ️ **Note on Greek Parakeet**: While Parakeet delivers ultra-fast 124 ms English transcription, it **lacks the Greek final sigma (ς)** in its vocabulary (17.7% of Greek words end in ς), resulting in 34.88% Greek WER. **Whisper Large-v3-Turbo is the recommended bilingual default.**

### 2. Latency Optimization (ABBA Paired Testing)

Tested on 100 paired clips (50 EL + 50 EN, Wilcoxon $p < 10^{-15}$):

* **3 s Utterance (typical PTT)**: Engine latency dropped from **804 ms → 450 ms** (median reduction: **−351 ms [−357, −346]**).
* **~10 s Utterance**: Dropped from **990 ms / 1332 ms (p50 / p95) → 562 ms / 879 ms**.
* **Cold Start (Process Launch → First Text Ready)**: Reduced from **8.1 s → 4.4 s** by eliminating PyTorch runtime loading (`pesto/cuda.py`).
* **VAD Speech Gate (Silero VAD)**: Takes **~4 ms** on 3 s audio, discarding accidental empty key presses before touching the heavy GPU ASR worker.

### 3. PASTA Natural Language Understanding & Safety

Evaluated across 201 annotated utterances (held-out commands, out-of-scope utterances, and adversarial dictation traps):

* **Held-out Greek Commands**: **97.5%** exact intent match on first unseen run (**100%** post-hoc).
* **Held-out English Commands**: **85.0%** exact intent match (**100%** post-hoc).
* **Grammar Parse Time**: **<0.1 ms** (0.06 ms median) vs 2–3 seconds for local LLMs.
* **Dictation Traps**: **0%** false command triggers out of 30 adversarial dictation sentences.
* **Safety Verification**: 3-tier gating (`auto`, `confirm`, `refuse`) with live window verification (`verified`, `unverified`, `failed`).

---

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/giannismargetis/pasta.git
cd pasta

# Automated environment setup (virtualenv, dependencies, model download, doctor check)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Or download the standalone Windows installer: **`dist\PASTA-Setup-3.0.0.exe`** (built with Inno Setup 6).

### Running

```bash
PESTO.bat            # Dictation only
PASTA.bat            # Dictation + Voice Commands
python -m pesto doctor   # Hardware, CUDA, and microphone verification
```

### Controls & Keybindings

| Action | Default Shortcut | Behavior |
|---|---|---|
| **Dictate (PESTO)** | Hold **Right Ctrl** (≥150 ms) | Speak, release to type at cursor. Quick taps act as normal Ctrl shortcuts. |
| **Command (PASTA)** | Hold **Right Ctrl** | Start with **“Pasta,”** or **“Πάστα,”** (e.g. *«Πάστα, άνοιξε το Spotify»*). |
| **Cancel Recording** | **Esc** | Aborts current recording or in-flight command. |
| **Confirm Action** | **Enter** (or say *“yes” / “ναι”*) | Approves a safety-gated command prompt. |
| **Cycle Language** | **Ctrl+Alt+Shift+L** | Toggles between Auto, Greek (`el`), and English (`en`). |
| **Cycle ASR Engine** | **Ctrl+Alt+Shift+E** | Toggles between Whisper Large-v3-Turbo and Parakeet TDT. |
| **Cycle Mode** | **Ctrl+Alt+Shift+M** | Toggles between Dictation only and Voice Command mode. |

---

## 🏛️ System Architecture

```
pesto/                 Core Voice Input Layer
  hotkeys.py           Low-level Win32 keyboard hook (WH_KEYBOARD_LL, virtual-key codes)
  audio.py             Continuous ring-buffer audio stream with 300 ms pre-roll
  session.py           VoiceSession coordinator & single GPU-owning worker thread
  asr/                 Engines: Whisper Large-v3-Turbo, Parakeet TDT, Silero VAD gate
  inject.py            Direct Unicode text typing via Windows SendInput (clipboard untouched)
  telemetry.py         High-precision SQLite WAL latency recorder
  ui/                  PyQt6 non-stealing HUD, system tray icon, and Dashboard

pasta/                 Extension: Voice Commands & Desktop Automation
  router.py            Wake-word discrimination boundary (dictation vs command)
  nlu/grammar.py       Deterministic bilingual grammar (<0.1 ms parse time)
  intents.py           Finite, typed action catalog (app, window, browser, volume, text)
  planner.py           Grounding against active desktop windows and installed apps
  safety.py            3-tier policy: auto / confirm / refuse
  executors.py         Execution handlers with verified / unverified / failed outcome tracking
  world/               Desktop observation (Windows UI Automation, audio, shell)

research/              Scientific Evaluation & Study Platform
  asr_eval.py          Automated FLEURS evaluation harness (WER, CER, confidence intervals)
  latency_ab.py        Paired ABBA engine latency measurement harness
  study/               HCI human-subjects study runner (NASA-TLX, Latin Square, WPM)
```

---

## 🔬 Reproducing the Thesis Research

To reproduce the benchmark figures reported in the thesis:

```bash
# 1. Download FLEURS evaluation dataset (~640 MB, CC-BY-4.0)
python research/data/fetch_fleurs.py

# 2. Run Whisper evaluation on Greek manifest
python -m research.asr_eval --engine whisper --manifest research/data/manifests/fleurs_el_200.jsonl --tag thesis-eval

# 3. Run Paired ABBA Latency Benchmark
python -m research.latency_ab --a baseline --b current --n 50 --tag latency-ab

# 4. Run PASTA NLU Grammar Benchmark
python -m pasta.eval.nlu

# 5. Launch the HCI Study Runner
python -m research.study plan --protocol input_modality --participant P01
```

---

## 🔒 Privacy & Security

* **Zero Cloud Dependence**: Audio never leaves the local machine. Once models are cached locally, the entire application operates strictly offline.
* **Clipboard Integrity**: Dictated text is injected directly using Windows `SendInput` Unicode events. The Windows clipboard is neither used nor overwritten, preventing data leakage into cloud-synced clipboard managers.
* **Local Telemetry**: All latency timestamps and interaction records are stored in a local SQLite file (`data/pesto.db`) that the user can inspect or purge at any time.

---

## 📜 Citation & Academic Context

This project is developed as part of a Diploma Thesis at the **Department of Computer Engineering and Informatics (CEID), University of Patras**:

* **Thesis Title**: *Perceived Latency and Cognitive Load in Push-to-Talk Greek Speech Input: A Comparative Study with Traditional Keyboard in an Academic Environment*
* **Author**: Giannis Margetis
* **Institution**: University of Patras, School of Engineering, CEID
