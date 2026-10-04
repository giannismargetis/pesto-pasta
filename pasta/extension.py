"""PASTA as a PESTO extension.

PESTO owns input, ASR and text output. PASTA registers one transcript
handler: if the router decides an utterance is a command, PASTA claims it
(nothing is typed) and runs it on its own thread; otherwise the transcript
continues down PESTO's dictation path unchanged.
"""

from __future__ import annotations

from pesto.app import PestoApp
from pesto.asr import Transcript
from pesto.events import Phase, Status
from pesto.log import get_logger
from pesto.session import Interaction

from . import settings as _settings  # noqa: F401  (registers config sections)
from .agent import Agent
from .executors import Executors
from .planner import Planner
from .router import STOP_WORDS, Router, yes_no
from .world.apps import AppIndex

log = get_logger("pasta")
MODES = ("dictation", "hybrid", "command")
MODE_LABELS = {"dictation": "Dictation only", "hybrid": "Dictation + “Pasta, …” commands",
               "command": "Commands only"}


class PastaExtension:
    name = "pasta"

    def __init__(self) -> None:
        self.app: PestoApp | None = None
        self.apps = AppIndex()
        self.agent: Agent | None = None
        self.router: Router | None = None

    def attach(self, app: PestoApp) -> None:
        self.app = app
        cfg = app.cfg
        self.router = Router(cfg.agent.wake_words)
        executors = Executors(app.injector, self.apps, cfg.agent, cfg.permissions)
        self.agent = Agent(cfg, app.bus, app.telemetry, Planner(executors, self.apps, cfg.agent, cfg.permissions))
        app.session.handlers.append(self)
        app.session.on_escape.append(self.agent.cancel)
        app.session.mode_label = cfg.agent.mode
        app.combos[cfg.agent.mode_key] = self.cycle_mode
        app.product = "PASTA"
        self.apps.start()

    def started(self, app: PestoApp) -> None:
        self.agent.hotkeys = app.hotkeys  # needed for "Enter to confirm"

    def shutdown(self) -> None:
        if self.agent:
            self.agent.cancel()

    # -- TranscriptHandler ----------------------------------------------------------------
    def claim(self, it: Interaction, tr: Transcript) -> bool:
        text = tr.text.strip()
        agent, mode = self.agent, self.app.cfg.agent.mode
        if agent.awaiting_confirmation:
            answer = yes_no(text)
            if answer is not None:
                agent.answer(answer)
                return True
        if agent.busy and text.lower().strip(" .!") in STOP_WORDS:
            agent.cancel()
            return True
        route = self.router.route(text, mode)
        log.info("route: %s (%s)", route.kind, route.reason)
        if route.kind != "command":
            return False
        if not route.command:
            self.app.bus.publish(Status(Phase.DONE, it.id, "Listening for a command…",
                                        detail="say “Pasta, open …”", data={"command": True}))
            return True
        agent.submit(route.command, it.id)
        return True

    # -- mode -----------------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        cfg = self.app.cfg
        cfg.agent.mode = mode
        self.app.session.mode_label = mode
        self.app.session._publish_settings()
        self.app.bus.publish(Status(Phase.DONE, "", MODE_LABELS[mode], detail="mode",
                                    data={"command": mode != "dictation"}))

    def cycle_mode(self) -> None:
        mode = self.app.cfg.agent.mode
        self.set_mode(MODES[(MODES.index(mode) + 1) % len(MODES)] if mode in MODES else "hybrid")

