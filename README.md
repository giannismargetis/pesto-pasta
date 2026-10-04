# PESTO + PASTA

**PESTO** is fully local, bilingual (Greek/English) push-to-talk speech input for
Windows: hold a key, speak, release, and the text appears wherever the cursor is.
**PASTA** extends it with voice commands ("Πάστα, άνοιξε το Chrome και ψάξε …")
that are parsed, grounded in the live desktop, safety-gated, executed and
**verified**.

Both run entirely offline after the first model download. The repository is also
the research platform for a CEID (University of Patras) HCI diploma thesis on
perceived latency and cognitive load in Greek speech input; every claim below is
backed by a reproducible measurement in `research/results/`.

```
hold Right Ctrl → speak → release → text appears             (PESTO)
"Πάστα, …" → understand → ground → gate → act → verify        (PASTA)
```

## Quick start

```bash
PESTO.bat            # dictation only
PASTA.bat            # dictation + voice commands
python -m pesto doctor   # check GPU, CUDA libraries, models, microphone
```

| Action | Default |
|---|---|
| Dictate | hold **Right Ctrl** (≥150 ms), speak, release |
| Command (PASTA) | start with **“Pasta,” / “Πάστα,”** |
| Cancel recording or command | **Esc** |
| Confirm a command that asks | **Enter** (or say “ναι” / “yes”) |
| Cycle language / engine / mode | Ctrl+Alt+Shift+L / E / M |

Quick, Right-Ctrl-based shortcuts (e.g. Right Ctrl+C) are recognised as shortcuts and
never start a dictation.

## What it does well (measured)

All numbers: FLEURS test sets, 200 Greek + 200 English utterances, RTX 3050.
Method and caveats: [`docs/ENGINEERING_LOG.md`](docs/ENGINEERING_LOG.md).

| | Original (v2) | Now |
|---|---|---|
| English WER, automatic language | **51.0 %** (Greek prompt garbled English) | **5.5 %** |
| Greek WER | 12.6 % | 12.3 % (equivalent, Δ −0.3 pp [−1.0, +0.4]) |
| Engine latency, 3 s utterance (p50) | 804 ms | **450 ms** |
| Engine latency, ~10 s utterance (p50 / p95) | 990 / 1332 ms | **562 / 879 ms** |
| Process start → first text | 8.1 s | **4.4 s** |
| Parakeet on GPU, English (WER / p50) | 9.5 % / 860 ms (CPU) | **6.0 % / 124 ms** |
| Commands understood (held-out, first run) | — | EL 97.5 %, EN 85 % |
| Dictation wrongly executed as a command | imperative sentences were | 0 % of 30 adversarial sentences |

Parakeet TDT 0.6B is available as a fast English engine, but it **cannot write the
Greek final sigma (ς)** — it is absent from its vocabulary — and its Greek WER is
42.8 %. Whisper large-v3-turbo is the default.

## Architecture

```
pesto/                 core: voice input layer
  hotkeys.py           low-level keyboard hook (virtual-key codes), PTT state machine
  audio.py             always-open stream + 300 ms pre-roll
  session.py           pipeline, single GPU-owning ASR worker, latency timeline
  asr/                 Whisper (single encoder pass, el/en LID), Parakeet, Silero VAD
  inject.py            SendInput Unicode typing (clipboard untouched)
  telemetry.py         SQLite: interactions, agent runs, study trials, questionnaires
  ui/                  Qt HUD, tray, dashboard
pasta/                 extension: voice commands
  router.py            dictation vs command boundary (wake word rules)
  nlu/grammar.py       deterministic bilingual grammar  (+ optional Ollama fallback)
  intents.py           the finite, typed action space
  planner.py           grounding against live windows / installed apps
  safety.py            auto / confirm / refuse
  executors.py         actions with verified / failed / unverified outcomes
research/              evaluation harnesses, metrics, manifests, results
```

PASTA plugs into PESTO as a transcript handler; PESTO never imports PASTA.

## Reproducing the evaluation

```bash
python research/data/fetch_fleurs.py                       # ~640 MB, CC-BY-4.0
python -m research.asr_eval --engine whisper --manifest research/data/manifests/fleurs_el_200.jsonl --tag my-run
python -m research.latency_ab --a baseline --b current --n 50 --tag my-ab   # needs PESTO_BASELINE_DIR
python -m pasta.eval.nlu
python -m pytest
```

## Privacy

Audio never leaves the machine; models load from the local cache without network
access once downloaded; dictated text is typed without passing through the
clipboard (and is excluded from Windows clipboard history when the clipboard path
is used). Telemetry is a local SQLite file you can delete.
