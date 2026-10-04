"""Offline evaluation of PASTA's language understanding.

    python -m pasta.eval.nlu [--llm] [--tag NAME]

Measures, per split and language:
* routing accuracy (dictation vs command, hybrid mode);
* **false-command rate** on dictation: dictated text that would have been
  executed instead of typed (the costliest error for a dictation user);
* exact match: same intent sequence with every labelled argument equal
  (accent/case-insensitive for free text);
* action match: same sequence of actions, ignoring arguments;
* out-of-scope rejection: unsupported requests answered with "didn't
  understand" rather than a wrong action;
* parse latency.

Splits: ``legacy`` = the 56 utterances of the PASTA v2 benchmark; ``dev`` =
utterances used while writing the grammar; ``heldout`` / ``heldout_oos`` /
``dictation`` = written before the first evaluation run and not used to tune
the grammar (see docs/PASTA.md#evaluation).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from pasta import settings  # noqa: F401
from pasta.nlu import grammar
from pasta.nlu.text import norm
from pasta.router import Router

DATA = Path(__file__).resolve().parent / "data" / "commands.jsonl"
OUT = Path(__file__).resolve().parents[2] / "research" / "results" / "nlu"
WAKE = ["pasta", "jarvis", "πάστα", "τζάρβις"]


def _arg_equal(expected, got) -> bool:
    if isinstance(expected, str) and isinstance(got, str):
        return norm(expected) == norm(got)
    return expected == got


def intent_match(expected: list[dict], got: list) -> tuple[bool, bool]:
    actions_ok = [e["action"] for e in expected] == [g.action for g in got]
    if not actions_ok:
        return False, False
    for e, g in zip(expected, got, strict=True):
        for k, v in e.get("args", {}).items():
            if not _arg_equal(v, g.args.get(k)):
                return False, True
    return True, True


def evaluate(use_llm: bool = False, llm_cfg=None) -> dict:
    items = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    router = Router(WAKE)
    rows = []
    for it in items:
        t0 = time.perf_counter()
        route = router.route(it["text"], "hybrid")
        intents, parser = [], "none"
        if route.kind == "command" and route.command:
            intents = grammar.parse(route.command)
            parser = "grammar" if intents else "none"
            if not intents and use_llm:
                from pasta.nlu import llm

                intents, _ = llm.parse(route.command, llm_cfg.llm_url, llm_cfg.llm_model, llm_cfg.llm_timeout_s)
                parser = "llm" if intents else "none"
        ms = (time.perf_counter() - t0) * 1000
        row = {"id": it["id"], "split": it["split"], "lang": it["lang"], "text": it["text"],
               "expected_route": it["route"], "route": route.kind, "route_reason": route.reason,
               "parser": parser, "intents": [i.to_dict() for i in intents], "ms": ms}
        row["route_ok"] = route.kind == it["route"]
        if it["route"] == "command" and it.get("oos"):
            row["exact"] = row["action"] = row["route_ok"] and not intents
        elif it["route"] == "command":
            exact, action = intent_match(it.get("intents", []), intents) if row["route_ok"] else (False, False)
            row["exact"], row["action"] = exact, action
        else:
            row["exact"] = row["action"] = row["route_ok"]
        rows.append(row)
    return summarize(rows)


def summarize(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["split"]].append(r)
        groups[f"{r['split']}:{r['lang']}"].append(r)
        groups["ALL"].append(r)
    table = {}
    for name, rs in sorted(groups.items()):
        cmd = [r for r in rs if r["expected_route"] == "command"]
        dic = [r for r in rs if r["expected_route"] == "dictation"]
        table[name] = {
            "n": len(rs),
            "route_acc": float(np.mean([r["route_ok"] for r in rs])),
            "exact_acc": float(np.mean([r["exact"] for r in rs])),
            "action_acc": float(np.mean([r["action"] for r in rs])),
            "false_command_rate": float(np.mean([r["route"] == "command" for r in dic])) if dic else None,
            "missed_command_rate": float(np.mean([r["route"] != "command" for r in cmd])) if cmd else None,
        }
    lat = [r["ms"] for r in rows]
    return {"table": table, "latency_ms": {"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95)),
                                           "max": float(np.max(lat))},
            "errors": [r for r in rows if not r["exact"]], "rows": rows}


def main() -> None:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use the Ollama fallback for unparsed commands")
    ap.add_argument("--tag", default="grammar")
    args = ap.parse_args()
    llm_cfg = None
    if args.llm:
        from pesto.config import load_config

        llm_cfg = load_config().agent
    res = evaluate(args.llm, llm_cfg)
    out = OUT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{'split':22} {'n':>4} {'route':>7} {'exact':>7} {'action':>7} {'falseCmd':>9} {'missedCmd':>10}")
    for name, s in res["table"].items():
        fc = "" if s["false_command_rate"] is None else f"{s['false_command_rate']:.1%}"
        mc = "" if s["missed_command_rate"] is None else f"{s['missed_command_rate']:.1%}"
        print(f"{name:22} {s['n']:>4} {s['route_acc']:>7.1%} {s['exact_acc']:>7.1%} {s['action_acc']:>7.1%} "
              f"{fc:>9} {mc:>10}")
    print(f"parse latency p50={res['latency_ms']['p50']:.2f} ms p95={res['latency_ms']['p95']:.2f} ms")
    print(f"\n{len(res['errors'])} errors:")
    for e in res["errors"]:
        got = [(i["action"], i["args"]) for i in e["intents"]]
        print(f"  [{e['id']}] {e['text']}\n      route={e['route']} ({e['route_reason']}) got={got}")


if __name__ == "__main__":
    main()
