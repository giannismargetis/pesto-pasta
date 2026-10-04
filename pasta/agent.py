"""The PASTA command runner.

speech -> intents (grammar, or confirmation-gated LLM) -> for each step:
ground against the live desktop -> safety gate -> (confirm) -> execute ->
verify -> report. One run at a time; a new command or Esc cancels the
current one. Every run and step is written to telemetry.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from pesto.events import EventBus, Phase, Status
from pesto.log import get_logger
from pesto.telemetry import Telemetry, now_iso

from . import safety
from .executors import FAILED, UNVERIFIED, VERIFIED, Outcome
from .intents import Intent
from .nlu import grammar, llm
from .planner import GroundingError, Planner
from .world import windows as W

log = get_logger("pasta.agent")


@dataclass
class StepView:
    label: str
    state: str = "pending"  # pending | confirm | running | done | unverified | failed | skipped
    hint: str = ""

    def as_dict(self) -> dict:
        return {"label": self.label, "state": self.state, "hint": self.hint}


@dataclass
class Run:
    id: str
    utterance: str
    interaction_id: str
    started: float = field(default_factory=time.perf_counter)
    started_at: str = field(default_factory=now_iso)
    cancel: threading.Event = field(default_factory=threading.Event)
    views: list[StepView] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)
    parser: str = "grammar"
    understand_ms: float = 0.0


class Agent:
    def __init__(self, cfg, bus: EventBus, telemetry: Telemetry | None, planner: Planner) -> None:
        self.cfg = cfg
        self.s = cfg.agent
        self.perm = cfg.permissions
        self.bus = bus
        self.telemetry = telemetry
        self.planner = planner
        self.hotkeys = None  # set by the extension once the app has started
        self._run: Run | None = None
        self._lock = threading.Lock()
        self._answer: bool | None = None
        self._answer_evt = threading.Event()
        self.awaiting_confirmation = False

    # -- control ------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._run is not None

    def cancel(self) -> bool:
        run = self._run
        if run is None:
            return False
        run.cancel.set()
        self.answer(False)
        return True

    def answer(self, yes: bool) -> None:
        self._answer = yes
        self._answer_evt.set()

    def submit(self, utterance: str, interaction_id: str = "") -> None:
        """Start a run on a worker thread (cancels any run in progress)."""
        self.cancel()
        run = Run(uuid.uuid4().hex[:12], utterance, interaction_id)
        with self._lock:
            self._run = run
        self._publish(run, Phase.UNDERSTANDING, "Understanding…", detail=f"“{utterance[:60]}”")
        threading.Thread(target=self._execute, args=(run,), name="PastaRun", daemon=True).start()

    # -- run ----------------------------------------------------------------------------
    def understand(self, utterance: str) -> tuple[list[Intent], str, dict]:
        intents = grammar.parse(utterance)
        if intents:
            return intents, "grammar", {}
        if self.s.llm_enabled:
            titles = [w.title for w in W.list_windows()]
            intents, diag = llm.parse(utterance, self.s.llm_url, self.s.llm_model, self.s.llm_timeout_s, titles)
            return intents, "llm", diag
        return [], "none", {}

    def _execute(self, run: Run) -> None:
        status, error = "completed", ""
        try:
            t0 = time.perf_counter()
            intents, run.parser, diag = self.understand(run.utterance)
            run.understand_ms = (time.perf_counter() - t0) * 1000
            if run.cancel.is_set():
                status = "cancelled"
                return
            if not intents:
                status = "not_understood"
                hint = "try “open …”, “search for …”, “switch to …”"
                self._publish(run, Phase.FAILED, "Didn't understand that", detail=hint)
                return
            if any(i.action == "stop" for i in intents):
                status = "stopped"
                self._publish(run, Phase.CANCELLED, "Stopped")
                return
            intents = intents[: self.s.max_steps]
            run.views = [StepView(self.planner.describe(i)) for i in intents]
            for idx, intent in enumerate(intents):
                if run.cancel.is_set():
                    status = "cancelled"
                    break
                ok, status, error = self._step(run, idx, intent)
                if not ok:
                    for v in run.views[idx + 1:]:
                        v.state = "skipped"
                    if status in ("failed", "rejected"):
                        self._publish(run, Phase.FAILED, error, detail=run.views[idx].label)
                    elif status in ("declined", "cancelled"):
                        self._publish(run, Phase.CANCELLED, "Cancelled", detail=run.views[idx].label)
                    break
            else:
                status = "completed"
            self._finish(run, status, error)
        except Exception as exc:
            log.exception("agent run failed")
            status, error = "failed", str(exc)
            self._publish(run, Phase.FAILED, "Something went wrong", detail=str(exc)[:80])
        finally:
            self._record(run, status, error)
            with self._lock:
                if self._run is run:
                    self._run = None

    def _step(self, run: Run, idx: int, intent: Intent) -> tuple[bool, str, str]:
        view = run.views[idx]
        rec = {"action": intent.action, "args": intent.args, "source": intent.source}
        run.records.append(rec)
        try:
            step = self.planner.ground(intent)
        except GroundingError as exc:
            view.state, view.hint = "failed", ""
            rec.update(gate="none", exec_ok=False, verification=FAILED, message=str(exc))
            return False, "failed", str(exc)
        view.label = step.label
        rec.update(risk=step.risk.name, confidence=step.confidence)
        gate = safety.decide(step, self.s, self.perm)
        rec["gate"] = gate.kind
        if gate.kind == safety.DENY:
            view.state = "failed"
            rec.update(exec_ok=False, verification="denied", message=gate.reason)
            return False, "rejected", gate.reason
        if gate.kind == safety.CONFIRM:
            view.state, view.hint = "confirm", "Enter ⏎ run · Esc cancel"
            if not self._confirm(run, step.label, gate.reason):
                view.state, view.hint = "skipped", ""
                rec.update(gate="declined", exec_ok=False, verification="declined")
                return False, "declined", ""
            rec["gate"] = "confirmed"
            view.hint = ""
        view.state = "running"
        self._publish(run, Phase.EXECUTING, step.label, detail=f"{idx + 1}/{len(run.views)}")
        t = time.perf_counter()
        try:
            outcome: Outcome = step.run(run.cancel)
        except Exception as exc:
            log.exception("step failed: %s", step.label)
            outcome = Outcome(FAILED, f"{step.label}: {exc}")
        rec.update(exec_ms=(time.perf_counter() - t) * 1000, exec_ok=outcome.ok, verification=outcome.verification,
                   evidence=outcome.evidence, message=outcome.message)
        if run.cancel.is_set():
            view.state = "skipped"
            return False, "cancelled", ""
        view.state = {VERIFIED: "done", UNVERIFIED: "unverified", FAILED: "failed"}[outcome.verification]
        view.label = outcome.message or step.label
        if outcome.verification == FAILED:
            return False, "failed", outcome.message
        return True, "completed", ""

    def _confirm(self, run: Run, label: str, reason: str) -> bool:
        self._answer, self._answer_evt = None, threading.Event()
        self.awaiting_confirmation = True
        hk = self.hotkeys
        if hk is not None:
            hk.capture(["enter", "esc"], lambda vk: self.answer(vk == 0x0D))
        try:
            self._publish(run, Phase.CONFIRM, f"{label}?", detail=reason)
            got = self._answer_evt.wait(self.s.confirm_timeout_s)
            return bool(got and self._answer and not run.cancel.is_set())
        finally:
            self.awaiting_confirmation = False
            if hk is not None:
                hk.release()

    def _finish(self, run: Run, status: str, error: str) -> None:
        if status == "completed":
            views = run.views
            last = views[-1] if views else None
            all_verified = all(v.state == "done" for v in views)
            ms = (time.perf_counter() - run.started) * 1000
            detail = f"{ms / 1000:.1f} s" + ("" if all_verified else " · not all effects verifiable")
            self._publish(run, Phase.DONE, last.label if last else "Done", detail=detail)
        elif status == "cancelled":
            self._publish(run, Phase.CANCELLED, "Cancelled")

    def _publish(self, run: Run, phase: Phase, message: str, detail: str = "") -> None:
        self.bus.publish(Status(phase, run.interaction_id or run.id, message, detail,
                                {"command": True, "steps": [v.as_dict() for v in run.views], "run_id": run.id}))

    def _record(self, run: Run, status: str, error: str) -> None:
        if self.telemetry is None:
            return
        self.telemetry.record_agent_run({
            "id": run.id, "interaction_id": run.interaction_id, "started_at": run.started_at,
            "utterance": run.utterance, "parser": run.parser,
            "plan": [{"label": v.label, "state": v.state} for v in run.views], "status": status,
            "steps": len(run.records), "verified_steps": sum(1 for r in run.records if r.get("verification") == VERIFIED),
            "understand_ms": run.understand_ms, "total_ms": (time.perf_counter() - run.started) * 1000,
            "error": error,
        }, run.records)
