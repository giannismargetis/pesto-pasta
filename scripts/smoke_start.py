"""Start the real app headless (hook + microphone + model), wait until the
engine is ready, then stop. Prints process-start -> ready timings.

    python scripts/smoke_start.py [--pasta] [--engine whisper|parakeet]

Installs the global keyboard hook for a few seconds: do not hold Right Ctrl
while it runs.
"""

from __future__ import annotations

import time

T0 = time.perf_counter()

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta", action="store_true")
    ap.add_argument("--engine", choices=["whisper", "parakeet"])
    args = ap.parse_args()

    from pesto.app import PestoApp
    from pesto.config import load_config
    from pesto.events import Settings

    t_import = time.perf_counter()
    cfg = load_config()
    if args.engine:
        cfg.asr.engine = args.engine
    exts = []
    if args.pasta:
        from pasta.extension import PastaExtension

        exts.append(PastaExtension())
    app = PestoApp(cfg, extensions=exts, telemetry=False)
    app.session.enabled = False  # hook + mic are exercised, but nothing can be dictated into the user's apps
    ready = threading.Event()
    states = []

    def on_settings(s: Settings) -> None:
        states.append((round((time.perf_counter() - T0) * 1000), s.engine_state, s.device))
        if s.engine_state in ("ready", "error"):
            ready.set()

    app.bus.subscribe(on_settings, Settings)
    t_built = time.perf_counter()
    app.start()
    t_started = time.perf_counter()
    ok = ready.wait(120)
    t_ready = time.perf_counter()
    hook_ok = app.hotkeys.hook is not None and app.hotkeys.hook.error is None and app.hotkeys.hook.ready.is_set()
    mic = app.session.mic.device_name
    device = app.engines.device
    app.stop()
    print(json.dumps({
        "engine": cfg.asr.engine, "pasta": args.pasta, "ready": ok, "device": device,
        "imports_ms": round((t_import - T0) * 1000), "construct_ms": round((t_built - t_import) * 1000),
        "start_ms": round((t_started - t_built) * 1000), "process_to_ready_ms": round((t_ready - T0) * 1000),
        "keyboard_hook": hook_ok, "microphone": mic, "states": states,
    }, ensure_ascii=False, indent=2))
    sys.stdout.flush()
    import os

    os._exit(0 if ok and hook_ok and mic else 1)


if __name__ == "__main__":
    main()
