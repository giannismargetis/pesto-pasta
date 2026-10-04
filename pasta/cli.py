"""``python -m pasta`` — PESTO + voice commands."""

from __future__ import annotations

import argparse
import json
import sys
import time

from pesto.cli import _apply_overrides, _utf8_console, build_parser, run_headless

from . import __version__


def cmd_run(args) -> int:
    from pesto.app import PestoApp, single_instance
    from pesto.config import load_config

    from . import settings  # noqa: F401
    from .extension import PastaExtension

    if not single_instance("PASTA"):
        print("PASTA is already running (see the tray icon).")
        return 0
    cfg = load_config()
    _apply_overrides(cfg, args)
    ext = PastaExtension()
    app = PestoApp(cfg, extensions=[ext])
    if args.headless:
        return run_headless(app)
    from pesto.ui.run import run_gui

    from .ui import install

    return run_gui(app, "PASTA", "Speech input + voice commands · Ελληνικά & English", args.dashboard,
                   ui_hooks=[install(ext)])


def cmd_parse(args) -> int:
    from . import settings  # noqa: F401
    from .nlu import grammar
    from .router import Router

    text = " ".join(args.text)
    from pesto.config import load_config

    cfg = load_config()
    route = Router(cfg.agent.wake_words).route(text, args.mode or cfg.agent.mode)
    t0 = time.perf_counter()
    intents = grammar.parse(route.command or text)
    ms = (time.perf_counter() - t0) * 1000
    print(json.dumps({"route": route.__dict__, "intents": [i.to_dict() for i in intents], "parse_ms": round(ms, 3)},
                     ensure_ascii=False, indent=2))
    return 0 if intents else 1


def cmd_do(args) -> int:
    """Run a command from the console (no microphone): useful for testing and demos."""
    import threading

    from pesto.config import load_config
    from pesto.events import TERMINAL, EventBus, Status
    from pesto.inject import TextInjector

    from . import safety, settings  # noqa: F401
    from .agent import Agent
    from .executors import Executors
    from .planner import GroundingError, Planner
    from .world.apps import AppIndex

    cfg = load_config()
    text = " ".join(args.text)
    apps = AppIndex()
    apps.start()
    apps.wait(15)
    planner = Planner(Executors(TextInjector(cfg.inject), apps, cfg.agent, cfg.permissions), apps, cfg.agent,
                      cfg.permissions)
    bus = EventBus()
    agent = Agent(cfg, bus, None, planner)
    intents, parser, diag = agent.understand(text)
    print(f"parser={parser} intents={[i.to_dict() for i in intents]}")
    if diag:
        print("llm:", json.dumps({k: v for k, v in diag.items() if k != "raw"}, ensure_ascii=False))
    if args.dry_run:
        for intent in intents:
            try:
                step = planner.ground(intent)
                gate = safety.decide(step, cfg.agent, cfg.permissions)
                print(f"  - {step.label}  risk={step.risk.name} conf={step.confidence:.2f} gate={gate.kind} {gate.reason}")
            except GroundingError as exc:
                print(f"  - {planner.describe(intent)}: cannot ground ({exc})")
        return 0
    done = threading.Event()

    def show(st: Status) -> None:
        steps = " | ".join(f"{s['state']}: {s['label']}" for s in st.data.get("steps", []))
        print(f"[{st.phase.value}] {st.message} {st.detail}  {steps}".rstrip())
        if st.phase in TERMINAL:
            done.set()
        if st.phase.value == "confirm":
            if args.yes:
                agent.answer(True)
            else:
                ans = input("  confirm? [y/N] ").strip().lower()
                agent.answer(ans in ("y", "yes", "ν", "ναι"))

    bus.subscribe(show, Status)
    agent.submit(text)
    done.wait(60)
    while agent.busy:
        time.sleep(0.05)
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    ap = build_parser("pasta")
    ap.description = "PASTA — PESTO speech input + voice commands for Windows"
    sub = next(a for a in ap._actions if isinstance(a, argparse._SubParsersAction))
    p = sub.add_parser("parse", help="show how an utterance is routed and parsed")
    p.add_argument("text", nargs="+")
    p.add_argument("--mode", choices=["dictation", "hybrid", "command"])
    d = sub.add_parser("do", help="execute a command typed on the console")
    d.add_argument("text", nargs="+")
    d.add_argument("--dry-run", action="store_true", help="parse, ground and gate only")
    d.add_argument("--yes", action="store_true", help="answer confirmations with yes")
    args = ap.parse_args(argv)
    from pesto import cli as core

    handlers = {"run": cmd_run, "parse": cmd_parse, "do": cmd_do}
    fn = handlers.get(args.command or "run") or core.COMMANDS[args.command]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
