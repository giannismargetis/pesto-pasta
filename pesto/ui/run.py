"""Qt bootstrap: the GUI thread owns HUD, tray and dashboard; everything else
runs on worker threads and reaches the GUI through :class:`UiBridge`."""

from __future__ import annotations

import signal
import sys

from ..app import PestoApp
from ..log import get_logger

log = get_logger("ui")


def run_gui(app: PestoApp, product: str = "PESTO", subtitle: str = "", show_dashboard: bool = False,
            ui_hooks: list | None = None) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from . import theme
    from .bridge import UiBridge
    from .dashboard import Dashboard
    from .hud import Hud
    from .tray import Tray

    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setApplicationName(product)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setStyleSheet(theme.STYLESHEET)

    bridge = UiBridge(app.bus)
    dashboard = Dashboard(app, product, subtitle)
    hud = Hud(app.cfg.ui.hud_position) if app.cfg.ui.hud else None

    def open_dashboard() -> None:
        dashboard.show()
        dashboard.raise_()
        dashboard.activateWindow()
        dashboard.refresh()

    def quit_app() -> None:
        tray.hide()
        qapp.quit()

    tray = Tray(app, open_dashboard, quit_app, product)
    tray.show()

    if hud is not None:
        bridge.status.connect(hud.on_status)
        bridge.preview.connect(hud.on_preview)
        bridge.level.connect(hud.on_level)
    bridge.status.connect(tray.on_status)
    bridge.settings.connect(tray.on_settings)
    bridge.status.connect(dashboard.on_status)
    bridge.settings.connect(dashboard.on_settings)

    ui = {"app": app, "qapp": qapp, "bridge": bridge, "dashboard": dashboard, "hud": hud, "tray": tray}
    for hook in ui_hooks or []:
        hook(ui)

    app.start()
    if show_dashboard or app.cfg.ui.start_dashboard:
        open_dashboard()

    # Let Ctrl+C in the console stop the app (Qt otherwise swallows SIGINT).
    signal.signal(signal.SIGINT, lambda *_: qapp.quit())
    pulse = QTimer(interval=250, timeout=lambda: None)
    pulse.start()
    try:
        return qapp.exec()
    finally:
        app.stop()
