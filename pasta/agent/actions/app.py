import os
from pathlib import Path
import shutil
import subprocess
import time

from ...logging_setup import get_logger
from ..schemas import ActionResult
from .base import failure_result, success_result

log = get_logger("action.app")

KNOWN_APPS: dict[str, list[str]] = {
    "chrome": ["chrome.exe", "google-chrome"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "notepad": ["notepad.exe"],
    "vscode": ["code.cmd", "Code.exe"],
    "vs code": ["code.cmd", "Code.exe"],
    "code": ["code.cmd", "Code.exe"],
    "explorer": ["explorer.exe"],
    "terminal": ["wt.exe", "cmd.exe", "powershell.exe"],
}


def launch_application(app_name: str) -> ActionResult:
    """Capability 1: Launch an installed Windows application safely."""
    clean_name = app_name.lower().strip()
    log.info("Attempting to launch application: '%s'", app_name)

    # Check known aliases
    target_exes = KNOWN_APPS.get(clean_name, [clean_name, f"{clean_name}.exe"])

    resolved_path = None
    for exe in target_exes:
        found = shutil.which(exe)
        if found:
            resolved_path = found
            break

    # Check common Windows paths if not found in PATH
    if not resolved_path:
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        prog_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        prog_files_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"))

        candidates = [
            prog_files / "Google/Chrome/Application/chrome.exe",
            prog_files_x86 / "Google/Chrome/Application/chrome.exe",
            prog_files / "Microsoft/Edge/Application/msedge.exe",
            prog_files_x86 / "Microsoft/Edge/Application/msedge.exe",
            local_app / "Programs/Microsoft VS Code/Code.exe",
            Path("C:/Windows/System32/calc.exe"),
            Path("C:/Windows/System32/notepad.exe"),
        ]

        for cand in candidates:
            if clean_name in cand.stem.lower() and cand.exists():
                resolved_path = str(cand)
                break

    try:
        if resolved_path:
            p = subprocess.Popen([resolved_path], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            return success_result(
                f"Launched '{app_name}' from {resolved_path}",
                evidence={"pid": p.pid, "resolved_path": resolved_path},
            )
        else:
            # Fallback to Windows shell start
            os.system(f'start "" "{app_name}"')
            return success_result(f"Triggered Windows shell start for '{app_name}'", evidence={"app_name": app_name})
    except Exception as exc:
        return failure_result(f"Failed to launch '{app_name}': {exc}")


def open_file_or_folder(target_path: str) -> ActionResult:
    """Capability 4: Open a file or folder using Windows shell API."""
    try:
        p = Path(target_path).expanduser().resolve()
        if not p.exists():
            return failure_result(f"Path does not exist: {target_path}")

        os.startfile(str(p))
        return success_result(f"Opened path: {p}", evidence={"path": str(p)})
    except Exception as exc:
        return failure_result(f"Failed to open path '{target_path}': {exc}")


def find_and_open_file(filename_query: str) -> ActionResult:
    """Capability 5: Bounded search for a file by name and open it."""
    clean_query = filename_query.lower().strip()
    home = Path.home()
    search_dirs = [
        home / "Downloads",
        home / "Documents",
        home / "Desktop",
        Path.cwd(),
    ]

    found_files: list[Path] = []
    total_checked = 0
    max_scan = 600

    for s_dir in search_dirs:
        if not s_dir.exists():
            continue
        try:
            for item in s_dir.rglob("*"):
                total_checked += 1
                if total_checked > max_scan:
                    break
                if item.is_file() and clean_query in item.name.lower():
                    found_files.append(item)
                    break
        except (PermissionError, OSError):
            continue
        if found_files:
            break

    if not found_files:
        return failure_result(f"File matching '{filename_query}' not found in standard directories.")

    target = found_files[0]
    try:
        os.startfile(str(target))
        return success_result(f"Found and opened file: {target}", evidence={"path": str(target)})
    except Exception as exc:
        return failure_result(f"Failed to open found file '{target}': {exc}")
