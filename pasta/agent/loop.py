import threading
import time
from typing import Any
import uuid

from ..config import Config
from ..history_db import get_history_db
from ..logging_setup import get_logger
from .schemas import ActionResult, AgentAction, ComputerState, Decision, TaskState
from .actions.browser import get_browser_manager
from .candidates import CandidateBuilder
from .models.base import DecisionModel
from .planner import TaskPlanner
from .safety import SafetyPolicy
from .state import StateObserver

log = get_logger("agent.loop")


class AgentLoop:
    """Explicit state machine orchestrating the real-time computer control loop:

    Observe -> Candidates -> Decide -> Safety -> Execute -> Verify -> Complete
    """

    def __init__(
        self,
        cfg: Config,
        model: DecisionModel,
        overlay_callback=None,
    ) -> None:
        self.cfg = cfg
        self.agent_cfg = cfg.agent
        self.model = model
        self.overlay_cb = overlay_callback
        self.history_db = get_history_db()

        self.observer = StateObserver(get_browser_manager())
        self.candidate_builder = CandidateBuilder()
        self.safety_policy = SafetyPolicy(cfg)
        self.planner = TaskPlanner(max_steps=getattr(self.agent_cfg, "max_steps", 30))

        self.cancel_event = threading.Event()
        self._current_run_id = ""

    def cancel(self) -> None:
        """Invoked when user hits Esc key or calls cancel."""
        log.info("Cancel requested for agent loop!")
        self.cancel_event.set()
        if self.overlay_cb:
            self.overlay_cb("CANCELLED", "Agent task cancelled by user (Esc)", 0.0, 0, 0)

    def execute_goal(self, goal: str, transcript: str = "") -> dict[str, Any]:
        if self.cancel_event.is_set():
            self.cancel_event.clear()
            return {
                "run_id": "cancelled_pre",
                "goal": goal,
                "status": "cancelled",
                "success": False,
                "steps": 0,
                "elapsed_ms": 0.0,
            }
        self.cancel_event.clear()
        run_id = uuid.uuid4().hex[:12]
        self._current_run_id = run_id
        start_time = time.perf_counter()

        log.info("Starting Agent Run [%s]: Goal='%s' (transcript='%s')", run_id, goal, transcript)
        task = self.planner.create_task(goal)

        max_steps = getattr(self.agent_cfg, "max_steps", 30)
        timeout_seconds = getattr(self.agent_cfg, "loop_timeout_seconds", 120.0)
        deadline = time.time() + timeout_seconds

        last_action_id = ""
        repeat_count = 0
        final_status = "completed"
        execution_res = None
        verif_res = None
        last_candidates: list[AgentAction] = []
        last_decisions: list[Decision] = []

        while task.current_step < max_steps:
            if self.cancel_event.is_set():
                task.is_cancelled = True
                final_status = "cancelled"
                log.info("[%s] Agent cancelled at step %d", run_id, task.current_step)
                break

            if time.time() > deadline:
                final_status = "timed_out"
                log.warning("[%s] Agent run timed out after %.1fs", run_id, timeout_seconds)
                break

            task.current_step += 1
            step_num = task.current_step

            # 1. OBSERVE
            if self.overlay_cb:
                self.overlay_cb("OBSERVING...", goal, 0.0, step_num, max_steps)
            state = self.observer.observe(task)

            # 2. CANDIDATES
            candidates = self.candidate_builder.build_candidates(state, goal)
            last_candidates = candidates
            if not candidates:
                log.warning("[%s] No candidate actions could be generated for goal: %s", run_id, goal)
                final_status = "no_candidates"
                break

            # 3. DECIDE
            if self.overlay_cb:
                self.overlay_cb("THINKING...", goal, 0.0, step_num, max_steps)

            questions = [
                {
                    "question": f"What should PASTA do next to '{goal}'?",
                    "options": [c.id for c in candidates],
                }
            ]
            decisions = self.model.decide(state.to_summary_dict(), questions)
            last_decisions = decisions

            decision = decisions[0] if decisions else None
            if not decision:
                log.warning("[%s] Decision model returned empty decision", run_id)
                final_status = "abstain"
                break

            selected_id = decision.action_id
            confidence = decision.confidence

            # Match chosen candidate
            selected_action = next((c for c in candidates if c.id == selected_id), candidates[0])

            # Repeat loop protection
            if selected_action.id == last_action_id:
                repeat_count += 1
                if repeat_count >= getattr(self.agent_cfg, "max_same_state_repeats", 3):
                    log.warning("[%s] Action '%s' repeated %d times. Terminating loop.", run_id, selected_id, repeat_count)
                    final_status = "repeated_loop_stopped"
                    break
            else:
                last_action_id = selected_action.id
                repeat_count = 0

            # 4. SAFETY FILTER
            safety_check = self.safety_policy.evaluate(selected_action, confidence)
            if not safety_check.allowed:
                log.warning("[%s] Safety check rejected action '%s': %s", run_id, selected_id, safety_check.reason)
                final_status = f"blocked: {safety_check.reason}"
                break

            # 5. EXECUTE
            action_desc = selected_action.description
            log.info("[%s] Step %d/%d: Executing '%s' (conf=%.2f) - %s", run_id, step_num, max_steps, selected_id, confidence, action_desc)

            if self.overlay_cb:
                self.overlay_cb(f"ACTION: {action_desc}", goal, confidence, step_num, max_steps)

            try:
                execution_res = selected_action.execute()
            except Exception as exc:
                log.error("[%s] Execution exception: %s", run_id, exc)
                execution_res = ActionResult(False, False, f"Exception: {exc}", {}, True)

            # 6. VERIFY
            try:
                verif_res = selected_action.verify()
            except Exception as exc:
                log.warning("[%s] Verification exception: %s", run_id, exc)
                verif_res = ActionResult(False, False, f"Verification exception: {exc}", {}, True)

            task.step_history.append(f"{selected_action.id}: {verif_res.message}")

            if not verif_res.success:
                task.failure_count += 1
                log.warning("[%s] Action '%s' verification failed: %s (recoverable=%s)", run_id, selected_id, verif_res.message, verif_res.recoverable)
                if not verif_res.recoverable or task.failure_count >= getattr(self.agent_cfg, "max_retries", 2) * 3:
                    final_status = "unrecoverable_failure"
                    break
                time.sleep(0.5)
                continue

            # Check completion
            if self.planner.is_task_complete(task, selected_action, verif_res):
                task.is_complete = True
                final_status = "completed"
                log.info("[%s] Task goal completed successfully at step %d", run_id, step_num)
                break

            time.sleep(0.3)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        success = (final_status == "completed")

        if self.overlay_cb:
            status_label = "DONE ✓" if success else (final_status.upper())
            self.overlay_cb(status_label, goal, 1.0 if success else 0.0, task.current_step, max_steps)

        # Store trace in SQLite history
        try:
            cand_dicts = [{"id": c.id, "desc": c.description, "risk": c.risk.value} for c in last_candidates]
            prob_list = [d.confidence for d in last_decisions]
            self.history_db.add_agent_run(
                run_id=run_id,
                transcript=transcript or goal,
                task=goal,
                state_summary=f"steps={task.current_step}, status={final_status}",
                candidates=cand_dicts,
                probabilities=prob_list,
                selected_action=last_action_id,
                execution_result=execution_res.message if execution_res else "",
                verification_result=verif_res.message if verif_res else "",
                elapsed_ms=elapsed_ms,
                termination_reason=final_status,
                steps_count=task.current_step,
                success=success,
            )
        except Exception as exc:
            log.error("Failed to log agent run to history DB: %s", exc)

        log.info("Agent Run [%s] finished in %.1fms (status=%s, success=%s)", run_id, elapsed_ms, final_status, success)
        return {
            "run_id": run_id,
            "goal": goal,
            "status": final_status,
            "success": success,
            "steps": task.current_step,
            "elapsed_ms": elapsed_ms,
        }
