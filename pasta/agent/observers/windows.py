import ctypes
import os
from typing import Any

import psutil

from ...logging_setup import get_logger
from ..schemas import ApplicationState, WindowState

log = get_logger("observer.windows")

user32 = ctypes.windll.user32


class WindowsObserver:
    """Observer for native Windows state using Win32 API and UI Automation."""

    def __init__(self) -> None:
        pass

    def get_foreground_window(self) -> WindowState | None:
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            return self._build_window_state(hwnd, is_foreground=True)
        except Exception as exc:
            log.warning("get_foreground_window failed: %s", exc)
            return None

    def get_visible_windows(self) -> list[WindowState]:
        windows: list[WindowState] = []
        fg_hwnd = user32.GetForegroundWindow() or 0

        def enum_windows_callback(hwnd, extra):
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True

            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value.strip()

            # Skip invisible, tooltips, or empty titles
            if not title or title in ("Program Manager", "Settings", "Default IME", "MSCTFIME UI"):
                return True

            ws = self._build_window_state(hwnd, is_foreground=(hwnd == fg_hwnd))
            if ws:
                windows.append(ws)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        cb = WNDENUMPROC(enum_windows_callback)
        user32.EnumWindows(cb, 0)
        return windows

    def get_running_applications(self) -> list[ApplicationState]:
        apps_map: dict[str, ApplicationState] = {}
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = p.info["name"] or ""
                exe = p.info["exe"] or ""
                pid = p.info["pid"]
                if not name:
                    continue

                clean_name = name.lower().replace(".exe", "")
                if clean_name not in apps_map:
                    apps_map[clean_name] = ApplicationState(
                        name=clean_name,
                        is_running=True,
                        pids=[pid],
                        exe_path=exe,
                    )
                else:
                    apps_map[clean_name].pids.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return list(apps_map.values())

    def _build_window_state(self, hwnd: int, is_foreground: bool = False) -> WindowState | None:
        try:
            length = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            process_name = ""
            try:
                proc = psutil.Process(pid.value)
                process_name = proc.name()
            except Exception:
                pass

            rect = (ctypes.c_long * 4)()  # left, top, right, bottom
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            bounds = (rect[0], rect[1], rect[2], rect[3])

            is_minimized = bool(user32.IsIconic(hwnd))
            is_maximized = bool(user32.IsZoomed(hwnd))

            return WindowState(
                hwnd=hwnd,
                title=title,
                process_name=process_name,
                pid=pid.value,
                is_minimized=is_minimized,
                is_maximized=is_maximized,
                is_foreground=is_foreground,
                bounds=bounds,
            )
        except Exception:
            return None

    def find_window_by_name(self, query: str) -> WindowState | None:
        clean = query.lower().strip()
        for w in self.get_visible_windows():
            if clean in w.title.lower() or clean in w.process_name.lower():
                return w
        return None
