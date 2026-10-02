from pathlib import Path
import sys

from .config import HOME
from .logging_setup import get_logger

log = get_logger("startup")

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "PASTA_V2"


def get_startup_command() -> str:
    """Returns the silent execution command string for Windows startup."""
    venv_pythonw = HOME / "venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.exists():
        py_exe = str(venv_pythonw)
    else:
        py_path = Path(sys.executable)
        pythonw = py_path.with_name("pythonw.exe")
        py_exe = str(pythonw if pythonw.exists() else py_path)

    return f'"{py_exe}" -m pasta run'


def is_startup_enabled() -> bool:
    """Checks whether PASTA is configured to run at Windows startup."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as exc:
        log.warning("Failed to check startup registry: %s", exc)
        return False


def enable_startup() -> bool:
    """Registers PASTA in HKCU Run key for automatic startup."""
    if sys.platform != "win32":
        log.warning("Startup registration only supported on Windows")
        return False
    cmd = get_startup_command()
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        log.info("Enabled startup in registry: %s", cmd)
        return True
    except Exception as exc:
        log.error("Failed to enable startup in registry: %s", exc)
        return False


def disable_startup() -> bool:
    """Removes PASTA from HKCU Run key."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        log.info("Disabled startup in registry")
        return True
    except Exception as exc:
        log.error("Failed to disable startup in registry: %s", exc)
        return False


def toggle_startup() -> bool:
    current = is_startup_enabled()
    if current:
        disable_startup()
        return False
    else:
        enable_startup()
        return True


def sync_startup(wanted: bool) -> None:
    current = is_startup_enabled()
    if wanted and not current:
        enable_startup()
    elif not wanted and current:
        disable_startup()
