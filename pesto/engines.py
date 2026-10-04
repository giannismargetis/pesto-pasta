"""Engine lifecycle: lazy load, switching, idle unload.

Every method that touches model weights is called **only on the ASR worker
thread** (see :mod:`pesto.session`), so loading, unloading and inference are
naturally serialised without cross-thread locking of the GPU.
"""

from __future__ import annotations

import time

from .asr import Engine, create_engine
from .config import AsrSettings
from .events import EventBus
from .log import get_logger

log = get_logger("engines")


class EngineManager:
    def __init__(self, settings: AsrSettings, bus: EventBus | None = None) -> None:
        self.settings = settings
        self.bus = bus
        self.active_name = settings.engine
        self._engines: dict[str, Engine] = {}
        self.state = "unloaded"  # unloaded | loading | ready | error
        self.last_error = ""
        self.last_used = time.monotonic()
        self.load_seconds: dict[str, float] = {}
        self.on_state = None  # callable(manager) set by the session

    @property
    def active(self) -> Engine:
        if self.active_name not in self._engines:
            self._engines[self.active_name] = create_engine(self.active_name, self.settings)
        return self._engines[self.active_name]

    def _set_state(self, state: str) -> None:
        self.state = state
        if self.on_state:
            self.on_state(self)

    def ensure_loaded(self) -> Engine:
        engine = self.active
        if not engine.loaded:
            self._set_state("loading")
            t0 = time.perf_counter()
            try:
                engine.load()
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("Loading %s failed", self.active_name)
                self._set_state("error")
                raise
            self.load_seconds[self.active_name] = time.perf_counter() - t0
            log.info("%s loaded in %.2f s on %s", self.active_name, self.load_seconds[self.active_name], engine.device)
            self._set_state("ready")
        self.last_used = time.monotonic()
        return engine

    def switch(self, name: str) -> None:
        if name == self.active_name:
            return
        old = self._engines.get(self.active_name)
        if old is not None and old.loaded:
            old.unload()  # free VRAM before loading the next model
        self.active_name = name
        self.settings.engine = name
        self._set_state("unloaded")

    def unload_all(self) -> None:
        for engine in self._engines.values():
            if engine.loaded:
                engine.unload()
        self._set_state("unloaded")

    def idle_unload_due(self) -> bool:
        minutes = self.settings.idle_unload_minutes
        return (
            minutes > 0
            and self.state == "ready"
            and time.monotonic() - self.last_used > minutes * 60
        )

    @property
    def device(self) -> str:
        e = self._engines.get(self.active_name)
        return e.device if e is not None else "unloaded"
