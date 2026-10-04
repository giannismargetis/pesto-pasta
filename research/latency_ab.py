"""Paired, interleaved latency comparison of two ASR configurations.

Why paired/interleaved? GPU latency on a desktop depends on what else is
running (games, browsers, clock boosting). Measuring system A for ten
minutes and then system B for ten minutes confounds the comparison with
whatever changed in between. Here both systems transcribe the *same* clip
back-to-back, with the order alternated (ABBA counterbalancing), and every
trial records GPU utilisation and clock. The statistic of interest is the
per-clip paired difference.

Clips: full FLEURS utterances and their first 3 s ("short", typical of a
push-to-talk sentence fragment) — latency only, no accuracy is computed on
truncated clips.

    python -m research.latency_ab --a baseline --b current --n 50 --tag ab-whisper
    python -m research.latency_ab --cold --tag cold-start      # process start -> first text
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "results" / "latency"


def _system(spec: str, engine: str, baseline_dir: Path | None):
    """spec: 'baseline' | 'current' | 'current:key=json,key=json'"""
    name, _, opts = spec.partition(":")
    overrides = {}
    for kv in filter(None, opts.split(",")):
        k, _, v = kv.partition("=")
        overrides[k] = json.loads(v)
    from research.asr_eval import BaselineAdapter, CurrentAdapter

    if name == "baseline":
        return BaselineAdapter(engine, baseline_dir, "auto")
    return CurrentAdapter(engine, overrides, "auto")


def paired(args) -> None:
    from pesto import gpu
    from research import metrics
    from research.corpus import MANIFEST_DIR, load_wav, read_manifest

    items = []
    for lang in ("el", "en"):
        items += read_manifest(MANIFEST_DIR / f"fleurs_{lang}_200.jsonl")[: args.n]
    clips = []
    for it in items:
        audio = load_wav(it["path"])
        clips.append((it["id"], it["lang"], "full", audio))
        clips.append((it["id"], it["lang"], "short", audio[: 3 * 16000]))

    systems = {"A": _system(args.a, args.engine, args.baseline_dir), "B": _system(args.b, args.engine, args.baseline_dir)}
    for s in systems.values():
        s.load()
    # warm both (first-inference effects are measured separately)
    for s in systems.values():
        for _, lang, _, audio in clips[:4]:
            s.transcribe(audio, lang)

    out = OUT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(out / "trials.jsonl", "w", encoding="utf-8") as f:
        for i, (cid, lang, kind, audio) in enumerate(clips):
            order = "AB" if i % 2 == 0 else "BA"
            row = {"clip": cid, "lang": lang, "kind": kind, "seconds": round(audio.size / 16000, 2), "order": order}
            for key in order:
                snap = gpu.snapshot()
                t0 = time.perf_counter()
                systems[key].transcribe(audio, lang)
                row[f"{key}_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                row[f"{key}_gpu_util"] = snap.util_pct
                row[f"{key}_clock"] = snap.clock_mhz
            rows.append(row)
            f.write(json.dumps(row) + "\n")
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(clips)}", flush=True)

    summary = {"a": args.a, "b": args.b, "engine": args.engine, "n_clips": len(rows),
               "gpu_used_mb_at_start": round(gpu.snapshot().used_mb), "by_kind": {}}
    rng = np.random.default_rng(7)
    for kind in ("short", "full", "all"):
        sel = [r for r in rows if kind == "all" or r["kind"] == kind]
        a = np.array([r["A_ms"] for r in sel])
        b = np.array([r["B_ms"] for r in sel])
        d = b - a
        boot = np.median(d[rng.integers(0, len(d), (4000, len(d)))], axis=1)
        summary["by_kind"][kind] = {
            "A": metrics.latency_summary(a), "B": metrics.latency_summary(b),
            "median_diff_ms": float(np.median(d)), "median_diff_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
            "median_ratio_b_over_a": float(np.median(b / a)),
            "b_faster_fraction": float((d < 0).mean()),
        }
        try:
            from scipy.stats import wilcoxon

            summary["by_kind"][kind]["wilcoxon_p"] = float(wilcoxon(a, b).pvalue)
        except Exception:
            pass
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for kind, s in summary["by_kind"].items():
        print(f"[{kind:5}] A p50={s['A']['p50']:.0f} p95={s['A']['p95']:.0f} | B p50={s['B']['p50']:.0f} "
              f"p95={s['B']['p95']:.0f} | median Δ={s['median_diff_ms']:.0f} ms "
              f"CI[{s['median_diff_ci95'][0]:.0f},{s['median_diff_ci95'][1]:.0f}] ratio={s['median_ratio_b_over_a']:.2f}")


COLD_SNIPPET = r"""
import sys, time, json, os
t_start = float(sys.argv[1]); impl = sys.argv[2]; engine = sys.argv[3]
sys.path.insert(0, os.getcwd())
t_import0 = time.perf_counter()
from research.asr_eval import BaselineAdapter, CurrentAdapter
from research.corpus import read_manifest, load_wav, MANIFEST_DIR
from pathlib import Path
item = read_manifest(MANIFEST_DIR / 'fleurs_el_200.jsonl')[0]
audio = load_wav(item['path'])[: 4 * 16000]
a = BaselineAdapter(engine, Path(sys.argv[4]), 'auto') if impl == 'baseline' else CurrentAdapter(engine, {}, 'auto')
t_imported = time.perf_counter()
a.load()
t_loaded = time.perf_counter()
a.transcribe(audio, 'el')
t_first = time.perf_counter()
print(json.dumps({'import_s': t_imported - t_import0, 'load_s': t_loaded - t_imported,
                  'first_ms': (t_first - t_loaded) * 1000, 'wall_s': time.time() - t_start}))
"""


def cold(args) -> None:
    out = OUT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for impl in ("baseline", "current"):
        runs = []
        for _ in range(args.reps):
            env = dict(os.environ, HF_HUB_OFFLINE="1")
            proc = subprocess.run([sys.executable, "-c", COLD_SNIPPET, str(time.time()), impl, args.engine,
                                   str(args.baseline_dir or "")], cwd=ROOT, capture_output=True, text=True, env=env)
            line = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
            if not line:
                print(proc.stderr[-2000:])
                raise SystemExit(f"cold run failed for {impl}")
            runs.append(json.loads(line[-1]))
            print(impl, runs[-1], flush=True)
        results[impl] = {k: float(np.median([r[k] for r in runs])) for k in runs[0]} | {"runs": runs}
    (out / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="baseline")
    ap.add_argument("--b", default="current")
    ap.add_argument("--engine", default="whisper", choices=["whisper", "parakeet"])
    ap.add_argument("--n", type=int, default=50, help="utterances per language")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--cold", action="store_true", help="measure process-start to first-text instead")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--baseline-dir", type=Path, default=os.environ.get("PESTO_BASELINE_DIR"))
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    (cold if args.cold else paired)(args)


if __name__ == "__main__":
    main()
