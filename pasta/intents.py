"""The finite, typed action space of PASTA.

Everything PASTA can do is listed here with its parameters, risk level and
required permission. The grammar, the optional LLM parser, the planner, the
safety policy and the UI all read this one table, so a model can never
propose an action (or an argument) that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Risk(IntEnum):
    READ = 0  # observes only
    LOW = 1  # easily reversible, no data at stake (focus, open, scroll, volume)
    MEDIUM = 2  # sends input / may lose state (type, keys, click, close tab/window)
    HIGH = 3  # runs programs with output / broad effects (shell)


@dataclass(frozen=True)
class ActionInfo:
    name: str
    params: dict[str, str]  # name -> "str" | "int" | "enum:a|b|c"; suffix "?" = optional
    risk: Risk
    permission: str
    summary: str  # for humans and for the LLM prompt


ACTIONS: dict[str, ActionInfo] = {a.name: a for a in [
    ActionInfo("open", {"target": "str"}, Risk.LOW, "apps",
               "Open an app, folder or website by name; focuses it if already open"),
    ActionInfo("focus", {"target": "str"}, Risk.LOW, "windows", "Bring an open window to the front"),
    ActionInfo("close", {"target": "str?"}, Risk.MEDIUM, "windows", "Close a window (default: the active one)"),
    ActionInfo("minimize", {"target": "str?"}, Risk.LOW, "windows", "Minimize a window (default: active)"),
    ActionInfo("maximize", {"target": "str?"}, Risk.LOW, "windows", "Maximize a window (default: active)"),
    ActionInfo("restore", {"target": "str?"}, Risk.LOW, "windows", "Restore a minimized/maximized window"),
    ActionInfo("show_desktop", {}, Risk.LOW, "windows", "Minimize all windows / show the desktop"),
    ActionInfo("list_windows", {}, Risk.READ, "windows", "Say which windows are open"),
    ActionInfo("open_url", {"url": "str", "browser": "str?"}, Risk.LOW, "browser", "Open a web address"),
    ActionInfo("web_search", {"query": "str", "site": "enum:web|youtube|wikipedia|maps?", "browser": "str?"},
               Risk.LOW, "browser", "Search the web, YouTube, Wikipedia or Maps"),
    ActionInfo("browser", {"op": "enum:new_tab|close_tab|next_tab|prev_tab|back|forward|reload"}, Risk.LOW,
               "browser", "Browser navigation in the active browser window"),
    ActionInfo("press", {"keys": "str"}, Risk.MEDIUM, "keyboard", "Press a key or shortcut, e.g. 'enter', 'ctrl+s'"),
    ActionInfo("edit", {"op": "enum:copy|paste|cut|undo|redo|select_all|save"}, Risk.MEDIUM, "keyboard",
               "Clipboard/editing command in the active app"),
    ActionInfo("type_text", {"text": "str"}, Risk.MEDIUM, "keyboard", "Type literal text into the active app"),
    ActionInfo("scroll", {"direction": "enum:up|down", "amount": "enum:small|page|large?"}, Risk.LOW, "keyboard",
               "Scroll the active window"),
    ActionInfo("volume", {"op": "enum:mute|unmute|up|down|set", "level": "int?"}, Risk.LOW, "system",
               "Change the system volume"),
    ActionInfo("media", {"op": "enum:play_pause|next|previous"}, Risk.LOW, "system", "Media playback keys"),
    ActionInfo("open_folder", {"folder": "enum:downloads|documents|desktop|pictures|music|videos|home"}, Risk.LOW,
               "files", "Open a standard folder"),
    ActionInfo("find_file", {"query": "str"}, Risk.LOW, "files",
               "Find a file by name in the user folders and open it"),
    ActionInfo("click", {"label": "str"}, Risk.MEDIUM, "ui_click", "Click a named button/link in the active window"),
    ActionInfo("run_command", {"command": "str"}, Risk.HIGH, "shell", "Run an allow-listed terminal command"),
    ActionInfo("stop", {}, Risk.READ, "windows", "Cancel what PASTA is doing"),
]}


@dataclass
class Intent:
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # how sure the *parser* is
    source: str = "grammar"  # grammar | llm
    text: str = ""  # the clause it came from

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "args": self.args, "confidence": round(self.confidence, 3),
                "source": self.source}


def validate(intent: Intent) -> str | None:
    """Return an error message if the intent does not fit the action table."""
    info = ACTIONS.get(intent.action)
    if info is None:
        return f"unknown action {intent.action!r}"
    for key in intent.args:
        if key not in info.params:
            return f"{intent.action}: unexpected argument {key!r}"
    for key, spec in info.params.items():
        optional = spec.endswith("?")
        spec = spec.rstrip("?")
        value = intent.args.get(key)
        if value in (None, ""):
            if not optional:
                return f"{intent.action}: missing {key}"
            continue
        if spec == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                return f"{intent.action}: {key} must be an integer"
        elif spec.startswith("enum:"):
            if value not in spec[5:].split("|"):
                return f"{intent.action}: {key} must be one of {spec[5:]}"
        elif not isinstance(value, str):
            return f"{intent.action}: {key} must be text"
    return None
