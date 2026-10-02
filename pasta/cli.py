import argparse
import ctypes
import sys

from .config import ENGINES, Config, load_config
from .logging_setup import get_logger, setup_logging
from .startup import disable_startup, enable_startup, is_startup_enabled, sync_startup


def _enforce_single_instance() -> bool:
    if sys.platform != "win32":
        return True
    ctypes.windll.kernel32.CreateMutexW(None, False, "PASTA_V2_App_Mutex")
    return ctypes.windll.kernel32.GetLastError() != 183


def _is_admin() -> bool:
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def cmd_run(cfg: Config) -> int:
    log = get_logger()
    if not _enforce_single_instance():
        log.info("PASTA is already running. Opening Dashboard...")
        return cmd_gui(cfg)

    if not _is_admin():
        log.warning("Not running as Administrator - global hotkeys may not reach elevated apps")

    if cfg.run_on_startup:
        sync_startup(True)

    from .pipeline import Pipeline
    from .tray import TrayController

    pipeline = Pipeline(cfg)
    pipeline.overlay.hide()

    log.info("=" * 60)
    log.info("🍝 PASTA V2 — Local Voice-to-Computer Control & Dictation")
    log.info("Mode: %s (Press [%s] or Click HUD to cycle)", cfg.mode.upper(), cfg.toggle_mode_key.upper())
    log.info("ASR Engine: %s | Language: %s", pipeline.active_engine.upper(), pipeline.language_mode.upper())
    log.info("Decision Model: %s (%s)", cfg.agent.model, cfg.agent.model_runtime)
    log.info("Hold [%s] to dictate or issue computer commands", cfg.hotkey.upper())
    log.info("Press [Esc] at any time to cancel running agent actions")
    log.info("Run on Startup: %s", "ENABLED" if is_startup_enabled() else "DISABLED")
    log.info("=" * 60)

    pipeline.start()
    TrayController(pipeline).start()
    pipeline.overlay.show_toast("🍝 PASTA V2 Ready", "Hold [Right Ctrl] to speak. Say 'Pasta, open Chrome...'", duration=2.5)
    pipeline.wait_forever()
    log.info("Goodbye!")
    return 0


def cmd_agent(goal: str, cfg: Config) -> int:
    """Execute an agent command directly from the command line."""
    log = get_logger()
    from .agent.loop import AgentLoop
    from .agent.models import create_decision_model

    log.info("Executing Agent goal: '%s'", goal)
    model = create_decision_model(cfg)
    loop = AgentLoop(cfg, model)
    res = loop.execute_goal(goal, transcript=goal)
    print("\n--- Agent Result ---")
    print(f"Goal:    {res['goal']}")
    print(f"Status:  {res['status']}")
    print(f"Success: {res['success']}")
    print(f"Steps:   {res['steps']}")
    print(f"Time:    {res['elapsed_ms']:.1f}ms")
    return 0 if res["success"] else 1


def cmd_benchmark() -> int:
    from benchmark.run_benchmark import run_pasta_benchmark

    return run_pasta_benchmark()


def cmd_gui(cfg: Config) -> int:
    from .gui import DashboardApp

    app = DashboardApp(cfg)
    app.run()
    return 0


def cmd_startup(action: str, cfg: Config) -> int:
    if action == "enable":
        ok = enable_startup()
        cfg.run_on_startup = True
        cfg.save()
        print("Startup enabled:", ok)
    elif action == "disable":
        ok = disable_startup()
        cfg.run_on_startup = False
        cfg.save()
        print("Startup disabled:", ok)
    else:
        print("Startup enabled:", is_startup_enabled())
    return 0


def cmd_download(engine: str, cfg: Config) -> int:
    log = get_logger()
    from .engines import create_engine

    targets = list(ENGINES) if engine == "all" else [engine]
    for name in targets:
        if name not in ENGINES:
            log.error("Unknown engine '%s' (choose from: %s)", name, ", ".join(ENGINES))
            return 1
        log.info("Downloading model for engine '%s'...", name)
        instance = create_engine(name, cfg)
        try:
            instance.load()
            instance.unload()
        except Exception as exc:
            log.error("Download failed for '%s': %s", name, exc)
            return 1
        log.info("'%s' ready", name)

    # Pre-load decision model
    log.info("Validating decision model: %s...", cfg.agent.model)
    from .agent.models import create_decision_model

    dm = create_decision_model(cfg)
    dm.load()
    dm.unload()
    log.info("Decision model ready")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="pasta",
        description="PASTA V2 — Fast local push-to-talk speech-to-text & real-time computer control for Windows",
    )
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="start push-to-talk & computer control (default)")
    run_p.add_argument("--mode", choices=["auto", "agent", "dictation"], help="operation mode (auto, agent, dictation)")
    run_p.add_argument("--engine", choices=[*ENGINES], help="ASR engine (whisper, parakeet)")
    run_p.add_argument("--language", choices=["auto", "el", "en"], help="dictation language")

    ag = sub.add_parser("agent", help="directly execute an agent automation command")
    ag.add_argument("goal", help="task goal (e.g. 'open Chrome and search RTX 5090')")

    sub.add_parser("benchmark", help="run the 50+ deterministic capability benchmark suite")
    sub.add_parser("gui", help="open Settings & Dashboard control panel")

    st = sub.add_parser("startup", help="manage Windows startup")
    st.add_argument("action", nargs="?", default="status", choices=["enable", "disable", "status"])

    dl = sub.add_parser("download", help="pre-download ASR and Decider models")
    dl.add_argument("--engine", default="all", choices=[*ENGINES, "all"])

    args = parser.parse_args(argv)

    setup_logging()
    cfg = load_config()

    if getattr(args, "mode", None):
        cfg.mode = args.mode
    if getattr(args, "engine", None) and args.command == "run":
        cfg.engine = args.engine
    if getattr(args, "language", None) and args.command == "run":
        cfg.language = args.language

    command = args.command or "run"

    if command == "run":
        return cmd_run(cfg)
    if command == "agent":
        return cmd_agent(args.goal, cfg)
    if command == "benchmark":
        return cmd_benchmark()
    if command == "gui":
        return cmd_gui(cfg)
    if command == "startup":
        return cmd_startup(args.action, cfg)
    if command == "download":
        return cmd_download(args.engine, cfg)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
