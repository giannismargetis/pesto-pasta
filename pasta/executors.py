"""Action executors with post-condition verification.

Every executor returns an :class:`Outcome` whose ``verification`` is one of

* ``verified``   — an independent observation confirms the intended effect
                   (window appeared/focused/closed, volume changed, clipboard
                   changed, command exited 0, ...);
* ``failed``     — the action errored or the effect demonstrably did not occur;
* ``unverified`` — the input was delivered but the effect is not observable
                   (e.g. a media key). Reported as such, never as success.

The old implementation's verifier returned success for most actions
unconditionally (including browser navigation that had failed); its
"100% task success" figure was therefore not a measurement.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from pesto.inject import INJECT_TAG, TextInjector, _key, _send, wait_modifiers_released
from pesto.log import get_logger

from .world import windows as W
from .world.apps import KNOWN_EXES, App
from .world.sites import SEARCH_URLS

log = get_logger("pasta.exec")
user32 = ctypes.WinDLL("user32", use_last_error=True)

VERIFIED, FAILED, UNVERIFIED = "verified", "failed", "unverified"
BROWSER_EXES = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "comet.exe", "vivaldi.exe"}


@dataclass
class Outcome:
    verification: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verification != FAILED


# --------------------------------------------------------------------------- keyboard
VK = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "up": 0x26,
      "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
      "insert": 0x2D, "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "volume_mute": 0xAD,
      "volume_down": 0xAE, "volume_up": 0xAF, "media_next": 0xB0, "media_prev": 0xB1, "media_play_pause": 0xB3}
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
VK.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E, 0x5B}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002


def send_combo(combo: str) -> bool:
    keys = [VK[k] for k in combo.lower().split("+")]
    wait_modifiers_released()
    events = []
    for vk in keys:
        events.append(_key(vk, flags=KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0))
    for vk in reversed(keys):
        events.append(_key(vk, flags=KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)))
    return _send(events)


def scroll_wheel(direction: str, notches: int) -> None:
    from pesto.inject import INPUT, MOUSEINPUT, _INPUTUNION

    delta = 120 * notches * (1 if direction == "up" else -1)
    inp = INPUT(0, _INPUTUNION(mi=MOUSEINPUT(0, 0, delta & 0xFFFFFFFF, 0x0800, 0, INJECT_TAG)))  # MOUSEEVENTF_WHEEL
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def clipboard_seq() -> int:
    return int(user32.GetClipboardSequenceNumber())


# --------------------------------------------------------------------------- helpers
def _fg() -> W.Window | None:
    return W.window_info(W.foreground_hwnd())


def _title_changed(hwnd: int, before: str, timeout: float, cancel) -> str | None:
    def check():
        info = W.window_info(hwnd)
        return info.title if info and info.title != before else None
    return W.wait_for(check, timeout, cancel=cancel)


def find_browser_exe(name: str) -> str | None:
    exe = {"chrome": "chrome.exe", "msedge": "msedge.exe", "firefox": "firefox.exe", "opera": "opera.exe",
           "brave": "brave.exe", "comet": "comet.exe"}.get(name, f"{name}.exe")
    found = shutil.which(exe)
    if found:
        return found
    try:
        import winreg

        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                    return winreg.QueryValue(k, None)
            except OSError:
                continue
    except Exception:
        pass
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    for p in (local / "Perplexity/Comet/Application/comet.exe", local / "Programs/Opera/opera.exe"):
        if p.name == exe and p.exists():
            return str(p)
    return None


def _norm_tokens(text: str) -> list[str]:
    from .nlu.text import norm

    return [t for t in norm(text).split() if len(t) >= 3]


# --------------------------------------------------------------------------- executors
class Executors:
    def __init__(self, injector: TextInjector, apps, settings, permissions) -> None:
        self.injector = injector
        self.apps = apps
        self.s = settings
        self.perm = permissions

    # windows -----------------------------------------------------------------------------
    def focus(self, win: W.Window, cancel) -> Outcome:
        W.activate(win.hwnd)
        ok = W.wait_for(lambda: W.foreground_hwnd() == win.hwnd, 1.5, cancel=cancel)
        if ok:
            return Outcome(VERIFIED, f"Switched to {win.title}", {"hwnd": win.hwnd})
        return Outcome(FAILED, f"Windows did not let me bring '{win.title}' to the front", {"hwnd": win.hwnd})

    def launch(self, app: App, cancel) -> Outcome:
        before = {w.hwnd for w in W.list_windows()}
        expect = KNOWN_EXES.get(app.exe_hint, {app.exe_hint} if app.exe_hint else set())
        subprocess.Popen(app.launch_command(), creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                         close_fds=True)
        name_tokens = _norm_tokens(app.name)

        def appeared():
            for w in W.list_windows():
                if w.hwnd in before:
                    continue
                title_tokens = set(_norm_tokens(w.title))
                if w.process.lower() in expect or (name_tokens and set(name_tokens) & title_tokens):
                    return w
                if not expect and not name_tokens:
                    return w
            return None

        win = W.wait_for(appeared, self.s.step_timeout_s, interval_s=0.1, cancel=cancel)
        if win:
            if not win.foreground:
                W.activate(win.hwnd)
            return Outcome(VERIFIED, f"Opened {app.name}", {"hwnd": win.hwnd, "process": win.process,
                                                           "title": win.title})
        # Single-instance apps may reuse an existing window (e.g. Steam, Discord).
        fg = _fg()
        if fg and (fg.process.lower() in expect or set(name_tokens) & set(_norm_tokens(fg.title))):
            return Outcome(VERIFIED, f"{app.name} is in front", {"hwnd": fg.hwnd, "title": fg.title})
        return Outcome(UNVERIFIED, f"Started {app.name}, but no window appeared within {self.s.step_timeout_s:.0f} s",
                       {"app_id": app.app_id})

    def window_state(self, win: W.Window, op: str, cancel) -> Outcome:
        cmd = {"minimize": W.SW_MINIMIZE, "maximize": W.SW_MAXIMIZE, "restore": W.SW_RESTORE}[op]
        W.show(win.hwnd, cmd)
        check = {"minimize": lambda: user32.IsIconic(win.hwnd),
                 "maximize": lambda: user32.IsZoomed(win.hwnd),
                 "restore": lambda: not user32.IsIconic(win.hwnd) and not user32.IsZoomed(win.hwnd)}[op]
        if W.wait_for(check, 1.0, cancel=cancel):
            return Outcome(VERIFIED, f"{op.capitalize()}d {win.title}", {"hwnd": win.hwnd})
        return Outcome(FAILED, f"Could not {op} {win.title}", {"hwnd": win.hwnd})

    def close(self, wins: list[W.Window], cancel) -> Outcome:
        for w in wins:
            W.close(w.hwnd)
        gone = W.wait_for(lambda: all(not W.exists(w.hwnd) for w in wins), 3.0, cancel=cancel)
        names = ", ".join(sorted({w.title for w in wins}))[:120]
        if gone:
            return Outcome(VERIFIED, f"Closed {names}", {"hwnds": [w.hwnd for w in wins]})
        fg = _fg()
        if fg and fg.pid in {w.pid for w in wins} and fg.hwnd not in {w.hwnd for w in wins}:
            return Outcome(UNVERIFIED, f"{fg.title}: the app is asking something (unsaved changes?)",
                           {"dialog": fg.title})
        return Outcome(FAILED, f"{names} did not close", {"hwnds": [w.hwnd for w in wins]})

    def show_desktop(self, cancel) -> Outcome:
        send_combo("win+d")
        done = W.wait_for(lambda: W.class_name(W.foreground_hwnd()) in ("WorkerW", "Progman"), 1.5, cancel=cancel)
        return Outcome(VERIFIED if done else UNVERIFIED, "Showing the desktop")

    def list_windows(self, cancel) -> Outcome:
        ws = W.list_windows()
        names = [w.title if len(w.title) < 40 else w.title[:37] + "…" for w in ws]
        msg = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
        return Outcome(VERIFIED, msg or "No windows are open", {"windows": [w.describe() for w in ws]})

    # browser -----------------------------------------------------------------------------
    def open_url(self, url: str, browser: str, cancel, expect_words: list[str] | None = None) -> Outcome:
        if not re.match(r"^[a-z]+://", url):
            url = "https://" + url
        before = {w.hwnd: w.title for w in W.list_windows() if w.process.lower() in BROWSER_EXES}
        exe = find_browser_exe(browser or self.s.preferred_browser) if (browser or self.s.preferred_browser) else None
        if exe:
            subprocess.Popen([exe, url], close_fds=True)
        else:
            os.startfile(url)  # system default browser
        words = [w for w in (expect_words or []) if len(w) >= 3]

        def navigated():
            for w in W.list_windows():
                if w.process.lower() not in BROWSER_EXES:
                    continue
                if before.get(w.hwnd) == w.title:
                    continue
                if not words or any(t in w.title.lower() for t in words):
                    return w
            return None

        win = W.wait_for(navigated, self.s.step_timeout_s, interval_s=0.1, cancel=cancel)
        if win:
            return Outcome(VERIFIED, f"Opened {url}", {"title": win.title, "browser": win.process})
        if exe is None and not before and not any(w.process.lower() in BROWSER_EXES for w in W.list_windows()):
            return Outcome(UNVERIFIED, f"Sent {url} to the default browser (not a browser I can observe)", {"url": url})
        return Outcome(UNVERIFIED, f"Sent {url} to the browser; could not confirm the page loaded", {"url": url})

    def web_search(self, query: str, site: str, browser: str, cancel) -> Outcome:
        url = SEARCH_URLS[site or "web"].format(q=quote_plus(query))
        from .nlu.text import strip_accents

        words = [strip_accents(t).lower() for t in query.split()][:3]
        site_word = {"youtube": "youtube", "wikipedia": "wiki", "maps": "maps"}.get(site or "web")
        out = self.open_url(url, browser, cancel, expect_words=words + ([site_word] if site_word else []))
        if out.verification != FAILED:
            label = {"youtube": "YouTube", "wikipedia": "Wikipedia", "maps": "Maps"}.get(site, "the web")
            out.message = f"Searched {label} for “{query}”"
        return out

    def browser_op(self, op: str, cancel) -> Outcome:
        fg = _fg()
        if not fg or fg.process.lower() not in BROWSER_EXES:
            browsers = [w for w in W.list_windows() if w.process.lower() in BROWSER_EXES]
            if not browsers:
                return Outcome(FAILED, "No browser window is open")
            W.activate(browsers[0].hwnd)
            if not W.wait_for(lambda: W.foreground_hwnd() == browsers[0].hwnd, 1.0, cancel=cancel):
                return Outcome(FAILED, "Could not bring the browser to the front")
            fg = browsers[0]
        combo = {"new_tab": "ctrl+t", "close_tab": "ctrl+w", "next_tab": "ctrl+tab", "prev_tab": "ctrl+shift+tab",
                 "back": "alt+left", "forward": "alt+right", "reload": "f5"}[op]
        send_combo(combo)
        if op == "reload":
            return Outcome(UNVERIFIED, "Reloaded the page", {"title": fg.title})
        changed = _title_changed(fg.hwnd, fg.title, 1.5, cancel)
        label = op.replace("_", " ")
        if changed or (op == "close_tab" and not W.exists(fg.hwnd)):
            return Outcome(VERIFIED, label.capitalize(), {"before": fg.title, "after": changed})
        return Outcome(UNVERIFIED, f"Sent {label}; the page title did not change", {"title": fg.title})

    # keyboard ----------------------------------------------------------------------------
    def press(self, keys: str, cancel) -> Outcome:
        fg = _fg()
        if not send_combo(keys):
            return Outcome(FAILED, f"Could not send {keys} (the active window may be elevated)")
        return Outcome(UNVERIFIED, f"Pressed {keys}", {"window": fg.title if fg else ""})

    def edit(self, op: str, cancel) -> Outcome:
        combo = {"copy": "ctrl+c", "paste": "ctrl+v", "cut": "ctrl+x", "undo": "ctrl+z", "redo": "ctrl+y",
                 "select_all": "ctrl+a", "save": "ctrl+s"}[op]
        fg = _fg()
        seq = clipboard_seq()
        if not send_combo(combo):
            return Outcome(FAILED, f"Could not send {combo}")
        if op in ("copy", "cut"):
            if W.wait_for(lambda: clipboard_seq() != seq, 1.0, cancel=cancel):
                return Outcome(VERIFIED, "Copied to the clipboard" if op == "copy" else "Cut to the clipboard")
            return Outcome(FAILED, "Nothing was copied (is anything selected?)")
        if op == "save" and fg:
            def saved():
                info = W.window_info(fg.hwnd)
                new_fg = _fg()
                if info and info.title != fg.title and "*" in fg.title and "*" not in info.title:
                    return "saved"
                if new_fg and new_fg.hwnd != fg.hwnd and new_fg.pid == fg.pid:
                    return "dialog"
                return None
            result = W.wait_for(saved, 1.5, cancel=cancel)
            if result == "saved":
                return Outcome(VERIFIED, "Saved", {"title": fg.title})
            if result == "dialog":
                return Outcome(UNVERIFIED, "A save dialog opened — choose where to save", {"title": fg.title})
        return Outcome(UNVERIFIED, op.replace("_", " ").capitalize(), {"window": fg.title if fg else ""})

    def type_text(self, text: str, cancel) -> Outcome:
        res = self.injector.inject(text)
        if not res.ok:
            return Outcome(FAILED, f"Could not type into the active window: {res.error}")
        return Outcome(UNVERIFIED, f"Typed “{text[:40]}”", {"app": res.target_app, "method": res.method})

    def scroll(self, direction: str, amount: str, cancel) -> Outcome:
        scroll_wheel(direction, {"small": 3, "page": 8, "large": 15}.get(amount or "page", 8))
        return Outcome(UNVERIFIED, f"Scrolled {direction}")

    # system ------------------------------------------------------------------------------
    def volume(self, op: str, level: int | None, cancel) -> Outcome:
        from .world import audio

        try:
            before = audio.get_state()
            if op == "mute":
                audio.set_mute(True)
            elif op == "unmute":
                audio.set_mute(False)
            elif op == "set":
                audio.set_volume(int(level or 0))
            else:
                audio.step_volume(10 if op == "up" else -10)
            after = audio.get_state()
        except Exception as exc:
            send_combo({"mute": "volume_mute", "unmute": "volume_mute", "up": "volume_up", "down": "volume_down"}
                       .get(op, "volume_mute"))
            return Outcome(UNVERIFIED, f"Sent a volume key (audio API unavailable: {exc})")
        expect = {"mute": after[1], "unmute": not after[1], "set": after[0] == max(0, min(100, int(level or 0))),
                  "up": after[0] > before[0] or after[0] == 100, "down": after[0] < before[0] or after[0] == 0}[op]
        msg = "Muted" if after[1] else f"Volume {after[0]}%"
        return Outcome(VERIFIED if expect else FAILED, msg, {"before": before, "after": after})

    def media(self, op: str, cancel) -> Outcome:
        send_combo({"play_pause": "media_play_pause", "next": "media_next", "previous": "media_prev"}[op])
        return Outcome(UNVERIFIED, {"play_pause": "Play/pause", "next": "Next track", "previous": "Previous track"}[op])

    # files -------------------------------------------------------------------------------
    def open_path(self, path: Path, label: str, cancel) -> Outcome:
        before = {w.hwnd: w.title for w in W.list_windows()}
        os.startfile(str(path))
        stem = path.stem.lower() if path.is_file() else ""

        def opened():
            for w in W.list_windows():
                if before.get(w.hwnd) == w.title:
                    continue
                if (stem and stem[:20] in w.title.lower()) or (not stem and w.process.lower() == "explorer.exe"):
                    return w
            return None

        win = W.wait_for(opened, self.s.step_timeout_s, interval_s=0.1, cancel=cancel)
        if win:
            return Outcome(VERIFIED, f"Opened {label}", {"path": str(path), "title": win.title})
        return Outcome(UNVERIFIED, f"Asked Windows to open {label}", {"path": str(path)})

    # shell -------------------------------------------------------------------------------
    def run_command(self, argv: list[str], cancel) -> Outcome:
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=15, cwd=str(Path.home()),
                                  creationflags=subprocess.CREATE_NO_WINDOW, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return Outcome(FAILED, f"{' '.join(argv)} timed out")
        except FileNotFoundError:
            return Outcome(FAILED, f"{argv[0]} is not installed")
        out = (proc.stdout or proc.stderr or "").strip()
        first = out.splitlines()[0][:100] if out else "(no output)"
        verdict = VERIFIED if proc.returncode == 0 else FAILED
        return Outcome(verdict, first, {"exit_code": proc.returncode, "output": out[:4000], "argv": argv})

    # UI automation -----------------------------------------------------------------------
    def click(self, label: str, cancel) -> Outcome:
        from .world.uia import click_named

        fg = _fg()
        if not fg:
            return Outcome(FAILED, "No active window")
        result = click_named(fg.hwnd, label, budget_s=2.5, cancel=cancel)
        if result is None:
            return Outcome(FAILED, f"No button or link called “{label}” in {fg.title}")
        name, ctype, method = result
        changed = _title_changed(fg.hwnd, fg.title, 1.0, cancel) or (W.foreground_hwnd() != fg.hwnd)
        return Outcome(VERIFIED if changed else UNVERIFIED, f"Clicked “{name}”",
                       {"control": ctype, "method": method, "window": fg.title})

