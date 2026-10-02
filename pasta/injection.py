import ctypes
import time

from .logging_setup import get_logger

log = get_logger("inject")

VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002


def get_foreground_window() -> int:
    try:
        return ctypes.windll.user32.GetForegroundWindow() or 0
    except Exception:
        return 0


def set_foreground_window(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.SetForegroundWindow(hwnd))
    except Exception as exc:
        log.warning("SetForegroundWindow failed: %s", exc)
        return False


def paste_text(text: str, target_hwnd: int | None = None) -> bool:
    import pyperclip

    try:
        pyperclip.copy(text)
    except Exception as exc:
        log.error("Clipboard copy failed: %s", exc)
        return False

    if target_hwnd:
        set_foreground_window(target_hwnd)
        time.sleep(0.03)

    user32 = ctypes.windll.user32
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    return True
