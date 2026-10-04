"""Composition root: wires configuration, input, ASR, injection, telemetry,
feedback and extensions together. The Qt UI (``pesto.ui``) and headless mode
both sit on top of :class:`PestoApp`.

Extensions (PASTA) implement :class:`Extension` and are attached before
``start()``. They receive the whole app, register transcript handlers on the
session, extra hotkeys, and UI contributions — the core never imports them.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Protocol

from . import paths
from .config import Config, load_config
from .engines import EngineManager
from .events import EventBus, Phase, Status
from .hotkeys import Hotkeys
from .inject import TextInjector
from .log import get_logger, setup_logging
from .session import VoiceSession
from .sounds import Sounds
from .telemetry import Telemetry

log = get_logger("app")


class Extension(Protocol):
    name: str

    def attach(self, app: PestoApp) -> None:
        """Before start(): register handlers, hotkeys, config."""

    def started(self, app: PestoApp) -> None:
        """After input and audio are live."""

    def shutdown(self) -> None: ...


class PestoApp:
    product = "PESTO"

    def __init__(self, cfg: Config | None = None, extensions: list[Extension] | None = None,
                 telemetry: bool = True) -> None:
        paths.ensure_dirs()
        self.cfg = cfg or load_config()
        setup_logging(self.cfg.general.log_level)
        self.bus = EventBus()
        self.telemetry = Telemetry() if telemetry else None
        self.engines = EngineManager(self.cfg.asr, self.bus)
        self.injector = TextInjector(self.cfg.inject)
        self.session = VoiceSession(self.cfg, self.bus, self.telemetry, self.engines, self.injector)
        self.sounds = Sounds(self.cfg.ui.sounds)
        self.combos = {
            self.cfg.input.language_key: self.session.cycle_language,
            self.cfg.input.engine_key: self.session.cycle_engine,
            self.cfg.input.vad_toggle_key: self.session.toggle_vad_listening,
        }
        self.extensions = list(extensions or [])
        self.hotkeys: Hotkeys | None = None
        self.bus.subscribe(self._on_status, Status)

    def _on_status(self, st: Status) -> None:
        sound = {Phase.LISTENING: "start", Phase.DONE: "done", Phase.FAILED: "error",
                 Phase.CANCELLED: "cancel", Phase.CONFIRM: "confirm"}.get(st.phase)
        if sound and self.cfg.ui.sounds:
            self.sounds.play(sound)

    def start(self) -> None:
        for ext in self.extensions:
            ext.attach(self)
            log.info("Extension attached: %s", ext.name)
        self.hotkeys = Hotkeys(self.cfg.input.ptt_key, self.cfg.input.cancel_key, self.cfg.input.hold_threshold_ms,
                               self.session.on_ptt, self.combos)
        self.hotkeys.start()
        if self.hotkeys.hook is not None and self.hotkeys.hook.error:
            self.bus.publish(Status(Phase.FAILED, message="Keyboard hook failed", detail=self.hotkeys.hook.error))
        self.session.start()
        for ext in self.extensions:
            ext.started(self)
        log.info("%s ready — hold [%s] to speak (%s, %s)", self.product, self.cfg.input.ptt_key,
                 self.cfg.asr.engine, self.cfg.asr.language)
        if not _is_admin():
            log.info("Not elevated: keys typed into elevated windows are not seen (by design; see docs).")

    def stop(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
        for ext in self.extensions:
            try:
                ext.shutdown()
            except Exception:
                log.exception("extension %s shutdown failed", ext.name)
        self.session.stop()
        if self.telemetry:
            self.telemetry.close()
        log.info("Stopped")


def _is_admin() -> bool:
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def single_instance(name: str) -> bool:
    """Returns False if another instance holds the named mutex."""
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    single_instance._handle = kernel32.CreateMutexW(None, False, f"Local\\{name}_single_instance")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
