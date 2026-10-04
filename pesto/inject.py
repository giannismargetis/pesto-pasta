"""Text injection into the focused application (Windows).

Methods
-------
``unicode``    SendInput with KEYEVENTF_UNICODE: one batched call, any script
               (Greek included), clipboard untouched. Default.
``clipboard``  Put text on the clipboard, send Ctrl+V, then restore the
               user's previous clipboard text. Used for long text and for
               apps that mishandle synthetic Unicode keystrokes (RDP, VMs).

Both wait until the user has released modifier keys: injecting while a
physical Ctrl is still down turns letters into shortcuts.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from .config import InjectSettings
from .log import get_logger

log = get_logger("inject")

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit prototypes: ctypes defaults to C int, which truncates 64-bit
    # handles/pointers (this broke SetWindowsHookEx in development).
    user32.GetForegroundWindow.restype = wintypes.HWND
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
else:  # pragma: no cover - the product is Windows-only; tests import pure helpers
    user32 = kernel32 = None

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
VK_RETURN, VK_TAB, VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x0D, 0x09, 0x11, 0x10, 0x12, 0x5B, 0x5C
VK_V = 0x56
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
INJECT_TAG = 0x50455354  # 'PEST' in dwExtraInfo marks our own synthetic input

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT must be present: it is the largest member and defines sizeof(INPUT).
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    return INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, INJECT_TAG)))


def unicode_events(text: str) -> list[INPUT]:
    """Key events for ``text``; newlines/tabs become real Enter/Tab presses."""
    events: list[INPUT] = []
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            events += [_key(VK_RETURN), _key(VK_RETURN, flags=KEYEVENTF_KEYUP)]
        elif ch == "\t":
            events += [_key(VK_TAB), _key(VK_TAB, flags=KEYEVENTF_KEYUP)]
        else:
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):  # astral characters -> surrogate pair
                unit = int.from_bytes(data[i : i + 2], "little")
                events += [_key(scan=unit, flags=KEYEVENTF_UNICODE),
                           _key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return events


def _send(events: list[INPUT]) -> bool:
    if not events:
        return True
    batch = 128  # keep each call well within the system input queue
    for i in range(0, len(events), batch):
        part = events[i : i + batch]
        arr = (INPUT * len(part))(*part)
        sent = user32.SendInput(len(part), arr, ctypes.sizeof(INPUT))
        if sent != len(part):
            log.error("SendInput sent %d/%d events (error %d)", sent, len(part), ctypes.get_last_error())
            return False
    return True


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0) if user32 else 0


def window_process_name(hwnd: int) -> str:
    if not hwnd or user32 is None:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(handle)


def modifiers_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN))


def wait_modifiers_released(timeout_s: float = 0.6) -> float:
    """Block until no modifier is physically held; returns ms waited."""
    t0 = time.perf_counter()
    while modifiers_down() and time.perf_counter() - t0 < timeout_s:
        time.sleep(0.005)
    return (time.perf_counter() - t0) * 1000.0


def restore_focus(hwnd: int) -> bool:
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if foreground_window() == hwnd:
        return True
    # A process may only take the foreground if it received the last input;
    # attaching to the foreground thread's input queue satisfies that rule.
    fg_thread = user32.GetWindowThreadProcessId(foreground_window(), None)
    me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(me, fg_thread, True)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.AttachThreadInput(me, fg_thread, False)
    return foreground_window() == hwnd


# -- clipboard -------------------------------------------------------------------------
class _Clipboard:
    def __enter__(self):
        for _ in range(20):
            if user32.OpenClipboard(None):
                return self
            time.sleep(0.01)
        raise OSError("clipboard busy")

    def __exit__(self, *exc):
        user32.CloseClipboard()


def _get_text() -> str | None:
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = wintypes.LPVOID
    handle = user32.GetClipboardData(CF_UNICODETEXT)
    if not handle:
        return None
    ptr = kernel32.GlobalLock(handle)
    try:
        return ctypes.wstring_at(ptr) if ptr else None
    finally:
        kernel32.GlobalUnlock(handle)


def _set_text(text: str, private: bool) -> None:
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.restype = wintypes.LPVOID
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    user32.EmptyClipboard()
    user32.SetClipboardData(CF_UNICODETEXT, handle)
    if private:  # keep dictated text out of Win+V history and cloud clipboard sync
        for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                     "CanUploadToCloudClipboard"):
            fmt = user32.RegisterClipboardFormatW(name)
            zero = kernel32.GlobalAlloc(GMEM_MOVEABLE, 4)
            p = kernel32.GlobalLock(zero)
            ctypes.memset(p, 0, 4)
            kernel32.GlobalUnlock(zero)
            user32.SetClipboardData(fmt, zero)


@dataclass
class InjectResult:
    ok: bool
    method: str
    ms: float
    modifier_wait_ms: float = 0.0
    focus_restored: bool = False
    target_app: str = ""
    error: str = ""


class TextInjector:
    def __init__(self, settings: InjectSettings) -> None:
        self.s = settings

    def choose_method(self, text: str, app: str) -> str:
        if self.s.method != "auto":
            return self.s.method
        if app.lower() in {a.lower() for a in self.s.clipboard_apps}:
            return "clipboard"
        return "clipboard" if len(text) > self.s.clipboard_threshold_chars else "unicode"

    def inject(self, text: str, target_hwnd: int = 0) -> InjectResult:
        t0 = time.perf_counter()
        if user32 is None:
            return InjectResult(False, "none", 0.0, error="not Windows")
        waited = wait_modifiers_released()
        restored = False
        if target_hwnd and foreground_window() != target_hwnd:
            restored = restore_focus(target_hwnd)
        app = window_process_name(foreground_window())
        method = self.choose_method(text, app)
        try:
            ok = self._paste(text) if method == "clipboard" else _send(unicode_events(text))
            err = "" if ok else "SendInput rejected events (target may be elevated)"
        except Exception as exc:
            ok, err = False, str(exc)
        if not ok and method == "unicode":
            log.warning("Unicode injection failed (%s); retrying via clipboard", err)
            method = "clipboard"
            try:
                ok, err = self._paste(text), ""
            except Exception as exc:
                ok, err = False, str(exc)
        return InjectResult(ok, method, (time.perf_counter() - t0) * 1000.0, waited, restored, app, err)

    def _paste(self, text: str) -> bool:
        previous = None
        with _Clipboard():
            if self.s.restore_clipboard:
                previous = _get_text()
            _set_text(text, private=True)
        seq = user32.GetClipboardSequenceNumber()
        ok = _send([_key(VK_CONTROL), _key(VK_V), _key(VK_V, flags=KEYEVENTF_KEYUP),
                    _key(VK_CONTROL, flags=KEYEVENTF_KEYUP)])
        if self.s.restore_clipboard and previous is not None:
            # The target reads the clipboard asynchronously while handling Ctrl+V.
            threading.Timer(0.25, self._restore, args=(previous, seq)).start()
        return ok

    @staticmethod
    def _restore(previous: str, seq: int) -> None:
        try:
            if user32.GetClipboardSequenceNumber() != seq:
                return  # the user copied something new meanwhile; do not clobber it
            with _Clipboard():
                _set_text(previous, private=False)
        except Exception as exc:
            log.debug("clipboard restore skipped: %s", exc)
