from dataclasses import dataclass
from typing import Any

from ..config import Config, PermissionConfig
from ..logging_setup import get_logger
from .schemas import AgentAction, RiskLevel

log = get_logger("agent.safety")


@dataclass
class SafetyCheckResult:
    allowed: bool
    requires_confirmation: bool
    reason: str


class SafetyPolicy:
    """Enforces confidence thresholds, permission boundaries, and safety policies

    for PASTA agent actions.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.agent_cfg = cfg.agent
        self.perm_cfg = cfg.permissions

        self.confidence_threshold = getattr(self.agent_cfg, "confidence_threshold", 0.72)
        self.confirmation_threshold = getattr(self.agent_cfg, "confirmation_threshold", 0.55)

    def evaluate(self, action: AgentAction, confidence: float) -> SafetyCheckResult:
        # 1. Check confidence floor
        if confidence < self.confirmation_threshold:
            return SafetyCheckResult(
                allowed=False,
                requires_confirmation=False,
                reason=f"Model confidence ({confidence:.2f}) is below threshold ({self.confirmation_threshold:.2f}). Abstaining.",
            )

        # 2. Check category permissions
        if action.category == "browser" and not self.perm_cfg.browser:
            return SafetyCheckResult(
                allowed=False,
                requires_confirmation=False,
                reason="Browser automation is disabled in configuration permissions.",
            )

        if action.category == "filesystem":
            if action.risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.DESTRUCTIVE):
                if not self.perm_cfg.filesystem_write:
                    return SafetyCheckResult(
                        allowed=False,
                        requires_confirmation=False,
                        reason="Filesystem write is disabled in configuration permissions.",
                    )

        if action.category == "shell":
            if self.perm_cfg.shell == "none":
                return SafetyCheckResult(
                    allowed=False,
                    requires_confirmation=False,
                    reason="Shell command execution is disabled.",
                )

        # 3. Check risk level & confirmation requirements
        if action.risk == RiskLevel.DESTRUCTIVE:
            return SafetyCheckResult(
                allowed=True,
                requires_confirmation=True,
                reason=f"Action '{action.id}' is destructive. User confirmation is required.",
            )

        if action.risk == RiskLevel.HIGH:
            return SafetyCheckResult(
                allowed=True,
                requires_confirmation=True,
                reason=f"Action '{action.id}' has HIGH risk. User confirmation is required.",
            )

        if confidence < self.confidence_threshold:
            # Between confirmation threshold and auto-execute threshold
            return SafetyCheckResult(
                allowed=True,
                requires_confirmation=True,
                reason=f"Confidence ({confidence:.2f}) is moderate. Asking confirmation.",
            )

        # Automatically allowed
        return SafetyCheckResult(
            allowed=True,
            requires_confirmation=False,
            reason="Action permitted automatically.",
        )
