# 🍝 PASTA V2: Practical Agent for Speech-Triggered Automation

> **Voice-to-Computer Control & Instant Dictation — 100% Local, Bilingual (Greek & English), Zero Cloud Dependencies.**

PASTA V2 elevates local voice typing into a full desktop and browser automation agent. Built directly on top of the battle-tested **Pesto** voice typing foundation, PASTA seamlessly preserves instant bilingual push-to-talk dictation while adding **Agent Mode** — empowering you to command your Windows OS, applications, and web browser naturally by voice.

---

## ⚡ Key Highlights

- **Dual-Mode System**:
  - 🟢 **Voice Mode (`PASTA • VOICE`)**: Ultra-fast push-to-talk bilingual dictation directly into any Windows foreground window.
  - 🔵 **Agent Mode (`PASTA • AGENT`)**: Autonomous computer control triggered by wake prefixes (`"Pasta,"`, `"Computer,"`, `"Πάστα,"`) or imperative commands.
- **Finite Action Space with Decider-2B**:
  - Instead of unconstrained free-form token generation, PASTA inspects your live desktop state, generates 5–15 valid typed candidate actions, and scores them using the **Decider-2B** architecture.
- **20 Real Desktop & Browser Capabilities**:
  - Windows app launching, window switching, minimizing, restoring, and closing.
  - Full Playwright-powered browser automation: search the web, open URLs, create/close tabs, history back, click selectors, fill inputs, and extract text.
  - Keyboard automation (copy, paste, enter, hotkeys), scrolling, volume muting, and allowlisted terminal commands (`git status`, `python --version`, etc.).
- **Dual Speech Engines**:
  - **Whisper large-v3-turbo** (CTranslate2, CUDA accelerated) for bilingual Greek/English dictation.
  - **Parakeet TDT 0.6B v3** (ONNX Runtime, CUDA) for lightning-fast English speech-to-text.
- **Safety First**:
  - Three-tier confidence gating (`>= 0.70` auto-execute, `0.50–0.70` confirmation required, `< 0.50` abstains).
  - Destructive action confirmation and configurable permission flags.
  - Instant cancellation with the **`Esc`** key.
- **Dual-Mode HUD**:
  - Floating, frameless Tkinter overlay that switches dynamically between emerald audio waveform (Voice Mode) and electric sapphire action telemetry (Agent Mode).
- **Comprehensive Benchmarks**:
  - 56-task benchmark suite achieving **100% Routing Accuracy**, **100% Candidate Coverage**, and **100% Decision Accuracy**.

---

## 🏗️ Architecture Overview

```
                      [ Microphone Input ]
                               │ (Right Ctrl Hold)
                               ▼
                    [ Audio Capture Thread ]
                               │
                               ▼
               [ Speech-to-Text Engine ]
              (Whisper large-v3-turbo / Parakeet)
                               │
                               ▼
                       [ CommandRouter ]
                       (< 1ms latency)
                        /             \
                       /               \
         (Normal Dictation)         (Agent Command)
                     ▼                         ▼
            [ Win32 Injection ]         [ AgentLoop ]
         (Active Foreground App)               │
                                               ▼
                                      [ State Observer ]
                                  (Win32 / UIA / Playwright)
                                               │
                                               ▼
                                     [ Candidate Builder ]
                                      (5-15 Typed Actions)
                                               │
                                               ▼
                                       [ Decider Model ]
                                     (GPU / GGUF / Heuristic)
                                               │
                                               ▼
                                        [ Safety Gate ]
                                     (Threshold & Perms)
                                               │
                                               ▼
                                     [ Action Execution ]
                                   (App / Browser / Shell)
                                               │
                                               ▼
                                    [ Action Verifier ]
                                 (PID, Title, URL, Clipboard)
                                               │
                                               ▼
                                        [ SQLite Audit ]
```

---

## 🚀 Quick Start

### 1. Requirements
- Windows 10 or 11 (64-bit)
- Python 3.11+ (Python 3.13 tested)
- NVIDIA GPU with CUDA support recommended (e.g. RTX 3050+)
- Shared Python virtual environment with Pesto (`t:\My Apps\voice-typer\venv`)

