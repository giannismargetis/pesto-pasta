import ctypes
import re
import subprocess

import pyautogui

from ...logging_setup import get_logger
from ..schemas import ActionResult
from .base import failure_result, success_result

log = get_logger("action.shell")

ALLOWLISTED_COMMANDS = [
    r"^python\s+(--version|-V)$",
    r"^git\s+(status|branch|log(\s+-n\s+\d+)?|diff\s+--stat)$",
    r"^pip\s+(list|--version)$",
    r"^ipconfig(\s+/all)?$",
    r"^hostname$",
    r"^whoami$",
    r"^dir(\s+[a-zA-Z0-9_\-\.\\]+)?$",
    r"^echo\s+[\w\s\.\-]+$",
]


def run_safe_terminal_command(command: str) -> ActionResult:
    """Capability 18: Run a safe, allowlisted terminal command."""
    clean_cmd = command.strip()

    is_allowed = False
    for pattern in ALLOWLISTED_COMMANDS:
        if re.match(pattern, clean_cmd, flags=re.IGNORECASE):
            is_allowed = True
            break

    if not is_allowed:
        log.warning("Blocked non-allowlisted shell command: '%s'", clean_cmd)
        return failure_result(
            f"Command '{clean_cmd}' is not in the safe allowlist.",
            evidence={"command": clean_cmd, "allowed": False},
        )

    try:
        proc = subprocess.run(
            clean_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (proc.stdout or proc.stderr or "").strip()
        log.info("Executed safe command '%s' (exit %d): %s", clean_cmd, proc.returncode, output[:100])
        return success_result(
            f"Executed '{clean_cmd}'",
            evidence={
                "command": clean_cmd,
                "exit_code": proc.returncode,
                "output": output[:500],
            },
        )
    except Exception as exc:
        return failure_result(f"Failed to execute command '{clean_cmd}': {exc}")


def toggle_mute() -> ActionResult:
    """Capability 19a: Mute/unmute system volume."""
    try:
        # Send VK_VOLUME_MUTE (0xAD) key event
        pyautogui.press("volumemute")
        return success_result("Toggled system mute")
    except Exception as exc:
        return failure_result(f"Failed to toggle mute: {exc}")


def volume_up(steps: int = 2) -> ActionResult:
    """Capability 19b: Volume up."""
    try:
        for _ in range(steps):
            pyautogui.press("volumeup")
        return success_result(f"Increased volume by {steps} steps")
    except Exception as exc:
        return failure_result(f"Failed to increase volume: {exc}")


def volume_down(steps: int = 2) -> ActionResult:
    """Capability 19c: Volume down."""
    try:
        for _ in range(steps):
            pyautogui.press("volumedown")
        return success_result(f"Decreased volume by {steps} steps")
    except Exception as exc:
        return failure_result(f"Failed to decrease volume: {exc}")
