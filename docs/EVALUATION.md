# Evaluation methodology

Three kinds of evidence back the claims in this repository. Each is reproducible
from committed code + committed manifests; audio is re-downloadable.

## 1. ASR accuracy — `research/asr_eval.py`

* **Data**: FLEURS (Conneau et al., 2022, CC-BY-4.0) test split, Greek (`el_gr`) and
  English (`en_us`). Read Wikipedia sentences, 16 kHz, ~10 s per utterance.
  `research/corpus.py` picks one recording per distinct sentence (FLEURS repeats each
  sentence for up to three speakers) and shuffles with seed 20261004; the first 200
  form the default manifests (`research/data/manifests/fleurs_{el,en}_200.jsonl`).
* **Metrics** (`research/metrics.py`, unit-tested):
  * WER/CER, **corpus-level** (total edits / total reference units), after
    case/punctuation normalisation (Greek final sigma unified, apostrophes removed);
  * CER without accents — the gap to CER isolates diacritic (τόνος) errors;
  * *formatted* WER: case- and punctuation-sensitive tokens, i.e. what a dictation
    user actually receives;
  * language-ID accuracy.
* **Uncertainty**: percentile bootstrap (2000 resamples, fixed seed) for every rate;
  paired bootstrap of the difference plus Wilcoxon signed-rank on per-utterance WER
  when comparing configurations on the same utterances.
* **Isolation**: each configuration runs in a fresh process; the original code is
  evaluated from a separate worktree of commit `d6799d0` with its shipped `config.json`
  (`--impl baseline`).
* **Contention**: GPU utilisation is sampled between inferences; summaries flag
  latency as "not representative" when other processes were using the GPU.
  Accuracy is unaffected by contention.

Limitations: FLEURS is read speech with ~10 s utterances, while dictation is
spontaneous and shorter; numbers are written as digits in references, so number
formatting differences count as errors for every system; no Greek–English
code-switching corpus exists yet (record one with the study runner's
`experiment.save_audio`).

## 2. Engine latency — `research/latency_ab.py`

Desktop GPU latency drifts with other load and clock boosting, so two
configurations are never measured in separate sessions. Instead, both transcribe
the **same clip back-to-back, with the order alternated (ABBA)**, and the statistic is
the per-clip paired difference (median, bootstrap CI, Wilcoxon). Clips: 50 Greek +
50 English full utterances and their first 3 s (PTT-length). Empty outputs are
counted, so a failing engine cannot look fast. Every trial logs GPU utilisation and
clock. `--cold` measures process start → first transcription in fresh processes.

When comparing against the original code, the A/B process is run with
`PESTO_ALLOW_TORCH=1`: the original only found CUDA because CTranslate2 imported
PyTorch, and the baseline must run as it did when deployed.

## 3. Interaction latency in real use — telemetry

`data/pesto.db` (`interactions` table) stores, per dictation, the release→text and
speech-end→text latency with its decomposition (queue, gate, ASR with
encoder/decoder breakdown, routing, added delay, injection). This is the measure the
thesis should report for *perceived* latency; engine latency (above) is only one
component. The dashboard shows its distribution against the 0.1 s / 1 s limits.

## 4. Command understanding — `pasta/eval/nlu.py`

`pasta/eval/data/commands.jsonl` — 201 utterances: the 56 of the old PASTA v2
benchmark (`legacy`), 25 used while writing the grammar (`dev`), and 120 written
**before the first evaluation run** and not used to tune it (`heldout` commands,
`heldout_oos` out-of-scope requests, adversarial `dictation` negatives). The first
run is kept as `research/results/nlu/grammar-v1-first-run`; later runs after fixes
are labelled post-hoc. Metrics: routing accuracy, false-command rate on dictation,
exact intent+argument match, action match, out-of-scope rejection, parse latency.

What this does *not* measure: execution success on a real desktop. That needs the
live task suite (not yet run: it sends real input and steals focus).

## Why the old numbers were not measurements

* PASTA v2's "100 % routing / decision accuracy" scored the keyword candidate builder
  against keyword-derived labels with a keyword-based mock scorer (circular), and the
  verifier returned success for most actions without checking.
* PESTO v5's Greek benchmark transcribed *silence* and, when the output was empty,
  used the reference text as the hypothesis — 0 % WER by construction.
* The 193–348 ms latency figures came from short, warm runs on a different
  configuration and are not reproducible with the shipped settings (logs show
  650–950 ms per final transcription).
