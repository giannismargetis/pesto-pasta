from typing import Any

from ...logging_setup import get_logger
from ..schemas import ActionResult

log = get_logger("action.base")


def success_result(message: str, changed_state: bool = True, evidence: dict[str, Any] | None = None) -> ActionResult:
    return ActionResult(
        success=True,
        changed_state=changed_state,
        message=message,
        evidence=evidence or {},
        recoverable=True,
    )


def failure_result(message: str, evidence: dict[str, Any] | None = None, recoverable: bool = True) -> ActionResult:
    log.warning("Action failed: %s", message)
    return ActionResult(
        success=False,
        changed_state=False,
        message=message,
        evidence=evidence or {},
        recoverable=recoverable,
    )
