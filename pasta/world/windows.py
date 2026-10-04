"""Top-level application windows, as the user sees them in Alt+Tab.

Excludes invisible, cloaked (suspended UWP frames, other virtual desktops),
tool and owned windows — the old observer listed those too, so "what is
open?" returned shell internals.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass

from pesto.inject import INJECT_TAG

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
GW_OWNER = 4
DWMWA_CLOAKED = 14
SW_RESTORE, SW_MINIMIZE, SW_MAXIMIZE, SW_SHOW = 9, 6, 3, 5
WM_CLOSE = 0x0010

_SELF_PID = os.getpid()
_IGNORED_TITLES = {"Program Manager", "Windows Input Experience", "Microsoft Text Input Application", "Settings"}

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    process: str  # e.g. "chrome.exe"
    pid: int
    minimized: bool
    maximized: bool
    foreground: bool

    @property
    def app(self) -> str:
        return self.process.rsplit(".", 1)[0].lower()

    def describe(self) -> str:
        return f"{self.title} ({self.process})"


def process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _cloaked(hwnd: int) -> bool:
    val = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    return val.value != 0


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def window_info(hwnd: int, fg: int | None = None) -> Window | None:
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return Window(int(hwnd), _title(hwnd), process_name(pid.value), pid.value, bool(user32.IsIconic(hwnd)),
                  bool(user32.IsZoomed(hwnd)), int(hwnd) == (fg if fg is not None else foreground_hwnd()))


def list_windows() -> list[Window]:
    """Alt+Tab-style list, foreground first, then Z-order."""
    fg = foreground_hwnd()
    found: list[Window] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
            return True
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW and not ex & WS_EX_APPWINDOW:
            return True
        if user32.GetWindow(hwnd, GW_OWNER) and not ex & WS_EX_APPWINDOW:
            return True
        title = _title(hwnd)
        if not title or title in _IGNORED_TITLES:
            return True
        info = window_info(hwnd, fg)
        if info and info.pid != _SELF_PID:
            found.append(info)
        return True

    user32.EnumWindows(cb, 0)
    found.sort(key=lambda w: not w.foreground)
    return found


def activate(hwnd: int) -> bool:
    """Bring a window to the foreground (works around the foreground lock)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = foreground_hwnd()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
        if not ok:
            # Last resort recognised by Windows: a synthetic ALT tap grants foreground rights.
            user32.keybd_event(0x12, 0, 0, INJECT_TAG)
            user32.keybd_event(0x12, 0, 2, INJECT_TAG)
            ok = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    return ok


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def show(hwnd: int, cmd: int) -> None:
    user32.ShowWindow(hwnd, cmd)


def close(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def exists(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd)) and bool(user32.IsWindowVisible(hwnd))


def wait_for(predicate, timeout_s: float, interval_s: float = 0.05, cancel=None):
    """Poll ``predicate`` until it returns a truthy value or time runs out."""
    deadline = time.perf_counter() + timeout_s
    while True:
        value = predicate()
        if value:
            return value
        if time.perf_counter() >= deadline or (cancel is not None and cancel.is_set()):
            return value
        time.sleep(interval_s)
