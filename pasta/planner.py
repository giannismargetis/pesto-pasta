"""Grounding: turn an :class:`Intent` into an executable :class:`Step`.

Grounding happens right before each step runs, against a fresh observation
of the desktop, so later steps see the effects of earlier ones. The step's
confidence is ``parse confidence × grounding score``; the safety policy turns
that into run / ask / refuse.
"""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .executors import VK, Executors, Outcome
from .intents import ACTIONS, Intent, Risk
from .nlu.grammar import FOLDERS
from .nlu.text import find_domain, norm, similarity
from .shell import to_argv
from .world import windows as W
from .world.apps import ALIASES, AppIndex
from .world.sites import SITES

FOLDER_IDS = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}", "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}", "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "home": "{5E6C858F-0E22-4760-9AFE-EA3317B67173}",
}
# Below this, a fuzzy app-name match is more likely a wrong app than the right
# one (e.g. "spotify" ~ "Support by e-mail" = 0.65); report "not found" instead.
MIN_APP_SCORE = 0.75

FOLDER_LABELS = {"downloads": "Downloads", "documents": "Documents", "desktop": "Desktop", "pictures": "Pictures",
                 "music": "Music", "videos": "Videos", "home": "your user folder"}


@dataclass
class Step:
    intent: Intent
    label: str
    run: Callable[[object], Outcome]
    risk: Risk
    permission: str
    confidence: float
    note: str = ""
    evidence: dict = field(default_factory=dict)


class GroundingError(Exception):
    pass


def known_folder(name: str) -> Path:
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    import uuid

    u = uuid.UUID(FOLDER_IDS[name])
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    ptr = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ptr)) == 0:
        path = Path(ptr.value)
        ctypes.windll.ole32.CoTaskMemFree(ptr)
        return path
    return Path.home() / FOLDER_LABELS[name]


def match_windows(query: str, wins: list[W.Window], apps: AppIndex | None = None) -> list[tuple[W.Window, float]]:
    q = norm(query)
    alias = ALIASES.get(q, "")
    alias_name = norm(alias) if alias and not alias.startswith(("exe:", "uri:")) else ""
    alias_exe = alias[4:].lower() if alias.startswith("exe:") else ""
    out = []
    for w in wins:
        title = norm(w.title)
        s = max(similarity(query, w.app), similarity(query, w.title) * 0.9)
        if q and (f" {q} " in f" {title} " or title.endswith(q)):
            s = max(s, 0.9 if len(q) >= 3 else 0.7)
        if alias_name and alias_name in title:
            s = max(s, 0.95)
        if alias_exe and w.process.lower() == alias_exe:
            s = max(s, 0.97)
        out.append((w, min(s, 1.0)))
    out.sort(key=lambda p: p[1], reverse=True)
    return out


def find_files(query: str, budget_s: float = 2.0, max_entries: int = 40000) -> list[tuple[Path, float]]:
    roots = [known_folder(n) for n in ("desktop", "documents", "downloads")]
    q = norm(Path(query).stem if "." in query else query)
    ext = Path(query).suffix.lower() if "." in query else ""
    deadline = time.perf_counter() + budget_s
    results: list[tuple[Path, float]] = []
    seen = 0
    for root in roots:
        stack = [(root, 0)]
        while stack and time.perf_counter() < deadline and seen < max_entries:
            folder, depth = stack.pop()
            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        seen += 1
                        if entry.name.startswith((".", "$", "~")):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if depth < 5 and entry.name.lower() not in ("node_modules", "venv", ".git", "__pycache__"):
                                stack.append((Path(entry.path), depth + 1))
                            continue
                        stem = norm(Path(entry.name).stem)
                        if ext and Path(entry.name).suffix.lower() != ext:
                            continue
                        s = 1.0 if stem == q else (0.88 if q and q in stem else similarity(q, stem))
                        if s >= 0.6:
                            results.append((Path(entry.path), s))
            except OSError:
                continue
    results.sort(key=lambda r: (r[1], r[0].stat().st_mtime if r[0].exists() else 0), reverse=True)
    return results[:5]


