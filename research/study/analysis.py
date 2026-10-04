"""Analysis of collected study data (within-subjects designs).

Per participant × condition the trial measures are aggregated first (so every
participant weighs equally), then conditions are compared within subjects:

* omnibus: Friedman test (k >= 3) or Wilcoxon signed-rank (k = 2);
* post hoc: pairwise Wilcoxon signed-rank, Holm-corrected, with the
  matched-pairs rank-biserial correlation as effect size;
* latency protocol: per-trial perceived speed (1–7) against *measured* total
  latency (system release->text from telemetry + added delay), Spearman's rho,
  and the share of trials rated >= 5 per delay level.

Non-parametric tests are used because WPM/error/TLX distributions in small
HCI samples are rarely normal; with fewer than ~6 participants the tests are
reported but should be treated as descriptive. Nothing here generates data:
with an empty database the script stops.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

from pesto import paths

MEASURES = {"wpm": "Words per minute", "msd_error": "Error rate % (literal MSD)",
            "cer": "Error rate % (case/punct.-insensitive)", "backspaces": "Backspaces per trial",
            "utterances": "Utterances per trial"}
OUT = Path(__file__).resolve().parents[1] / "results" / "study"


def holm(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    m = len(pvalues)
    for rank, idx in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[idx]))
        adjusted[idx] = running
    return adjusted


def rank_biserial(a: np.ndarray, b: np.ndarray) -> float:
    from scipy.stats import rankdata

    d = b - a
    d = d[d != 0]
    if d.size == 0:
        return 0.0
    r = rankdata(np.abs(d))
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def compare(table: dict[str, dict[str, float]], conditions: list[str]) -> dict:
    """table[participant][condition] -> value. Uses complete cases only."""
    from scipy.stats import friedmanchisquare, wilcoxon

    complete = [p for p, row in table.items() if all(c in row for c in conditions)]
    out: dict = {"n": len(complete)}
    if len(complete) < 3 or len(conditions) < 2:
        out["note"] = "too few complete participants for inferential tests"
        return out
    data = {c: np.array([table[p][c] for p in complete]) for c in conditions}
    if len(conditions) >= 3:
        stat, p = friedmanchisquare(*data.values())
        out["friedman"] = {"chi2": float(stat), "p": float(p)}
    pairs = list(itertools.combinations(conditions, 2))
    raw = []
    for a, b in pairs:
        try:
            raw.append(float(wilcoxon(data[a], data[b]).pvalue))
        except ValueError:  # all differences zero
            raw.append(1.0)
    out["pairwise"] = [{"a": a, "b": b, "p": p, "p_holm": ph, "rank_biserial": rank_biserial(data[a], data[b]),
                        "median_diff": float(np.median(data[b] - data[a]))}
                       for (a, b), p, ph in zip(pairs, raw, holm(raw), strict=True)]
    return out


def describe(values: list[float]) -> dict:
    v = np.asarray(values, dtype=float)
    q1, q3 = np.percentile(v, [25, 75])
    return {"n": int(v.size), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if v.size > 1 else 0.0,
            "median": float(np.median(v)), "iqr": [float(q1), float(q3)]}


def analyze(protocol_name: str, db: Path | None = None, out: Path | None = None) -> int:
    from .protocol import Protocol

    proto = Protocol.load(protocol_name)
    db = db or paths.DB_PATH
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    trials = [dict(r) for r in conn.execute("SELECT * FROM trials WHERE study = ?", (proto.name,))]
    trials = [t for t in trials if not json.loads(t["data_json"] or "{}").get("practice")]
    if not trials:
        print(f"No trials recorded for study '{proto.name}' in {db}. Run sessions first "
              f"(python -m research.study run --protocol {proto.name} --participant P01).")
        return 1
    tlx = [dict(r) for r in conn.execute("SELECT * FROM questionnaires WHERE study = ? AND instrument = 'nasa_tlx_raw'",
                                         (proto.name,))]
    latencies = {r["id"]: r["release_to_text_ms"] for r in conn.execute(
        "SELECT id, release_to_text_ms FROM interactions WHERE participant != ''")}
    conn.close()

    conditions = [c.name for c in proto.conditions]
    report: dict = {"study": proto.name, "participants": sorted({t["participant"] for t in trials}),
                    "trials": len(trials), "measures": {}}
    for key, label in MEASURES.items():
        per: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for t in trials:
            if t[key] is not None:
                per[t["participant"]][t["condition"]].append(float(t[key]))
        table = {p: {c: float(np.mean(v)) for c, v in row.items()} for p, row in per.items()}
        report["measures"][key] = {
            "label": label,
            "by_condition": {c: describe([table[p][c] for p in table if c in table[p]]) for c in conditions
                             if any(c in table[p] for p in table)},
            "tests": compare(table, conditions),
        }
    if tlx:
        table = defaultdict(dict)
        for q in tlx:
            table[q["participant"]][q["condition"]] = float(q["score"])
        report["measures"]["tlx"] = {
            "label": "Raw NASA-TLX (0–100)",
            "by_condition": {c: describe([table[p][c] for p in table if c in table[p]]) for c in conditions
                             if any(c in table[p] for p in table)},
            "tests": compare(dict(table), conditions),
        }
    if proto.rate_each_trial:
        report["perceived_latency"] = _latency_analysis(trials, latencies, conditions)

    out = out or OUT / proto.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_markdown(report, out / "report.md")
    _plots(trials, tlx, conditions, report, out)
    print((out / "report.md").read_text(encoding="utf-8"))
    return 0


def _latency_analysis(trials, latencies, conditions) -> dict:
    from scipy.stats import spearmanr

    points = []
    for t in trials:
        d = json.loads(t["data_json"] or "{}")
        rating = d.get("perceived_speed")
        sys_ms = [latencies[i] for i in d.get("interaction_ids", []) if latencies.get(i) is not None]
        if rating is None or not sys_ms:
            continue
        # release_to_text already includes the added delay (it is applied before injection)
        points.append({"condition": t["condition"], "participant": t["participant"], "rating": rating,
                       "total_ms": float(np.mean(sys_ms)), "added_ms": d.get("added_latency_ms", 0)})
    res: dict = {"n_trials": len(points)}
    if len(points) >= 5:
        rho, p = spearmanr([x["total_ms"] for x in points], [x["rating"] for x in points])
        res["spearman"] = {"rho": float(rho), "p": float(p)}
    res["by_condition"] = {}
    for c in conditions:
        sel = [x for x in points if x["condition"] == c]
        if sel:
            res["by_condition"][c] = {"median_rating": float(np.median([x["rating"] for x in sel])),
                                      "share_rated_fast": float(np.mean([x["rating"] >= 5 for x in sel])),
                                      "median_total_ms": float(np.median([x["total_ms"] for x in sel]))}
    res["points"] = points
    return res


def _write_markdown(report: dict, path: Path) -> None:
    lines = [f"# Study `{report['study']}`", "",
             f"Participants: {len(report['participants'])} · non-practice trials: {report['trials']}", ""]
    for m in report["measures"].values():
        lines += [f"## {m['label']}", "", "| Condition | n | Mean | SD | Median | IQR |", "|---|---|---|---|---|---|"]
        for c, d in m["by_condition"].items():
            lines.append(f"| {c} | {d['n']} | {d['mean']:.2f} | {d['sd']:.2f} | {d['median']:.2f} | "
                         f"{d['iqr'][0]:.2f}–{d['iqr'][1]:.2f} |")
        t = m["tests"]
        lines.append("")
        if "note" in t:
            lines.append(f"_{t['note']} (n = {t['n']})_")
        else:
            if "friedman" in t:
                lines.append(f"Friedman χ² = {t['friedman']['chi2']:.2f}, p = {t['friedman']['p']:.4f} (n = {t['n']})")
            for pw in t.get("pairwise", []):
                lines.append(f"- {pw['a']} vs {pw['b']}: Wilcoxon p = {pw['p']:.4f}, Holm p = {pw['p_holm']:.4f}, "
                             f"r_rb = {pw['rank_biserial']:+.2f}, median Δ = {pw['median_diff']:+.2f}")
        lines.append("")
    pl = report.get("perceived_latency")
    if pl:
        lines += ["## Perceived latency", ""]
        if "spearman" in pl:
            lines.append(f"Spearman ρ(total latency, rating) = {pl['spearman']['rho']:.2f}, p = {pl['spearman']['p']:.4f}"
                         f" over {pl['n_trials']} trials")
        lines += ["", "| Condition | median total latency (ms) | median rating | rated ≥ 5 |", "|---|---|---|---|"]
        for c, d in pl["by_condition"].items():
            lines.append(f"| {c} | {d['median_total_ms']:.0f} | {d['median_rating']:.1f} | {d['share_rated_fast']:.0%} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plots(trials, tlx, conditions, report, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    present = [c for c in conditions if any(t["condition"] == c for t in trials)]
    fig, axes = plt.subplots(1, 3 if tlx else 2, figsize=(12 if tlx else 8, 3.6))
    for ax, (key, title) in zip(axes, (("wpm", "WPM"), ("cer", "Error % (normalised)")), strict=False):
        data = [[t[key] for t in trials if t["condition"] == c and t[key] is not None] for c in present]
        ax.boxplot(data, tick_labels=present)
        ax.set_title(title)
    if tlx:
        data = [[q["score"] for q in tlx if q["condition"] == c] for c in present]
        axes[-1].boxplot(data, tick_labels=present)
        axes[-1].set_title("Raw NASA-TLX")
    fig.tight_layout()
    fig.savefig(out / "conditions.png", dpi=150)
    plt.close(fig)
    pl = report.get("perceived_latency")
    if pl and pl["points"]:
        fig, ax = plt.subplots(figsize=(6, 3.6))
        xs = [p["total_ms"] for p in pl["points"]]
        ys = np.array([p["rating"] for p in pl["points"]], dtype=float)
        ax.scatter(xs, ys + np.random.default_rng(0).uniform(-0.15, 0.15, ys.size), s=12, alpha=0.6)
        ax.set_xlabel("measured release → text (ms)")
        ax.set_ylabel("perceived speed (1–7)")
        fig.tight_layout()
        fig.savefig(out / "perceived_latency.png", dpi=150)
        plt.close(fig)
