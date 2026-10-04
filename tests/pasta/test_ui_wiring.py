"""PASTA's UI hooks run before app.start() (i.e. before the extension is attached).
Regression test for a launch crash found by the GUI smoke test."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


def test_pasta_ui_hook_runs_before_attach(tmp_path):
    from PySide6.QtWidgets import QApplication

    from pasta.extension import PastaExtension
    from pasta.ui import install
    from pesto.app import PestoApp
    from pesto.config import Config
    from pesto.ui.bridge import UiBridge
    from pesto.ui.dashboard import Dashboard
    from pesto.ui.tray import Tray

    QApplication.instance() or QApplication([])
    ext = PastaExtension()
    app = PestoApp(Config(tmp_path / "c.json"), extensions=[ext], telemetry=False)
    assert ext.app is None  # not attached yet, exactly as in run_gui
    ui = {"app": app, "bridge": UiBridge(app.bus), "dashboard": Dashboard(app), "hud": None,
          "tray": Tray(app, lambda: None, lambda: None, "PASTA")}
    install(ext)(ui)
    pages = [ui["dashboard"].nav.item(i).text() for i in range(ui["dashboard"].nav.count())]
    assert "Commands" in pages
