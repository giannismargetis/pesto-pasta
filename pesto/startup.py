"""Run-at-login registration (HKCU Run key, no elevation needed)."""

from __future__ import annotations

import sys
from pathlib import Path

from .log import get_logger

log = get_logger("startup")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command(module: str) -> str:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" -m {module}'


def is_enabled(name: str) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, name)
            return True
    except OSError:
        return False


def set_enabled(name: str, module: str, enabled: bool) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command(module))
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.error("startup registration failed: %s", exc)
        return False
