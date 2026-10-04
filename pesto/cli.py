"""``python -m pesto`` — command line entry point."""

from __future__ import annotations

import argparse
import sys
import time

from . import __version__


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def cmd_run(args) -> int:
    from .app import PestoApp, single_instance
    from .config import load_config

    if not single_instance("PESTO"):
        print("PESTO is already running (see the tray icon).")
        return 0
    cfg = load_config()
    _apply_overrides(cfg, args)
    app = PestoApp(cfg)
    if args.headless:
        return run_headless(app)
    from .ui.run import run_gui

    return run_gui(app, "PESTO", "Local push-to-talk speech input · Ελληνικά & English", args.dashboard)


def _apply_overrides(cfg, args) -> None:
    if getattr(args, "engine", None):
        cfg.asr.engine = args.engine
    if getattr(args, "language", None):
        cfg.asr.language = args.language
    if getattr(args, "input", None):
        cfg.input.mode = args.input


def run_headless(app) -> int:
    from .events import Status

    app.bus.subscribe(lambda st: print(f"[{st.phase.value}] {st.message} {st.detail}".rstrip()), Status)
    app.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    return 0


def cmd_transcribe(args) -> int:
    from .asr import create_engine
    from .config import load_config
    from .log import setup_logging

    setup_logging("WARNING")
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from research.corpus import load_wav

    cfg = load_config()
    engine = create_engine(args.engine or cfg.asr.engine, cfg.asr)
    t = time.perf_counter()
    engine.load()
    load_s = time.perf_counter() - t
    for path in args.files:
        audio = load_wav(path)
        t = time.perf_counter()
        tr = engine.transcribe(audio, args.language)
        ms = (time.perf_counter() - t) * 1000
        print(f"{path}: [{tr.language} {tr.language_prob:.2f}] {ms:.0f} ms ({audio.size / 16000:.1f} s audio)\n  {tr.text}")
    print(f"(model load {load_s:.1f} s on {engine.device})")
    return 0


def cmd_devices(_args) -> int:
    from .audio import list_input_devices

    for d in list_input_devices():
        print(f"{'*' if d['default'] else ' '} [{d['index']}] {d['name']}")
    return 0


def cmd_doctor(_args) -> int:
    from . import gpu, paths

    ok = True

    def check(name: str, fn) -> None:
        nonlocal ok
        try:
            print(f"  OK   {name}: {fn()}")
        except Exception as exc:
            ok = False
            print(f"  FAIL {name}: {exc}")

    print(f"PESTO {__version__}  home={paths.HOME}")
    check("python", lambda: sys.version.split()[0])
    check("GPU (NVML)", lambda: (lambda s: f"{s.name}, {s.used_mb:.0f}/{s.total_mb:.0f} MB" if s.available
                                  else "no NVIDIA GPU (CPU mode)")(gpu.snapshot()))
    check("CTranslate2 CUDA devices", lambda: __import__("ctranslate2").get_cuda_device_count())
    check("onnxruntime providers", lambda: ", ".join(__import__("onnxruntime").get_available_providers()))
    check("Whisper model cached", lambda: _cached("mobiuslabsgmbh/faster-whisper-large-v3-turbo"))
    check("Parakeet model cached", lambda: _cached("istupakov/parakeet-tdt-0.6b-v3-onnx"))
    check("microphone", lambda: next(d["name"] for d in __import__("pesto.audio", fromlist=["x"]).list_input_devices()
                                      if d["default"]))
    check("Qt (PySide6)", lambda: __import__("PySide6").__version__)
    check("torch not required", lambda: "not imported" if "torch" not in sys.modules else "imported (unexpected)")
    return 0 if ok else 1


def _cached(repo: str) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(repo, local_files_only=True)


def cmd_startup(args) -> int:
    from . import startup

    if args.action == "status":
        print("enabled" if startup.is_enabled("PESTO") else "disabled")
    else:
        startup.set_enabled("PESTO", "pesto", args.action == "enable")
    return 0


def build_parser(prog: str = "pesto") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description="PESTO — local push-to-talk speech input (Greek & English)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command")
    run = sub.add_parser("run", help="start (default)")
    for p in (ap, run):
        p.add_argument("--headless", action="store_true", help="no UI; print status to the console")
        p.add_argument("--dashboard", action="store_true", help="open the dashboard on start")
        p.add_argument("--engine", choices=["whisper", "parakeet"])
        p.add_argument("--language", choices=["auto", "el", "en"])
        p.add_argument("--input", choices=["ptt", "vad"], help="push-to-talk or hands-free")
    tr = sub.add_parser("transcribe", help="transcribe WAV files (quick check)")
    tr.add_argument("files", nargs="+")
    tr.add_argument("--engine", choices=["whisper", "parakeet"])
    tr.add_argument("--language", choices=["el", "en"])
    sub.add_parser("devices", help="list microphones")
    sub.add_parser("doctor", help="check the environment")
    st = sub.add_parser("startup", help="run at Windows login")
    st.add_argument("action", choices=["enable", "disable", "status"])
    return ap


COMMANDS = {"run": cmd_run, "transcribe": cmd_transcribe, "devices": cmd_devices, "doctor": cmd_doctor,
            "startup": cmd_startup}


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command or "run"](args)
