"""Global keyboard input: a low-level hook and the push-to-talk state machine.

Push-to-talk semantics (docs/ARCHITECTURE.md#input):

* Recording starts the instant the PTT key goes down (plus pre-roll audio),
  but visible/audible feedback only appears once the key has been held for
  ``hold_threshold_ms``. Shorter presses are *taps* and are discarded
  silently — so using Right Ctrl for ordinary shortcuts no longer flashes the
  HUD or beeps.
* If any other key is pressed while PTT is held, the user is performing a
  shortcut (e.g. Right Ctrl + C): the recording is discarded (*chord*).
* The cancel key aborts an in-progress recording or a running command.

Keys are matched by Windows virtual-key code, which — unlike key *names* —
does not depend on the active keyboard layout (Greek/English).
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

from .inject import INJECT_TAG
from .log import get_logger

log = get_logger("hotkeys")

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP, WM_QUIT = 0x0100, 0x0101, 0x0104, 0x0105, 0x0012
VK_PACKET = 0xE7

_NAMED = {
    "right ctrl": {0xA3}, "left ctrl": {0xA2}, "ctrl": {0xA2, 0xA3},
    "right shift": {0xA1}, "left shift": {0xA0}, "shift": {0xA0, 0xA1},
    "right alt": {0xA5}, "left alt": {0xA4}, "alt": {0xA4, 0xA5},
    "right win": {0x5C}, "left win": {0x5B}, "win": {0x5B, 0x5C},
    "esc": {0x1B}, "escape": {0x1B}, "space": {0x20}, "enter": {0x0D}, "tab": {0x09},
    "caps lock": {0x14}, "scroll lock": {0x91}, "pause": {0x13}, "insert": {0x2D}, "menu": {0x5D},
    "home": {0x24}, "end": {0x23}, "page up": {0x21}, "page down": {0x22},
}
_ALIASES = {"rctrl": "right ctrl", "right control": "right ctrl", "lctrl": "left ctrl", "control": "ctrl",
            "rshift": "right shift", "ralt": "right alt", "alt gr": "right alt", "apps": "menu"}
MODIFIERS = {"ctrl": {0xA2, 0xA3, 0x11}, "shift": {0xA0, 0xA1, 0x10}, "alt": {0xA4, 0xA5, 0x12},
             "win": {0x5B, 0x5C}}
_ALL_MOD_VKS = set().union(*MODIFIERS.values())


def key_vks(name: str) -> set[int]:
    """Virtual-key codes for a single key name ("right ctrl", "f9", "l", "7")."""
    n = _ALIASES.get(name.strip().lower(), name.strip().lower())
    if n in _NAMED:
        return set(_NAMED[n])
    if len(n) >= 2 and n[0] == "f" and n[1:].isdigit() and 1 <= int(n[1:]) <= 24:
        return {0x6F + int(n[1:])}
    if len(n) == 1 and (n.isascii() and n.isalnum()):
        return {ord(n.upper())}
    raise ValueError(f"unknown key name: {name!r}")


@dataclass(frozen=True)
class Combo:
    modifiers: frozenset[str]
    key: frozenset[int]

    @classmethod
    def parse(cls, spec: str) -> Combo:
        parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
        if not parts:
            raise ValueError("empty hotkey")
        mods = frozenset(p for p in parts[:-1])
        unknown = mods - MODIFIERS.keys()
        if unknown:
            raise ValueError(f"unknown modifier(s) {sorted(unknown)} in {spec!r}")
        return cls(mods, frozenset(key_vks(parts[-1])))


@dataclass
class KeyEvent:
    vk: int
    down: bool
    t: float  # perf_counter seconds


class KeyboardHook(threading.Thread):
    """WH_KEYBOARD_LL on a dedicated message-loop thread.

    ``on_event`` runs on the hook thread and must return within a few ms
    (Windows silently uninstalls slow hooks); return True to swallow the key.
    """

    def __init__(self, on_event: Callable[[KeyEvent], bool]) -> None:
        super().__init__(name="KeyboardHook", daemon=True)
        self.on_event = on_event
        self._thread_id = 0
        self.ready = threading.Event()
        self.error: str | None = None

    def run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK

        def proc(n_code, w_param, l_param):
            if n_code == 0:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.dwExtraInfo != INJECT_TAG and kb.vkCode != VK_PACKET:
                    try:
                        if self.on_event(KeyEvent(kb.vkCode, w_param in (WM_KEYDOWN, WM_SYSKEYDOWN),
                                                  time.perf_counter())):
                            return 1
                    except Exception:
                        log.exception("hotkey handler failed")
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = HOOKPROC(proc)  # keep a reference: the C side does not own it
        self._thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            self.error = f"SetWindowsHookEx failed ({ctypes.get_last_error()})"
            log.error(self.error)
            self.ready.set()
            return
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(hook)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


class PushToTalk:
    """Pure state machine (unit-tested without a real hook)."""

    IDLE, ARMED, ACTIVE, CHORD = "idle", "armed", "active", "chord"

    def __init__(self, ptt: set[int], cancel: set[int], hold_threshold_s: float,
                 emit: Callable[[str, float], None]) -> None:
        self.ptt, self.cancel, self.hold = ptt, cancel, hold_threshold_s
        self.emit = emit  # (event_name, t) -> None ; events: press, confirm, release, tap, chord, cancel, escape
        self.state = self.IDLE
        self.t_press = 0.0
        self._token = 0

    def on_key(self, ev: KeyEvent) -> None:
        if ev.vk in self.ptt:
            if ev.down:
                if self.state == self.IDLE:
                    self.state, self.t_press = self.ARMED, ev.t
                    self._token += 1
                    self.emit("press", ev.t)
                    self._schedule_confirm(self._token)
                return  # auto-repeat while held
            prev, self.state = self.state, self.IDLE
            if prev == self.ARMED:
                self.emit("tap", ev.t)
            elif prev == self.ACTIVE:
                self.emit("release", ev.t)
            return
        if not ev.down:
            return
        if ev.vk in self.cancel:
            if self.state in (self.ARMED, self.ACTIVE):
                self.state = self.CHORD
                self.emit("cancel", ev.t)
            elif self.state == self.IDLE:
                self.emit("escape", ev.t)
            return
        if self.state in (self.ARMED, self.ACTIVE):
            # Any other key (letters or extra modifiers) while PTT is held means
            # the user is performing a shortcut such as Right Ctrl + C.
            self.state = self.CHORD
            self.emit("chord", ev.t)

    def _schedule_confirm(self, token: int) -> None:
        def confirm() -> None:
            if self._token == token and self.state == self.ARMED:
                self.state = self.ACTIVE
                self.emit("confirm", time.perf_counter())

        if self.hold <= 0:
            confirm()
        else:
            t = threading.Timer(self.hold, confirm)
            t.daemon = True
            t.start()


class Hotkeys:
    """Owns the hook, the PTT state machine and the global combos.

    Callbacks are delivered on a dedicated dispatch thread, never on the hook
    thread, so slow consumers can't get the hook uninstalled by Windows.
    """

    def __init__(self, ptt_key: str, cancel_key: str, hold_threshold_ms: int,
                 on_ptt: Callable[[str, float], None], combos: dict[str, Callable[[], None]] | None = None) -> None:
        self._queue: queue.Queue = queue.Queue()
        self.ptt = PushToTalk(key_vks(ptt_key), key_vks(cancel_key), hold_threshold_ms / 1000.0,
                              lambda name, t: self._queue.put((on_ptt, (name, t))))
        self.combos: list[tuple[Combo, Callable[[], None]]] = []
        for spec, fn in (combos or {}).items():
            if not spec:
                continue
            try:
                self.combos.append((Combo.parse(spec), fn))
            except ValueError as exc:
                log.warning("ignoring hotkey %r: %s", spec, exc)
        self._held: set[int] = set()
        self._swallowed: set[int] = set()
        self._capture: tuple[set[int], Callable[[int], None]] | None = None
        self.hook = KeyboardHook(self._on_event) if sys.platform == "win32" else None
        self._dispatcher = threading.Thread(target=self._dispatch, name="HotkeyDispatch", daemon=True)

    def start(self) -> None:
        self._dispatcher.start()
        if self.hook is not None:
            self.hook.start()
            self.hook.ready.wait(2.0)

    def stop(self) -> None:
        if self.hook is not None:
            self.hook.stop()
        self._queue.put(None)

    def capture(self, keys: list[str], callback: Callable[[int], None]) -> None:
        """Swallow ``keys`` system-wide and deliver them to ``callback(vk)``
        (on the dispatch thread) until :meth:`release` — used for "press Enter
        to confirm" without the Enter reaching the user's application."""
        vks = set().union(*(key_vks(k) for k in keys))
        self._capture = (vks, callback)

    def release(self) -> None:
        self._capture = None

    def _held_modifiers(self) -> set[str]:
        return {name for name, vks in MODIFIERS.items() if vks & self._held}

    def _on_event(self, ev: KeyEvent) -> bool:
        cap = self._capture
        if cap is not None and ev.vk in cap[0] and self.ptt.state == PushToTalk.IDLE:
            if ev.down:
                self._queue.put((cap[1], (ev.vk,)))
            return True
        if ev.down:
            self._held.add(ev.vk)
        else:
            self._held.discard(ev.vk)
            if ev.vk in self._swallowed:
                self._swallowed.discard(ev.vk)
                return True
        if ev.down and ev.vk not in _ALL_MOD_VKS:
            mods = self._held_modifiers()
            for combo, fn in self.combos:
                if ev.vk in combo.key and mods == set(combo.modifiers):
                    self._swallowed.add(ev.vk)
                    self._queue.put((fn, ()))
                    return True
        self.ptt.on_key(ev)
        return False

    def _dispatch(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            fn, args = item
            try:
                fn(*args)
            except Exception:
                log.exception("hotkey callback failed")
