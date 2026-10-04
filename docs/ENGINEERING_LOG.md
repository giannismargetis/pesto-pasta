# Engineering log — PESTO/PASTA v3 overhaul (2026-10-04)

Baseline = original code at git `d6799d0` (checked out as a separate worktree and
run with its shipped `config.json`). All ASR numbers: FLEURS test, 200 Greek + 200
English utterances (one per distinct sentence, seed 20261004; manifests in
`research/data/manifests/`), RTX 3050 8 GB. Raw per-utterance outputs:
`research/results/asr/<tag>/`.

**Caveat on latency.** A GPU game (Bodycam) was running at 99 % GPU during most new-engine
runs, so their latencies are **not** comparable and are not reported as results.
Latency must be re-measured on an idle GPU with `python -m research.latency_ab`
(paired, interleaved A/B design built for this purpose).

## Findings in the original system (verified)

| # | Finding | Evidence |
|---|---|---|
| 1 | Default `language: auto` fed Whisper a **Greek prompt for every utterance**; English speech came out as Greek gibberish with repetition loops | Baseline English WER **51.0 %** (69/146 utterances with WER > 50 % at that point) |
| 2 | Auto language ran the 30 s Whisper encoder **twice** (faster-whisper `detect_language` does not pass its encoder output on) | faster-whisper 1.2.1 source, `transcribe()` |
| 3 | VRAM telemetry imported **PyTorch** (1.9 s import + 0.9 s CUDA init + a second CUDA context), on the dictation path before text injection | measured |
| 4 | "Decider-2B" never loaded (`No module named transformers.models.qwen3_5`); every agent decision came from a keyword heuristic | `logs/pasta.log` |
| 5 | Verifier returned success unconditionally for most actions (incl. failed browser navigation); safety `requires_confirmation` was computed but never enforced | code |
| 6 | The "100 %" agent benchmark tested the same keywords the candidates were built from (circular) | code |
| 7 | PESTO's Greek "benchmark" transcribed silence and, when the output was empty, **used the reference as the hypothesis** (0 % WER by construction) | `voice-typer/scripts/eval_greek.py` |
| 8 | Parakeet ran on CPU (CPU-only onnxruntime installed) while the UI said CUDA | `onnxruntime.get_available_providers()` |
| 9 | Parakeet v3's vocabulary has **no final sigma (ς)**; 17.7 % of Greek words end in ς. Even with ς forgiven its Greek WER is 31 % | vocab.txt; analysis |
| 10 | Imperative dictation ("Open the report…") was executed as a command; Esc beeped on every press; F10–F12 globals collided with apps; Right-Ctrl+C triggered dictation | code |

## Accuracy (WER, corpus-level, 95 % bootstrap CI)

| Config | Greek | English |
|---|---|---|
| Baseline Whisper (auto, beam 2, VAD, Greek prompt) | 12.61 % [11.1, 14.3] | **51.02 %** |
| Baseline Parakeet int8 (CPU) | 42.82 % | 9.53 % |
| New Whisper (single encode, el/en-restricted LID, per-language prompt, beam 1) | 13.09 % [11.4, 15.0] | run in progress (≈5.7 % at 125/200) |

Greek paired comparison new − baseline: ΔWER +0.48 pp, 95 % CI [−0.25, +1.20],
Wilcoxon p = 0.38 — not significant. **Open item:** run beam 2 with the new engine
(`--set whisper_beam_size=2`) to see whether it removes the small shift, then decide the default.

## PASTA language understanding (`python -m pasta.eval.nlu`)

First run (held-out written before evaluation): held-out EL 97.5 %, EN 85.0 % exact match,
out-of-scope rejection 80 %, **false-command rate on dictation 0 %**, parse p50 0.06 ms.
After post-hoc fixes (no longer unseen): 99.5 % overall; remaining miss is deliberate
("Computer," removed as wake word).

## Not yet done
- Latency/startup measurements on an idle GPU (`research.latency_ab`, `--cold`).
- Beam/VAD/prompt sweep; final default selection.
- Live desktop task-success runs (not run: user was gaming; they steal focus).
- Study runner (keyboard vs voice, NASA-TLX), thesis docs (ARCHITECTURE, EVALUATION, STUDY_PROTOCOL), README rewrite, launcher .bat files.
