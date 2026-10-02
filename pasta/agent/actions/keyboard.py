import ctypes
import time

import pyautogui
import pyperclip

from ...injection import paste_text
from ...logging_setup import get_logger
from ..schemas import ActionResult
from .base import failure_result, success_result

log = get_logger("action.keyboard")

HOTKEY_MAP = {
    "enter": ["enter"],
    "return": ["enter"],
    "esc": ["escape"],
    "escape": ["escape"],
    "tab": ["tab"],
    "space": ["space"],
    "backspace": ["backspace"],
    "delete": ["delete"],
    "copy": ["ctrl", "c"],
    "ctrl+c": ["ctrl", "c"],
    "paste": ["ctrl", "v"],
    "ctrl+v": ["ctrl", "v"],
    "cut": ["ctrl", "x"],
    "ctrl+x": ["ctrl", "x"],
    "select all": ["ctrl", "a"],
    "ctrl+a": ["ctrl", "a"],
    "address bar": ["ctrl", "l"],
    "ctrl+l": ["ctrl", "l"],
    "switch app": ["alt", "tab"],
    "alt+tab": ["alt", "tab"],
    "new tab": ["ctrl", "t"],
    "ctrl+t": ["ctrl", "t"],
    "close tab": ["ctrl", "w"],
    "ctrl+w": ["ctrl", "w"],
}


def type_dictated_text(text: str) -> ActionResult:
    """Capability 14: Type arbitrary dictated text into the focused field."""
    clean_text = text.strip()
    if not clean_text:
        return failure_result("No text provided to type")

    try:
        ok = paste_text(clean_text + " ")
        if ok:
            return success_result(f"Typed text: '{clean_text}'", evidence={"text": clean_text})
        else:
            # Fallback to direct key typing
            pyautogui.write(clean_text)
            return success_result(f"Typed text via keyboard: '{clean_text}'", evidence={"text": clean_text})
    except Exception as exc:
        return failure_result(f"Failed to type text: {exc}")


def press_hotkey(hotkey_str: str) -> ActionResult:
    """Capability 15: Press a key or standard hotkey."""
    clean = hotkey_str.lower().strip()
    keys = HOTKEY_MAP.get(clean)

    if not keys:
        # Check if user specified hyphen or plus delimited keys e.g. "ctrl+shift+p"
        if "+" in clean:
            keys = [k.strip() for k in clean.split("+")]
        else:
            keys = [clean]

    try:
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        time.sleep(0.05)
        return success_result(f"Pressed hotkey: {'+'.join(keys)}", evidence={"hotkey": "+".join(keys)})
    except Exception as exc:
        return failure_result(f"Failed to press hotkey '{hotkey_str}': {exc}")


def copy_selection() -> ActionResult:
    """Capability 16a: Copy current selection."""
    try:
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.08)
        content = pyperclip.paste()
        return success_result("Copied selection to clipboard", evidence={"clipboard": content[:100]})
    except Exception as exc:
        return failure_result(f"Failed to copy: {exc}")


def paste_clipboard() -> ActionResult:
    """Capability 16b: Paste clipboard content."""
    try:
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)
        return success_result("Pasted from clipboard")
    except Exception as exc:
        return failure_result(f"Failed to paste: {exc}")


def select_all() -> ActionResult:
    """Capability 16c: Select all in focused field/document."""
    try:
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)
        return success_result("Selected all text")
    except Exception as exc:
        return failure_result(f"Failed to select all: {exc}")
