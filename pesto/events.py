"""Interaction phases and a small thread-safe publish/subscribe bus.

Every user-visible state change flows through :class:`EventBus` as a
:class:`Status` event. The HUD renders it, telemetry records it, and an
experiment runner can observe it — so what the user *sees* and what we
*measure* come from the same source of truth.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .log import get_logger

log = get_logger("events")


class Phase(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    INJECTING = "injecting"
    DONE = "done"
    EMPTY = "empty"  # nothing recognised
    FAILED = "failed"
    CANCELLED = "cancelled"
    # PASTA (command) phases
    UNDERSTANDING = "understanding"
    CONFIRM = "confirm"
    EXECUTING = "executing"
    VERIFYING = "verifying"


TERMINAL = {Phase.DONE, Phase.EMPTY, Phase.FAILED, Phase.CANCELLED}


@dataclass
class Status:
    phase: Phase
    interaction_id: str = ""
    message: str = ""
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    t: float = field(default_factory=time.perf_counter)


@dataclass
class Level:
    """Microphone level (0..1), published ~30 times/s while listening."""

    rms: float
    t: float = field(default_factory=time.perf_counter)


@dataclass
class Preview:
    interaction_id: str
    text: str
    t: float = field(default_factory=time.perf_counter)


@dataclass
class Settings:
    """Engine / language / mode changed (for tray, HUD and dashboard)."""

    engine: str
    language: str
    mode: str
    input_mode: str
    engine_state: str  # unloaded | loading | ready | error
    device: str = ""


Handler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[tuple[type | None, Handler]] = []
        self._lock = threading.Lock()

    def subscribe(self, handler: Handler, kind: type | None = None) -> Callable[[], None]:
        entry = (kind, handler)
        with self._lock:
            self._subs.append(entry)

        def unsubscribe() -> None:
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)

        return unsubscribe

    def publish(self, event: Any) -> None:
        with self._lock:
            subs = list(self._subs)
        for kind, handler in subs:
            if kind is None or isinstance(event, kind):
                try:
                    handler(event)
                except Exception:
                    log.exception("event handler failed for %s", type(event).__name__)
