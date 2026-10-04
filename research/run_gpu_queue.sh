#!/usr/bin/env bash
# Runs every GPU measurement strictly one after another (overlapping runs
# contaminate latency). Usage: PY=path/to/python research/run_gpu_queue.sh
set -u
cd "$(dirname "$0")/.."
PY=${PY:-python}
LOG=research/results/logs
mkdir -p "$LOG"
M=research/data/manifests

run() { echo "=== $(date +%T) $*"; "$@" || echo "!!! FAILED: $*"; }

# 1. Engine latency, original vs new Whisper (paired, interleaved). Torch is allowed so the
#    original code finds CUDA exactly as it did when deployed.
PESTO_ALLOW_TORCH=1 run "$PY" -m research.latency_ab --a baseline --b current --engine whisper --n 50 \
    --tag ab-whisper-baseline-vs-v3
# 2. Cost of beam 2 vs beam 1 in the new engine
run "$PY" -m research.latency_ab --a current --b "current:whisper_beam_size=2" --engine whisper --n 50 \
    --tag ab-whisper-beam1-vs-beam2
# 3. Process start -> first transcription (cold start), 3 repetitions each
run "$PY" -m research.latency_ab --cold --reps 3 --tag cold-start-whisper
# 4. Accuracy: beam 2 Greek (English beam 2 already done)
run "$PY" -m research.asr_eval --engine whisper --set whisper_beam_size=2 --manifest $M/fleurs_el_200.jsonl --tag v3-whisper-b2-el
# 5. Parakeet on GPU (fp32, auto) accuracy + engine latency on an idle GPU
for lang in el en; do
    run "$PY" -m research.asr_eval --engine parakeet --manifest $M/fleurs_${lang}_200.jsonl --tag v3-parakeet-gpu-$lang
done
echo "=== $(date +%T) queue done"
