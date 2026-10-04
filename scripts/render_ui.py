"""Render the HUD in every state, plus the dashboard, to PNG files (offscreen).

    python scripts/render_ui.py [out_dir]

No hooks, microphone or focus changes: safe to run anywhere, and used to
produce the screenshots in docs/. Dashboard numbers come from the real
telemetry database of the configured PESTO home (empty on a fresh install).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from pesto.events import Phase, Preview, Status  # noqa: E402
from pesto.ui import theme  # noqa: E402
from pesto.ui.hud import Hud  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img")
STATES = [
    ("listening", [Status(Phase.LISTENING, "a", "Ελληνικά · English"), Preview("a", "Η μελέτη συγκρίνει την υπαγόρευση με το πληκτρολόγιο")], 0.55),
    ("transcribing", [Status(Phase.TRANSCRIBING, "a", "Transcribing")], 0),
    ("done", [Status(Phase.DONE, "a", "Η μελέτη συγκρίνει την υπαγόρευση με το πληκτρολόγιο.", "286 ms")], 0),
    ("empty", [Status(Phase.EMPTY, "a", "No speech detected")], 0),
    ("failed", [Status(Phase.FAILED, "a", "Could not type into the active window", "target is elevated")], 0),
    ("command-running", [Status(Phase.EXECUTING, "b", "Open Google Chrome", "1/2", {"command": True, "steps": [
        {"label": "Open Google Chrome", "state": "running"},
        {"label": "Search YouTube for “Χατζιδάκις”", "state": "pending"}]})], 0),
    ("command-confirm", [Status(Phase.CONFIRM, "c", "Close 2 chrome windows?", "Closing a window — please confirm",
                                {"command": True, "steps": [{"label": "Close 2 chrome windows", "state": "confirm",
                                                             "hint": "Enter ⏎ run · Esc cancel"}]})], 0),
    ("command-done", [Status(Phase.DONE, "d", "Searched YouTube for “Χατζιδάκις”", "1.4 s", {"command": True, "steps": [
        {"label": "Opened Google Chrome", "state": "done"},
        {"label": "Searched YouTube for “Χατζιδάκις”", "state": "done"}]})], 0),
]


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":  # offscreen has no system font database
        from PySide6.QtGui import QFontDatabase

        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for f in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "SegUIVar.ttf", "seguisym.ttf", "seguiemj.ttf"):
            if (fonts / f).exists():
                QFontDatabase.addApplicationFont(str(fonts / f))
    app.setStyleSheet(theme.STYLESHEET)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, events, level in STATES:
        hud = Hud()
        for ev in events:
            (hud.on_preview if isinstance(ev, Preview) else hud.on_status)(ev)
        if level:
            for _ in range(30):
                hud.on_level(level)
                hud._frame()
        t = time.perf_counter()
        while time.perf_counter() - t < 0.35:  # let width/fade/check animations settle
            app.processEvents()
            hud._frame()
        hud.grab().save(str(OUT / f"hud-{name}.png"))
        hud.close()
    if "--dashboard" in sys.argv:
        from pesto.app import PestoApp
        from pesto.ui.dashboard import Dashboard

        pesto = PestoApp(telemetry=True)
        dash = Dashboard(pesto, "PESTO", "Local push-to-talk speech input · Ελληνικά & English")
        dash.resize(1060, 700)
        dash.show()
        dash.refresh()
        for i in range(dash.nav.count()):
            dash.nav.setCurrentRow(i)
            app.processEvents()
            dash.grab().save(str(OUT / f"dashboard-{dash.nav.item(i).text().lower()}.png"))
        pesto.telemetry.close()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
