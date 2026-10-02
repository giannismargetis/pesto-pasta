import ctypes
import time
from typing import Any

from ...logging_setup import get_logger
from ..observers.windows import WindowsObserver
from ..schemas import ActionResult
from .base import failure_result, success_result

log = get_logger("action.windows")

user32 = ctypes.windll.user32

SW_HIDE = 0
SW_NORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_RESTORE = 9
WM_CLOSE = 0x0010


def focus_window(query: str | int) -> ActionResult:
    """Capability 2: Switch/focus an existing application/window."""
    obs = WindowsObserver()
    target_hwnd = 0
    target_title = ""

    if isinstance(query, int):
        target_hwnd = query
    else:
        matched = obs.find_window_by_name(query)
        if matched:
            target_hwnd = matched.hwnd
            target_title = matched.title

    if not target_hwnd:
        return failure_result(f"No window found matching '{query}'")

    try:
        # If minimized, restore it first
        if user32.IsIconic(target_hwnd):
            user32.ShowWindow(target_hwnd, SW_RESTORE)
            time.sleep(0.05)

        user32.ShowWindow(target_hwnd, SW_NORMAL)
        ok = bool(user32.SetForegroundWindow(target_hwnd))
        time.sleep(0.05)
        return success_result(
            f"Focused window: {target_title or target_hwnd}",
            evidence={"hwnd": target_hwnd, "title": target_title, "success": ok},
        )
    except Exception as exc:
        return failure_result(f"Failed to focus window: {exc}")


def minimize_window(query: str | int | None = None) -> ActionResult:
    """Capability 3a: Minimize window."""
    hwnd = _resolve_hwnd(query)
    if not hwnd:
        return failure_result("No window found to minimize")
    user32.ShowWindow(hwnd, SW_SHOWMINIMIZED)
    return success_result(f"Minimized window {hwnd}", evidence={"hwnd": hwnd})


def maximize_window(query: str | int | None = None) -> ActionResult:
    """Capability 3b: Maximize window."""
    hwnd = _resolve_hwnd(query)
    if not hwnd:
        return failure_result("No window found to maximize")
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    return success_result(f"Maximized window {hwnd}", evidence={"hwnd": hwnd})


def restore_window(query: str | int | None = None) -> ActionResult:
    """Capability 3c: Restore window."""
    hwnd = _resolve_hwnd(query)
    if not hwnd:
        return failure_result("No window found to restore")
    user32.ShowWindow(hwnd, SW_RESTORE)
    return success_result(f"Restored window {hwnd}", evidence={"hwnd": hwnd})


def close_window(query: str | int | None = None) -> ActionResult:
    """Capability 3d: Close window."""
    hwnd = _resolve_hwnd(query)
    if not hwnd:
        return failure_result("No window found to close")
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return success_result(f"Closed window {hwnd}", evidence={"hwnd": hwnd})


def _resolve_hwnd(query: str | int | None) -> int:
    if query is None or query == "":
        return user32.GetForegroundWindow() or 0
    if isinstance(query, int):
        return query
    obs = WindowsObserver()
    matched = obs.find_window_by_name(str(query))
    return matched.hwnd if matched else 0