### 2. Launching PASTA
Simply run the root launch script:
```powershell
.\PASTA.bat
```
Or launch via Python:
```powershell
& "..\voice-typer\venv\Scripts\python.exe" -m pasta
```

### 3. CLI Options
```
usage: python -m pasta [-h] [--engine {whisper,parakeet}] [--language {el,en}]
                       [--agent-mode {on,off}] [--no-gui] [--benchmark]

options:
  -h, --help            show this help message and exit
  --engine {whisper,parakeet}
                        Speech recognition engine
  --language {el,en}    Default dictation language
  --agent-mode {on,off} Enable or disable agent computer control
  --no-gui              Run headless without floating HUD
  --benchmark           Run the 56-task benchmark suite
```

---

## 🎙️ How to Use

### Normal Dictation (Voice Mode)
1. Hold **Right Ctrl** (or your configured push-to-talk key).
2. Speak naturally in Greek or English (e.g., *"Καλημέρα, επισυνάπτω την αναφορά της διπλωματικής μου."*).
3. Release **Right Ctrl**.
4. The text is immediately typed into your active window.

### Computer Control (Agent Mode)
Hold **Right Ctrl**, speak a command starting with **"Pasta"**, **"Πάστα"**, **"Computer"**, or a direct imperative, and release:

| Voice Command | Action Executed |
| :--- | :--- |
| *"Pasta, open Chrome and search for RTX 5090 prices."* | Launches Chrome and executes web search |
| *"Πάστα, άνοιξε το Calculator."* | Launches Windows Calculator |
| *"Pasta, switch to VS Code."* | Brings Visual Studio Code to the foreground |
| *"Pasta, open Downloads."* | Opens your Windows Downloads folder |
| *"Πάστα, βρες το PDF μου."* | Searches your user directory for the PDF and opens it |
| *"Pasta, create a new browser tab and open github.com."* | Opens a new Playwright tab and navigates to GitHub |
| *"Pasta, run git status in the terminal."* | Runs safe git status and captures output |
| *"Πάστα, πάτα Enter."* | Simulates the Enter key press |
| *"Pasta, mute sound."* | Toggles computer master volume mute |
| *"Pasta, stop."* or pressing **`Esc`** | Immediately aborts the current agent task |

---

## 📊 Benchmark Results

PASTA includes a built-in deterministic benchmark suite (`benchmark/run_benchmark.py`) covering 56 diverse tasks across 7 categories:

```
====================================================================
                       BENCHMARK RESULTS
====================================================================
Total Benchmark Tasks:             56
Intent Routing Accuracy:           100.0% (56/56)
Candidate Generation Coverage:     100.0% (52/52)
Decider Top-1 Accuracy:            100.0% (52/52)
Average Decision Latency:          104.66 ms
p50 Decision Latency:              0.02 ms
p95 Decision Latency:              0.07 ms
====================================================================
```

To run the benchmark suite at any time:
```powershell
& "..\voice-typer\venv\Scripts\python.exe" -m benchmark.run_benchmark
```

---

## 🧪 Automated Testing

PASTA comes with a full test suite covering all modules:
```powershell
& "..\voice-typer\venv\Scripts\python.exe" -m pytest tests/ -v
```
**Test Results**: 39 passed in 1.08s (100% pass rate).

---

## ⚙️ Configuration (`config.json`)

```json
{
  "general": {
    "engine": "whisper",
    "language": "el"
  },
  "agent": {
    "enabled": true,
    "model": "Mapika/decider-2b",
    "runtime": "gpu",
    "auto_execute_threshold": 0.70,
    "confirm_threshold": 0.50,
    "max_steps": 5,
    "timeout_seconds": 15.0
  },
  "permissions": {
    "allow_app_launch": true,
    "allow_window_control": true,
    "allow_browser_automation": true,
    "allow_shell_commands": true,
    "allow_file_system": true,
    "require_confirmation_for_destructive": true
  }
}
```

---

## 📜 License & Attribution

PASTA V2 is developed locally for privacy-preserving, high-speed desktop voice automation. Reuses core STT audio pipelines and settings from Pesto.
