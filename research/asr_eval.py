"""Reproducible ASR evaluation: accuracy + latency + memory on a manifest.

Every configuration is evaluated in a fresh process so model state, CUDA
allocator state and caches never leak between configurations::

    python -m research.asr_eval --impl current --engine whisper \
        --manifest research/data/manifests/fleurs_el_200.jsonl --tag whisper-el

    python -m research.asr_eval --impl baseline --engine whisper ...   # original code (git d6799d0)

Outputs ``research/results/asr/<tag>/{utterances.jsonl,summary.json}``.
Latency here is *engine* latency (audio array in -> text out), measured with
``time.perf_counter`` around the transcribe call; end-to-end interaction
latency is measured separately by the live telemetry (docs/EVALUATION.md).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "research" / "results" / "asr"


# --------------------------------------------------------------------------- adapters
class Adapter:
    """Uniform wrapper so the harness never depends on one implementation."""

    name = ""

    def load(self) -> None: ...

    def transcribe(self, audio, lang: str | None) -> tuple[str, str | None]: ...

    def describe(self) -> dict: ...


class BaselineAdapter(Adapter):
    """The original PASTA engines from the baseline git worktree, configured
    exactly as the shipped config.json (language=auto, beam 2, VAD on)."""

    def __init__(self, engine: str, baseline_dir: Path, language_mode: str) -> None:
        os.environ["PASTA_HOME"] = str(ROOT)  # model cache lives in this repo
        sys.path.insert(0, str(baseline_dir))
        from pasta.config import load_config  # type: ignore  # noqa: E402
        from pasta.engines import create_engine  # type: ignore  # noqa: E402

        self.cfg = load_config(baseline_dir / "config.json")
        self.engine = create_engine(engine, self.cfg)
        self.language_mode = language_mode
        self.name = f"baseline-{engine}"

    def load(self) -> None:
        self.engine.load()

    def transcribe(self, audio, lang):
        language = None if self.language_mode == "auto" else lang
        res = self.engine.transcribe(audio, language=language, is_partial=False)
        return res.text, res.language

    def describe(self) -> dict:
        keys = ("engine", "language", "whisper_model", "whisper_compute_cuda", "whisper_beam_size",
                "whisper_vad_filter", "parakeet_model", "parakeet_quantization", "parakeet_provider")
        return {"impl": "baseline", "language_mode": self.language_mode,
                **{k: getattr(self.cfg, k, None) for k in keys},
                "device": getattr(self.engine, "device", getattr(self.engine, "device_label", "?"))}


class CurrentAdapter(Adapter):
    """The current ``pesto.asr`` engines with optional setting overrides."""

    def __init__(self, engine: str, overrides: dict, language_mode: str) -> None:
        from pesto.asr import create_engine
        from pesto.config import AsrSettings

        settings = AsrSettings()
        for key, value in overrides.items():
            if not hasattr(settings, key):
                raise SystemExit(f"unknown ASR setting: {key}")
            setattr(settings, key, value)
        self.settings = settings
        self.engine = create_engine(engine, settings)
        self.language_mode = language_mode
        self.name = f"current-{engine}"

    def load(self) -> None:
        self.engine.load()

    def transcribe(self, audio, lang):
        hint = None if self.language_mode == "auto" else lang
        res = self.engine.transcribe(audio, language=hint)
        return res.text, res.language

    def describe(self) -> dict:
        from dataclasses import asdict

        return {"impl": "current", "language_mode": self.language_mode, **asdict(self.settings),
                "device": self.engine.device,
                "resolved_quantization": getattr(self.engine, "quantization", None)
                or getattr(self.engine, "compute_type", None)}


# --------------------------------------------------------------------------- harness
def _environment() -> dict:
    from pesto import gpu

    snap = gpu.snapshot()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except Exception:
        commit, dirty = "unknown", True
    versions = {}
    for mod in ("ctranslate2", "faster_whisper", "onnxruntime", "onnx_asr", "numpy"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:
            pass
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "gpu": snap.name,
        "gpu_total_mb": round(snap.total_mb),
        "git_commit": commit,
        "git_dirty": dirty,
        "versions": versions,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def run(adapter: Adapter, manifest: Path, tag: str, limit: int | None) -> dict:
    from pesto import gpu
    from research import metrics
    from research.corpus import load_wav, read_manifest

    items = read_manifest(manifest)[: limit or None]
    out_dir = RESULTS / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    mem_before = gpu.snapshot().used_mb
    t0 = time.perf_counter()
    adapter.load()
    load_s = time.perf_counter() - t0
    mem_loaded = gpu.snapshot().used_mb

    # First inference on a real utterance (not silence) is reported separately:
    # it includes lazy CUDA kernel/JIT initialisation the user feels once.
    first_audio = load_wav(items[0]["path"])
    t0 = time.perf_counter()
    adapter.transcribe(first_audio, items[0]["lang"])
    first_ms = (time.perf_counter() - t0) * 1000.0

    scores, rows, lat, rtf = [], [], [], []
    peak_mb = mem_loaded
    util_samples = []
    with open(out_dir / "utterances.jsonl", "w", encoding="utf-8") as f:
        for i, item in enumerate(items):
            audio = load_wav(item["path"])
            t0 = time.perf_counter()
            text, detected = adapter.transcribe(audio, item["lang"])
            ms = (time.perf_counter() - t0) * 1000.0
            if i % 10 == 0:
                # NVML utilisation is averaged over the last sampling period, so
                # sample after a short idle gap: otherwise it measures our own
                # inference instead of other processes' load.
                time.sleep(0.3)
                snap = gpu.snapshot()
                peak_mb = max(peak_mb, snap.used_mb)
                util_samples.append(snap.util_pct)
            s = metrics.score(item["reference"], text)
            scores.append(s)
            lat.append(ms)
            rtf.append(ms / 1000.0 / max(item["duration_s"], 1e-3))
            row = {"id": item["id"], "lang": item["lang"], "duration_s": item["duration_s"], "latency_ms": round(ms, 2),
                   "detected_lang": detected, "reference": item["reference"], "hypothesis": text,
                   "wer": round(s.wer, 4), "cer": round(s.cer, 4), "edits": s.__dict__}
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(items)}  running WER={metrics.corpus_rates(scores)['wer']:.3f}  p50={sorted(lat)[len(lat) // 2]:.0f}ms", flush=True)

    langs = sorted({r["lang"] for r in rows})
    lang_id_acc = {lang: sum(1 for r in rows if r["lang"] == lang and r["detected_lang"] == lang)
                   / max(1, sum(1 for r in rows if r["lang"] == lang)) for lang in langs}
    summary = {
        "tag": tag,
        "manifest": str(manifest.relative_to(ROOT)) if manifest.is_relative_to(ROOT) else str(manifest),
        "n": len(rows),
        "audio_seconds": round(sum(r["duration_s"] for r in rows), 1),
        "config": adapter.describe(),
        "environment": _environment(),
        "accuracy": metrics.corpus_rates(scores),
        "accuracy_ci95": metrics.bootstrap_ci(scores),
        "language_id_accuracy": lang_id_acc,
        "latency_ms": metrics.latency_summary(lat),
        "rtf": metrics.latency_summary(rtf),
        "load_seconds": round(load_s, 2),
        "first_inference_ms": round(first_ms, 1),
        # Other GPU load biases latency (accuracy is unaffected). Utilisation is
        # sampled *between* our own inferences, so high values mean contention.
        "gpu_contention": {"util_between_inferences_mean": round(float(sum(util_samples) / max(1, len(util_samples))), 1),
                           "warning": "latency not representative" if util_samples and
                           sum(util_samples) / len(util_samples) > 30 else ""},
        "vram_mb": {"before_load": round(mem_before), "after_load": round(mem_loaded), "peak_sampled": round(peak_mb),
                    "model_delta": round(mem_loaded - mem_before)},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    acc = summary["accuracy"]
    print(f"[{tag}] n={len(rows)} WER={acc['wer']:.4f} CER={acc['cer']:.4f} fmtWER={acc['wer_formatted']:.4f} "
          f"p50={summary['latency_ms']['p50']:.0f}ms p95={summary['latency_ms']['p95']:.0f}ms "
          f"load={load_s:.1f}s first={first_ms:.0f}ms VRAM+{summary['vram_mb']['model_delta']}MB")
    return summary


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--impl", choices=["current", "baseline"], default="current")
    ap.add_argument("--engine", choices=["whisper", "parakeet"], required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--language-mode", choices=["auto", "hint"], default="auto",
                    help="auto: engine detects language (product default); hint: pass corpus language")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=JSON",
                    help="override an AsrSettings field (current impl), e.g. --set whisper_beam_size=1")
    ap.add_argument("--baseline-dir", type=Path, default=os.environ.get("PESTO_BASELINE_DIR"))
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    if args.impl == "baseline":
        if not args.baseline_dir:
            ap.error("--baseline-dir (or PESTO_BASELINE_DIR) must point at a checkout of the original code")
        adapter = BaselineAdapter(args.engine, args.baseline_dir, args.language_mode)
    else:
        overrides = {}
        for item in args.set:
            key, _, raw = item.partition("=")
            try:
                overrides[key] = json.loads(raw)
            except json.JSONDecodeError:
                overrides[key] = raw
        adapter = CurrentAdapter(args.engine, overrides, args.language_mode)
    run(adapter, args.manifest.resolve(), args.tag, args.limit)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # CTranslate2/CUDA can crash during interpreter teardown on Windows; results
    # are already on disk, so skip teardown instead of reporting a false failure.
    os._exit(code)
