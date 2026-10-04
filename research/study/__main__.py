"""Study platform CLI.

    python -m research.study run --protocol input_modality --participant P01
    python -m research.study plan --protocol input_modality --participant P01
    python -m research.study analyze --protocol input_modality [--db path]

``run`` starts PESTO (dictation only, no PASTA commands) with the study
window; data go to the normal telemetry database (tables ``trials``,
``questionnaires``, ``interactions``), tagged with participant and condition.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def participant_index(pid: str) -> int:
    m = re.search(r"(\d+)$", pid)
    return int(m.group(1)) - 1 if m else 0


def cmd_plan(args) -> int:
    from .protocol import Protocol

    p = Protocol.load(args.protocol)
    for cond, practice, trials in p.assign(args.participant, args.index):
        print(f"[{cond.name}] input={cond.input} +{cond.added_latency_ms} ms  practice={len(practice)} trials={len(trials)}")
        for ph in trials:
            print(f"    {ph}")
    return 0


def cmd_run(args) -> int:
    from pesto.app import PestoApp, single_instance
    from pesto.config import load_config
    from pesto.ui.run import run_gui

    from .protocol import Protocol
    from .runner import StudyWindow

    if not single_instance("PESTO"):
        print("Close PESTO/PASTA before starting a study session.")
        return 1
    protocol = Protocol.load(args.protocol)
    cfg = load_config()
    cfg.asr.language = protocol.language  # the task language is known; no language-ID errors
    app = PestoApp(cfg)
    holder = {}

    def hook(ui):
        win = StudyWindow(app, protocol, args.participant, args.index, app.telemetry)
        win.show()
        holder["win"] = win

    return run_gui(app, "PESTO study", f"{protocol.name} · {args.participant}", ui_hooks=[hook])


def cmd_analyze(args) -> int:
    from .analysis import analyze

    return analyze(args.protocol, Path(args.db) if args.db else None, Path(args.out) if args.out else None)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m research.study", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--protocol", required=True)
        p.add_argument("--participant", required=True, help="e.g. P01 (the number selects the counterbalanced order)")
        p.add_argument("--index", type=int, help="override the Latin-square row")
    a = sub.add_parser("analyze")
    a.add_argument("--protocol", required=True)
    a.add_argument("--db")
    a.add_argument("--out")
    args = ap.parse_args(argv)
    if getattr(args, "index", None) is None and hasattr(args, "participant"):
        args.index = participant_index(args.participant)
    return {"run": cmd_run, "plan": cmd_plan, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
