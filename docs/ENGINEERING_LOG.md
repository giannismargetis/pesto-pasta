# Engineering log — PESTO/PASTA v3 overhaul (2026-10-04)

Baseline = original code at git `d6799d0`, checked out as a separate worktree and run
with its shipped `config.json`. ASR data: FLEURS test, 200 Greek + 200 English
utterances (one per distinct sentence, seed 20261004; `research/data/manifests/`).
Hardware: RTX 3050 8 GB, Windows 10, Python 3.13. Raw outputs: `research/results/`.
Methodology: [`EVALUATION.md`](EVALUATION.md).

## 1. What was wrong (verified)

| # | Finding | Evidence |
|---|---|---|
| 1 | Default `language: auto` fed Whisper a **Greek prompt for every utterance**; English speech came out as Greek gibberish with repetition loops | English WER **51.0 %**; empty output for 21/50 three-second English clips |
| 2 | Auto language ran the 30 s Whisper encoder **twice** (faster-whisper's `detect_language` does not pass its encoder output on) | faster-whisper 1.2.1 source |
| 3 | VRAM telemetry imported **PyTorch** on the dictation path, before text injection | 1.9 s import + 0.9 s CUDA init measured |
| 4 | GPU Whisper only worked **by accident**: CTranslate2 found cuBLAS because its optional PyTorch import put `torch/lib` on the DLL path | without torch: `cublas64_12.dll not found` |
| 5 | Parakeet never ran on the GPU: first the CPU-only onnxruntime was installed (UI said CUDA); the latest onnxruntime-gpu targets CUDA 13 | `get_providers()` = CPU; ORT error log |
| 6 | "Decider-2B" never loaded (`No module named transformers.models.qwen3_5`); every agent decision came from a keyword heuristic | `logs/pasta.log` |
| 7 | Verifier returned success unconditionally for most actions; `requires_confirmation` was computed but never enforced | code |
| 8 | The "100 %" agent benchmark scored keyword candidates against keyword labels (circular) | code |
| 9 | PESTO's Greek benchmark transcribed silence and **used the reference as the hypothesis** when the output was empty (0 % WER by construction) | `voice-typer/scripts/eval_greek.py` |
| 10 | Parakeet v3 has **no final sigma (ς)** in its vocabulary; 17.7 % of Greek words end in ς | `vocab.txt` |
| 11 | Imperative dictation ("Open the report…") was executed as a command; Esc beeped on every press; F10–F12 globals collided with apps; Right Ctrl+C started a dictation | code |
| 12 | Key names come from `GetKeyNameText` (keyboard-layout-localised) in the `keyboard` library | library source |
| 13 | Clipboard overwritten on every dictation | code |

## 2. Accuracy

Corpus-level WER, 95 % bootstrap CI (paired bootstrap / Wilcoxon for differences).

| Configuration | Greek WER | English WER | Greek CER |
|---|---|---|---|
| Baseline Whisper (auto, beam 2, VAD, Greek prompt) | 12.61 % [11.1, 14.3] | **51.02 %** | 4.91 % |
| New Whisper, beam 1 | 13.09 % [11.4, 15.0] | 5.54 % | 5.11 % |
| **New Whisper, beam 2 (default)** | **12.28 % [10.8, 14.1]** | **5.52 %** | 4.57 % |
| Baseline Parakeet (int8, CPU) | 42.82 % | 9.53 % | 17.45 % |
| New Parakeet (fp32, CUDA) | 34.88 % | 5.96 % | 11.30 % |

* Greek, new beam 2 vs baseline: ΔWER −0.34 pp [−1.01, +0.35] — equivalent.
  Beam 2 vs beam 1: −0.82 pp [−1.39, −0.36] (significant) → beam 2 is the default.
* English: 51.0 % → 5.5 %. The fix is the per-language prompt chosen after
  language ID restricted to {el, en}.
* Parakeet's int8 build cost ~8 pp Greek WER and ~3.6 pp English WER versus fp32.
  Even with ς forgiven, Parakeet Greek WER would be ~31 %: Whisper stays the default.

## 3. Latency

**Engine latency, paired interleaved A/B on an idle GPU** (`research/results/latency/`), pairs
where both systems produced text:

| Clips | Baseline p50 / p95 | New p50 / p95 | Median paired Δ [95 % CI] |
|---|---|---|---|
| 3 s (push-to-talk length), n = 78 | 804 / 859 ms | **450 / 502 ms** | −351 ms [−357, −346] |
| full ≈ 10 s, n = 97 | 990 / 1332 ms | **562 / 879 ms** | −383 ms [−390, −377] |

Wilcoxon p < 1e−15 for both; the new engine was faster on 98–100 % of clips.
Beam 2 vs beam 1 in the new engine: +11 ms (3 s clips) / +24 ms (full).

**Cold start** (process start → first transcription of a 4 s clip; 3 runs each, warm file cache):
baseline 8.1 s (load 6.9 s, first inference ~980 ms) → **new 4.4 s** (load 3.7 s, first 483 ms).

**Full app start** (`scripts/smoke_start.py`: hook + microphone + model ready):
PESTO/Whisper 4.25 s, PASTA/Whisper 4.24 s, PASTA/Parakeet 3.83 s.

**Parakeet on CUDA** (fp32, cuDNN heuristic search): p50 158 ms (Greek), 124 ms (English)
vs 642 / 860 ms for the original CPU int8. With cuDNN's default exhaustive algorithm
search, every new utterance length was re-benchmarked (seconds per utterance).

**Speech gate** (Silero VAD, CPU): ~4 ms for 3 s of audio, ~13 ms for 10 s; an empty
press now costs milliseconds instead of a ~450 ms ASR call.

**Imports** (start-up, warm cache): ~5.4 s with PyTorch → ~0.7 s without.

Not yet measured: end-to-end release→text in live use (needs a person dictating;
recorded automatically in `data/pesto.db` once used).

## 4. Command understanding (PASTA)

`python -m pasta.eval.nlu`, 201 labelled utterances.

| Split | First run (held-out unseen) | After post-hoc fixes |
|---|---|---|
| Held-out commands, Greek | 97.5 % exact | 100 % |
| Held-out commands, English | 85.0 % exact | 100 % |
| Out-of-scope rejected | 80 % (2 misparses failed safely at grounding) | 100 % |
| Dictation wrongly treated as command | **0 %** (30 adversarial sentences) | 0 % |
| Legacy (PASTA v2 benchmark) | 91.1 % | 98.2 % (1 deliberate: "Computer," no longer a wake word) |

Parse latency p50 0.06 ms. Live execution success: suite written
(`python -m pasta.eval.live`), **not yet run** (it takes over the desktop).

## 5. Bugs found by running the real application (fixed, with regression tests)

* `SetWindowsHookEx` failed (error 126) because ctypes truncated the 64-bit module
  handle: the new hook would have seen no keys. Explicit prototypes everywhere.
* PASTA's UI hook ran before the extension was attached → crash at launch.
* SciPy crashed on the `sys.modules["torch"] = None` placeholder → replaced by a
  meta-path import blocker.

## 6. Remaining limitations

* FLEURS is read speech (~10 s); dictation is spontaneous and shorter. Record a
  dictation-style Greek/English code-switching set with the study runner.
* The latency A/B samples GPU utilisation immediately after our own inference, so
  the logged utilisation reflects our load, not contention; the A/B ran with the
  game closed and no other GPU jobs (verified).
* Live PASTA task success, HUD timing on real hardware, and hands-free (VAD) mode
  with a real microphone have not been measured yet.
* `onnxruntime-gpu` is pinned below 1.24 (CUDA 12) to match CTranslate2.
