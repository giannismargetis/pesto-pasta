"""Entry point of the installed (frozen) PASTA application.

No console, no command line: single instance, first-run setup when the
speech model is missing, then the normal tray application. Any start-up
error is shown in a dialog that points to the log file.
"""

from __future__ import annotations

import os
import sys
import traceback


def _fatal(message: str) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from pesto import paths

    QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "PASTA", f"{message}\n\nΑρχείο καταγραφής / Log file:\n{paths.LOG_DIR / 'pesto.log'}")


def main() -> int:
    os.environ.setdefault("PESTO_APP", "1")
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from pesto import paths
    from pesto.app import PestoApp, single_instance
    from pesto.config import load_config
    from pesto.log import get_logger, setup_logging
    from pesto.ui import theme

    paths.ensure_dirs()
    setup_logging("INFO", console=False)
    log = get_logger("main")
    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setApplicationName("PASTA")
    qapp.setStyleSheet(theme.STYLESHEET)
    icon = paths.ASSETS_DIR / "icon.ico"
    if icon.exists():
        qapp.setWindowIcon(QIcon(str(icon)))

    if not single_instance("PASTA"):
        QMessageBox.information(None, "PASTA", "Το PASTA τρέχει ήδη — δες το εικονίδιο κάτω δεξιά.\n"
                                               "PASTA is already running (see the system tray).")
        return 0

    from pesto.ui.firstrun import FirstRun, model_cached

    cfg = load_config()
    if not model_cached() or not cfg.general.first_run_done:
        wizard = FirstRun("PASTA")
        if wizard.exec() != wizard.DialogCode.Accepted:
            return 0
        cfg.general.first_run_done = True
        cfg.save()

    from pesto.ui.run import run_gui

    from . import settings  # noqa: F401
    from .extension import PastaExtension
    from .ui import install

    ext = PastaExtension()
    app = PestoApp(cfg, extensions=[ext])
    log.info("PASTA %s starting (frozen=%s)", __import__("pasta").__version__, getattr(sys, "frozen", False))
    return run_gui(app, "PASTA", "Ομιλία σε κείμενο + φωνητικές εντολές · Ελληνικά & English",
                   show_dashboard=False, ui_hooks=[install(ext)])


def selftest(out: str) -> int:
    """`PASTA.exe --selftest <file.json>`: load each engine, transcribe 2 s of a tone,
    check the keyboard hook and microphone; no UI. Used to validate builds."""
    import json

    import numpy as np

    from pesto import paths
    from pesto.asr import create_engine
    from pesto.config import AsrSettings
    from pesto.hotkeys import KeyboardHook

    report: dict = {"frozen": bool(getattr(sys, "frozen", False)), "home": str(paths.HOME)}
    tone = (0.05 * np.sin(2 * np.pi * 220 * np.arange(32000) / 16000)).astype(np.float32)
    for name in ("whisper", "parakeet"):
        try:
            e = create_engine(name, AsrSettings())
            e.load()
            e.transcribe(tone)
            report[name] = {"ok": True, "device": e.device}
        except Exception as exc:
            report[name] = {"ok": False, "error": str(exc)}
    h = KeyboardHook(lambda ev: False)
    h.start()
    h.ready.wait(3)
    report["keyboard_hook"] = h.error or "ok"
    h.stop()
    try:
        import sounddevice as sd

        report["default_microphone"] = sd.query_devices(sd.default.device[0])["name"]
    except Exception as exc:
        report["default_microphone"] = f"none ({exc})"
    from pesto.cuda import register_cuda_libraries

    report["cuda_dirs"] = register_cuda_libraries() or "already registered"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return 0 if report["whisper"]["ok"] else 1


def run() -> None:
    try:
        if "--selftest" in sys.argv:
            from pesto.log import setup_logging

            setup_logging("INFO", console=False)
            os._exit(selftest(sys.argv[sys.argv.index("--selftest") + 1]))
        code = main()
    except Exception:
        try:
            from pesto.log import get_logger

            get_logger("main").exception("fatal start-up error")
        except Exception:
            pass
        _fatal("Το PASTA δεν μπόρεσε να ξεκινήσει.\nPASTA could not start.\n\n" + traceback.format_exc()[-800:])
        code = 1
    sys.stdout and sys.stdout.flush()
    os._exit(code)  # skip CUDA runtime teardown, which can crash on exit


if __name__ == "__main__":
    run()
