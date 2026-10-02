import pyautogui

from ...logging_setup import get_logger
from ..schemas import ActionResult
from .base import failure_result, success_result

log = get_logger("action.mouse")


def scroll_active_window(direction: str = "down", clicks: int = 5) -> ActionResult:
    """Capability 17: Scroll the active application."""
    clean_dir = direction.lower().strip()
    try:
        # positive scroll = up, negative scroll = down in PyAutoGUI
        amount = -clicks * 100 if clean_dir == "down" else clicks * 100
        pyautogui.scroll(amount)
        return success_result(f"Scrolled {clean_dir} by {clicks} units", evidence={"direction": clean_dir, "amount": amount})
    except Exception as exc:
        return failure_result(f"Failed to scroll window: {exc}")
