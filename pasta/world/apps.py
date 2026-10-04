"""Installed-application index (everything in the Start menu, desktop + Store).

``Get-StartApps`` returns display names (localised: this is how users refer
to apps) and AppIDs that ``explorer shell:AppsFolder\\<AppID>`` launches
uniformly. Enumeration takes ~1 s, so it is cached on disk and refreshed in
the background.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass

from pesto import paths
from pesto.log import get_logger

from ..nlu.text import norm, similarity

log = get_logger("pasta.apps")
CACHE = paths.DATA_DIR / "apps.json"
MAX_AGE_S = 24 * 3600

_JUNK = re.compile(r"\b(uninstall|readme|read me|help|license|manual|documentation|website|release notes|"
                   r"κατάργηση εγκατάστασης|απεγκατάσταση|βοήθεια)\b", re.IGNORECASE)

# Spoken name -> canonical command. Values starting with "exe:" launch a
# program on PATH, "uri:" a protocol URI; otherwise the value is matched
# against Start-menu names.
ALIASES = {
    "calculator": "exe:calc.exe", "calc": "exe:calc.exe", "αριθμομηχανη": "exe:calc.exe",
    "κομπιουτερακι": "exe:calc.exe",
    "notepad": "exe:notepad.exe", "σημειωματαριο": "exe:notepad.exe",
    "paint": "exe:mspaint.exe", "ζωγραφικη": "exe:mspaint.exe",
    "terminal": "exe:wt.exe", "τερματικο": "exe:wt.exe", "windows terminal": "exe:wt.exe",
    "command prompt": "exe:cmd.exe", "cmd": "exe:cmd.exe", "γραμμη εντολων": "exe:cmd.exe",
    "powershell": "exe:powershell.exe",
    "explorer": "exe:explorer.exe", "file explorer": "exe:explorer.exe", "εξερευνηση αρχειων": "exe:explorer.exe",
    "εξερευνητη": "exe:explorer.exe", "this pc": "exe:explorer.exe",
    "task manager": "exe:taskmgr.exe", "διαχειριση εργασιων": "exe:taskmgr.exe",
    "settings": "uri:ms-settings:", "ρυθμισεισ": "uri:ms-settings:",
    "control panel": "exe:control.exe", "πινακασ ελεγχου": "exe:control.exe",
    "vs code": "Visual Studio Code", "vscode": "Visual Studio Code", "code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code", "βι εσ κοουντ": "Visual Studio Code",
    "word": "Word", "excel": "Excel", "powerpoint": "PowerPoint", "outlook": "Outlook",
    "chrome": "Google Chrome", "google chrome": "Google Chrome", "κρομ": "Google Chrome", "κροουμ": "Google Chrome",
    "edge": "Microsoft Edge", "firefox": "Firefox", "spotify": "Spotify", "σποτιφαι": "Spotify",
    "discord": "Discord", "ντισκορντ": "Discord", "steam": "Steam", "στιμ": "Steam", "obsidian": "Obsidian",
}

# Executables we can verify by process name.
KNOWN_EXES = {"calc.exe": {"calculatorapp.exe", "applicationframehost.exe", "calc.exe"},
              "notepad.exe": {"notepad.exe"}, "mspaint.exe": {"mspaint.exe"},
              "wt.exe": {"windowsterminal.exe", "wt.exe"}, "cmd.exe": {"cmd.exe", "conhost.exe", "windowsterminal.exe"},
              "powershell.exe": {"powershell.exe", "conhost.exe", "windowsterminal.exe"},
              "explorer.exe": {"explorer.exe"}, "taskmgr.exe": {"taskmgr.exe"}, "control.exe": {"explorer.exe"}}


@dataclass(frozen=True)
class App:
    name: str
    app_id: str  # AppsFolder id, "exe:..." or "uri:..."

    @property
    def exe_hint(self) -> str:
        """Process name we expect after launch, if derivable."""
        if self.app_id.startswith("exe:"):
            return self.app_id[4:].lower()
        m = re.search(r"([^\\/]+\.exe)$", self.app_id, re.IGNORECASE)
        return m.group(1).lower() if m else ""

    def launch_command(self) -> list[str]:
        if self.app_id.startswith("exe:"):
            return ["cmd", "/c", "start", "", self.app_id[4:]]
        if self.app_id.startswith("uri:"):
            return ["cmd", "/c", "start", "", self.app_id[4:]]
        return ["explorer.exe", f"shell:AppsFolder\\{self.app_id}"]


@dataclass(frozen=True)
class Match:
    app: App
    score: float


class AppIndex:
    def __init__(self) -> None:
        self._apps: list[App] = []
        self._lock = threading.Lock()
        self._loaded = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._load, name="AppIndex", daemon=True).start()

    def _load(self) -> None:
        apps = self._read_cache()
        if apps:
            self._set(apps)
        if not apps or time.time() - CACHE.stat().st_mtime > MAX_AGE_S:
            fresh = enumerate_start_apps()
            if fresh:
                self._set(fresh)
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps([a.__dict__ for a in fresh], ensure_ascii=False), encoding="utf-8")
        self._loaded.set()

    def _set(self, apps: list[App]) -> None:
        with self._lock:
            self._apps = apps
        self._loaded.set()

    @staticmethod
    def _read_cache() -> list[App]:
        try:
            return [App(**d) for d in json.loads(CACHE.read_text(encoding="utf-8"))]
        except Exception:
            return []

    def wait(self, timeout: float = 3.0) -> bool:
        return self._loaded.wait(timeout)

    @property
    def apps(self) -> list[App]:
        with self._lock:
            return list(self._apps)

    def find(self, query: str, limit: int = 3) -> list[Match]:
        q = norm(query)
        if not q:
            return []
        alias = ALIASES.get(q)
        if alias and alias.startswith(("exe:", "uri:")):
            return [Match(App(query.strip().title(), alias), 1.0)]
        target = alias or query
        scored: list[Match] = []
        for app in self.apps:
            if _JUNK.search(app.name):
                continue
            s = similarity(target, app.name)
            nq, nn = norm(target), norm(app.name)
            if nq and (nn.startswith(nq + " ") or f" {nq} " in f" {nn} "):
                s = max(s, 0.86 if len(nq) >= 4 else 0.75)  # "spotify" ~ "Spotify Premium"
            if alias:
                s = min(1.0, s + 0.05)
            scored.append(Match(app, s))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:limit]


def enumerate_start_apps() -> list[App]:
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
           "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                             timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        data = json.loads(out.decode("utf-8-sig") or "[]")
    except Exception as exc:
        log.warning("Start menu enumeration failed: %s", exc)
        return []
    if isinstance(data, dict):
        data = [data]
    apps = [App(d["Name"], d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]
    log.info("Indexed %d Start menu apps", len(apps))
    return apps
