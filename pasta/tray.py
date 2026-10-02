import threading
from pathlib import Path

from .gui import open_dashboard
from .logging_setup import get_logger
from .startup import is_startup_enabled, toggle_startup

log = get_logger("tray")


def _find_icon() -> "object | None":
    from PIL import Image

    candidates = [
        Path(__file__).resolve().parent.parent / "icon.ico",
        Path.cwd() / "icon.ico",
    ]
    for path in candidates:
        if path.exists():
            try:
                return Image.open(path)
            except Exception:
                break
    return Image.new("RGBA", (64, 64), (56, 189, 248, 255))


class TrayController(threading.Thread):
    def __init__(self, pipeline) -> None:
        super().__init__(name="Tray", daemon=True)
        self.pipeline = pipeline
        self.icon = None

    def run(self) -> None:
        try:
            import pystray
        except ImportError:
            log.warning("pystray not installed, tray disabled")
            return

        pipeline = self.pipeline
        cfg = pipeline.cfg

        def on_open_dashboard(icon=None, item=None):
            open_dashboard(cfg, pipeline)

        def engine_item(name, label):
            return pystray.MenuItem(
                label,
                lambda icon, item: pipeline.set_engine(name),
                radio=True,
                checked=lambda item: pipeline.active_engine == name,
            )

        def language_item(mode, label):
            return pystray.MenuItem(
                label,
                lambda icon, item: pipeline.switch_language(mode),
                radio=True,
                checked=lambda item: pipeline.language_mode == mode,
            )

        def model_item(model_name):
            def _set(icon, item):
                cfg.whisper_model = model_name
                cfg.save()
                if pipeline.active_engine == "whisper":
                    # Reload engine with new model
                    pipeline.set_engine("whisper", force_reload=True)

            return pystray.MenuItem(
                model_name,
                _set,
                radio=True,
                checked=lambda item: cfg.whisper_model == model_name,
            )

        def on_toggle_startup(icon, item):
            new_state = toggle_startup()
            cfg.run_on_startup = new_state
            cfg.save()
            log.info("Run on startup set to %s from tray", new_state)

        def on_toggle_beep(icon, item):
            cfg.beep_enabled = not cfg.beep_enabled
            cfg.save()

        def on_toggle_overlay(icon, item):
            cfg.overlay_enabled = not cfg.overlay_enabled
            cfg.save()
            if hasattr(pipeline, "overlay"):
                pipeline.overlay.enabled = cfg.overlay_enabled

        def toggle_pause(icon, item):
            pipeline.set_paused(not pipeline.paused)

        def pause_label(item):
            return "▶ Resume (load models)" if pipeline.paused else "⏸ Pause (free memory)"

        def on_exit(icon, item):
            log.info("Exit requested from tray")
            pipeline.stop()
            icon.stop()

        def mode_item(mode_name, label):
            def _set(icon, item):
                pipeline._operation_mode = mode_name
                pipeline.overlay.set_operation_mode(mode_name)
                pipeline.overlay.show_toast(f"Mode: {mode_name.upper()}", "Switched via System Tray", duration=1.6)

            return pystray.MenuItem(
                label,
                _set,
                radio=True,
                checked=lambda item: pipeline.operation_mode == mode_name,
            )

        mode_menu = pystray.Menu(
            mode_item("agent", "🔵 Computer Use Mode (Direct Actions)"),
            mode_item("dictation", "🟢 Voice Typing Mode (Direct Text)"),
            mode_item("auto", "🟣 Smart Hybrid Mode (Wake Prefixes)"),
        )

        models_menu = pystray.Menu(
            model_item("large-v3-turbo"),
            model_item("large-v3"),
            model_item("medium"),
            model_item("small"),
            model_item("base"),
        )

        menu = pystray.Menu(
            pystray.MenuItem("⚙️ Settings & Dashboard", on_open_dashboard, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🎯 Operation Mode (F10)", mode_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: f"Active Engine: {pipeline.active_engine.upper()}",
                lambda icon, item: None,
                enabled=False,
            ),
            engine_item("whisper", "Whisper (High Accuracy)"),
            engine_item("parakeet", "Parakeet (Ultra Fast)"),
            pystray.MenuItem("Whisper Model", models_menu),
            pystray.Menu.SEPARATOR,
            language_item("auto", "🌐 Language: Auto (el + en)"),
            language_item("el", "🇬🇷 Language: Greek"),
            language_item("en", "🇬🇧 Language: English"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "🚀 Start with Windows",
                on_toggle_startup,
                checked=lambda item: is_startup_enabled(),
            ),
            pystray.MenuItem(
                "🔊 Sound Chimes",
                on_toggle_beep,
                checked=lambda item: cfg.beep_enabled,
            ),
            pystray.MenuItem(
                "🎨 Floating Overlay",
                on_toggle_overlay,
                checked=lambda item: cfg.overlay_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(pause_label, toggle_pause),
            pystray.MenuItem("❌ Exit PASTA", on_exit),
        )

        try:
            self.icon = pystray.Icon("pasta", _find_icon(), "PASTA V2", menu)
            self.icon.run()
        except Exception as exc:
            log.error("Tray failed to start: %s", exc)