class Planner:
    def __init__(self, executors: Executors, apps: AppIndex, settings, permissions) -> None:
        self.x = executors
        self.apps = apps
        self.s = settings
        self.perm = permissions

    # Human-readable label before grounding (shown in the HUD plan list)
    @staticmethod
    def describe(intent: Intent) -> str:
        a = intent.args
        return {
            "open": lambda: f"Open {a.get('target', '')}",
            "focus": lambda: f"Switch to {a.get('target', '')}",
            "close": lambda: f"Close {a.get('target') or 'the active window'}",
            "minimize": lambda: f"Minimize {a.get('target') or 'the active window'}",
            "maximize": lambda: f"Maximize {a.get('target') or 'the active window'}",
            "restore": lambda: f"Restore {a.get('target') or 'the active window'}",
            "show_desktop": lambda: "Show the desktop",
            "list_windows": lambda: "List open windows",
            "open_url": lambda: f"Open {a.get('url', '')}",
            "web_search": lambda: {"youtube": "Search YouTube for", "wikipedia": "Search Wikipedia for",
                                   "maps": "Find on Maps:"}.get(a.get("site", "web"), "Search the web for")
            + f" “{a.get('query', '')}”",
            "browser": lambda: {"new_tab": "New tab", "close_tab": "Close tab", "next_tab": "Next tab",
                                "prev_tab": "Previous tab", "back": "Go back", "forward": "Go forward",
                                "reload": "Reload page"}[a["op"]],
            "press": lambda: "Press " + "+".join(k.capitalize() for k in a.get("keys", "").split("+")),
            "edit": lambda: {"copy": "Copy", "paste": "Paste", "cut": "Cut", "undo": "Undo", "redo": "Redo",
                             "select_all": "Select all", "save": "Save"}[a["op"]],
            "type_text": lambda: f"Type “{a.get('text', '')[:40]}”",
            "scroll": lambda: f"Scroll {a.get('direction', 'down')}",
            "volume": lambda: {"mute": "Mute", "unmute": "Unmute", "up": "Volume up", "down": "Volume down",
                               "set": f"Set volume to {a.get('level')}%"}[a["op"]],
            "media": lambda: {"play_pause": "Play / pause", "next": "Next track", "previous": "Previous track"}[a["op"]],
            "open_folder": lambda: f"Open {FOLDER_LABELS.get(a.get('folder', ''), a.get('folder', ''))}",
            "find_file": lambda: f"Find and open “{a.get('query', '')}”",
            "click": lambda: f"Click “{a.get('label', '')}”",
            "run_command": lambda: f"Run `{a.get('command', '')}`",
            "stop": lambda: "Stop",
        }[intent.action]()

    def ground(self, intent: Intent) -> Step:
        info = ACTIONS[intent.action]
        a, p = intent.args, intent.confidence

        def step(label: str, run, conf: float = 1.0, risk: Risk | None = None, note: str = "") -> Step:
            return Step(intent, label, run, risk if risk is not None else info.risk, info.permission,
                        round(p * conf, 3), note)

        act = intent.action
        if act in ("open", "focus"):
            return self._ground_open(intent, step, focus_only=act == "focus")
        if act in ("close", "minimize", "maximize", "restore"):
            target = a.get("target", "")
            if target:
                wins = [w for w, s in match_windows(target, W.list_windows(), self.apps) if s >= 0.75]
                if not wins:
                    raise GroundingError(f"No open window matches “{target}”")
                score = match_windows(target, wins)[0][1]
            else:
                fg = W.window_info(W.foreground_hwnd())
                if fg is None or W.class_name(fg.hwnd) in ("WorkerW", "Progman", "Shell_TrayWnd"):
                    raise GroundingError("There is no active window")
                wins, score = [fg], 1.0
            if act == "close":
                same_app = [w for w in wins if w.process == wins[0].process] if target else wins
                n = len(same_app)
                label = f"Close {same_app[0].title}" if n == 1 else f"Close {n} {same_app[0].app} windows"
                return step(label, lambda c: self.x.close(same_app, c), score,
                            risk=Risk.MEDIUM if n == 1 else Risk.HIGH)
            w = wins[0]
            return step(f"{act.capitalize()} {w.title}", lambda c: self.x.window_state(w, act, c), score)
        if act == "show_desktop":
            return step("Show the desktop", self.x.show_desktop)
        if act == "list_windows":
            return step("List open windows", self.x.list_windows)
        if act == "open_url":
            url = a["url"]
            return step(f"Open {url}", lambda c: self.x.open_url(url, a.get("browser", ""), c,
                                                                    [url.split("//")[-1].split(".")[0]
                                                                     if "." in url else url]))
        if act == "web_search":
            return step(self.describe(intent), lambda c: self.x.web_search(a["query"], a.get("site", "web"),
                                                                          a.get("browser", ""), c))
        if act == "browser":
            return step(self.describe(intent), lambda c: self.x.browser_op(a["op"], c),
                        risk=Risk.MEDIUM if a["op"] == "close_tab" else None)
        if act == "press":
            keys = a["keys"].lower()
            if any(k not in VK for k in keys.split("+")):
                raise GroundingError(f"Unknown key in “{a['keys']}”")
            risky = keys in ("alt+f4", "ctrl+w", "ctrl+shift+w", "ctrl+q")
            return step(self.describe(intent), lambda c: self.x.press(keys, c),
                        risk=Risk.HIGH if risky else None)
        if act == "edit":
            return step(self.describe(intent), lambda c: self.x.edit(a["op"], c),
                        risk=Risk.LOW if a["op"] in ("copy", "select_all") else None)
        if act == "type_text":
            return step(self.describe(intent), lambda c: self.x.type_text(a["text"], c))
        if act == "scroll":
            return step(self.describe(intent), lambda c: self.x.scroll(a["direction"], a.get("amount", "page"), c))
        if act == "volume":
            return step(self.describe(intent), lambda c: self.x.volume(a["op"], a.get("level"), c))
        if act == "media":
            return step(self.describe(intent), lambda c: self.x.media(a["op"], c))
        if act == "open_folder":
            folder = known_folder(a["folder"])
            return step(f"Open {FOLDER_LABELS[a['folder']]}", lambda c: self.x.open_path(folder, folder.name, c))
        if act == "find_file":
            hits = find_files(a["query"])
            if not hits:
                raise GroundingError(f"No file matching “{a['query']}” in Desktop, Documents or Downloads")
            path, score = hits[0]
            ambiguous = len(hits) > 1 and hits[1][1] >= score - 0.02 and score < 1.0
            return step(f"Open {path.name}", lambda c: self.x.open_path(path, path.name, c),
                        score * (0.85 if ambiguous else 1.0), note=str(path))
        if act == "click":
            return step(self.describe(intent), lambda c: self.x.click(a["label"], c))
        if act == "run_command":
            argv = to_argv(a["command"])
            if argv is None:
                raise GroundingError(f"“{a['command']}” is not in the allowed command list")
            return step(f"Run `{' '.join(argv[2:] if argv[:2] == ['cmd', '/c'] else argv)}`",
                        lambda c: self.x.run_command(argv, c))
        raise GroundingError(f"Unsupported action {act}")

    def _ground_open(self, intent: Intent, step, focus_only: bool) -> Step:
        target = intent.args.get("target", "").strip()
        browser = intent.args.get("browser", "")
        t = norm(target)
        if t in FOLDERS:
            folder = known_folder(FOLDERS[t])
            return step(f"Open {FOLDER_LABELS[FOLDERS[t]]}", lambda c: self.x.open_path(folder, folder.name, c))
        wins = match_windows(target, W.list_windows(), self.apps)
        if wins and wins[0][1] >= (0.75 if focus_only else 0.85) and not (t in SITES and browser):
            w, s = wins[0]
            return step(f"Switch to {w.title}", lambda c: self.x.focus(w, c), s)
        domain = find_domain(target)
        if t in SITES or domain:
            url = SITES.get(t) or domain
            name = target if t in SITES else domain
            return step(f"Open {name}", lambda c: self.x.open_url(url, browser, c, [t.split()[0]] if t in SITES
                                                                   else [domain.split(".")[0]]))
        matches = self.apps.find(target)
        if matches and matches[0].score >= MIN_APP_SCORE:
            best = matches[0]
            conf = best.score
            note = ""
            if len(matches) > 1 and matches[1].score >= best.score - 0.03 and best.score < 1.0:
                conf *= 0.85
                note = f"also matches {matches[1].app.name}"
            prefix = "" if not focus_only else f"{target} isn't open — "
            app = best.app
            return step(f"{prefix}Open {app.name}", lambda c: self.x.launch(app, c),
                        conf * (0.95 if focus_only else 1.0), note=note)
        raise GroundingError(f"I couldn't find an app, window or website called “{target}”")

