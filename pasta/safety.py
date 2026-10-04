"""The execution gate: run automatically, ask first, or refuse.

Policy (docs/PASTA.md#safety)
-----------------------------
1. Permissions are absolute: a disabled category is refused.
2. Proposals from the LLM fallback are *never* auto-executed.
3. HIGH risk (shell, closing several windows, Alt+F4-like keys) always asks.
4. MEDIUM risk (typing, keys, clicks, closing one window) runs automatically
   only when the step is near-certain (>= 0.95), otherwise asks.
5. LOW/READ risk runs automatically at >= ``auto_threshold``.
6. Anything below ``confirm_threshold`` is refused as "not sure".
"""

from __future__ import annotations

from dataclasses import dataclass

from .intents import Risk
from .planner import Step

AUTO, CONFIRM, DENY = "auto", "confirm", "deny"


@dataclass(frozen=True)
class Gate:
    kind: str
    reason: str


def decide(step: Step, settings, permissions) -> Gate:
    perm = step.permission
    if perm == "shell":
        if permissions.shell != "allowlist":
            return Gate(DENY, "Terminal commands are disabled in settings")
    elif not getattr(permissions, perm, True):
        return Gate(DENY, f"'{perm}' actions are disabled in settings")
    if step.intent.action == "close" and permissions.close_windows == "never":
        return Gate(DENY, "Closing windows is disabled in settings")

    c = step.confidence
    if c < settings.confirm_threshold:
        return Gate(DENY, f"Not sure what you meant ({c:.0%} confidence)")
    if step.intent.source != "grammar":
        return Gate(CONFIRM, "Interpreted by the language model — please confirm")
    if step.risk >= Risk.HIGH:
        return Gate(CONFIRM, "This has broad effects — please confirm")
    if step.intent.action == "close" and permissions.close_windows == "confirm":
        return Gate(CONFIRM, "Closing a window — please confirm")
    if step.risk == Risk.MEDIUM and c < 0.95:
        return Gate(CONFIRM, f"Sends input to an app ({c:.0%} confidence)")
    if c < settings.auto_threshold:
        return Gate(CONFIRM, f"{c:.0%} confidence")
    return Gate(AUTO, "")
