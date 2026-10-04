"""PASTA additions to the PESTO UI: mode menu, Commands page, settings card."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from pesto.ui.dashboard import card, label, query

from .extension import MODE_LABELS, MODES, PastaExtension

STATUS_LABEL = {"completed": "✓ completed", "failed": "✗ failed", "cancelled": "cancelled", "declined": "declined",
                "rejected": "refused", "not_understood": "not understood", "stopped": "stopped"}


def install(ext: PastaExtension):
    def hook(ui: dict) -> None:
        app = ext.app
        tray = ui["tray"]
        menu = tray.add_menu("Mode")
        group = QActionGroup(menu)
        actions = {}
        for mode in MODES:
            a = QAction(MODE_LABELS[mode], menu, checkable=True)
            a.triggered.connect(lambda _=False, m=mode: ext.set_mode(m))
            group.addAction(a)
            menu.addAction(a)
            actions[mode] = a
        ui["bridge"].settings.connect(lambda s: actions.get(app.cfg.agent.mode) and
                                      actions[app.cfg.agent.mode].setChecked(True))
        actions.get(app.cfg.agent.mode, actions["hybrid"]).setChecked(True)

        dash = ui["dashboard"]
        page = CommandsPage()
        dash.add_page("Commands", page, index=2)
        dash.nav.currentRowChanged.connect(lambda i: page.reload() if dash.nav.item(i) and
                                           dash.nav.item(i).text() == "Commands" else None)
        ui["bridge"].status.connect(lambda st: QTimer.singleShot(400, page.reload)
                                    if st.data.get("command") and page.isVisible() else None)
        widget, saver = settings_card(app)
        dash.settings_page.add_section(widget, saver)
    return hook


class CommandsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(12)
        lay.addWidget(label("Commands", "h1"))
        lay.addWidget(label("Every command PASTA ran, with what it did and whether the effect was verified.",
                            "muted", wrap=True))
        row = QHBoxLayout()
        self.summary = label("", "muted")
        row.addWidget(self.summary)
        row.addStretch(1)
        lay.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Time", "You said", "Steps", "Result", "Duration"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

    def reload(self) -> None:
        rows = query("SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT 300")
        self.table.setRowCount(len(rows))
        done = sum(1 for r in rows if r["status"] == "completed")
        steps = sum(r["steps"] or 0 for r in rows)
        verified = sum(r["verified_steps"] or 0 for r in rows)
        if rows:
            self.summary.setText(f"{len(rows)} commands · {done / len(rows):.0%} completed · "
                                 f"{verified}/{steps} steps independently verified")
        for i, r in enumerate(rows):
            plan = json.loads(r["plan_json"] or "[]")
            marks = {"done": "✓", "unverified": "~", "failed": "✗", "skipped": "–", "confirm": "?"}
            plan_text = "  ".join(f"{marks.get(p['state'], '·')} {p['label']}" for p in plan)
            vals = [str(r["started_at"])[5:16].replace("T", " "), r["utterance"] or "", plan_text,
                    STATUS_LABEL.get(r["status"], r["status"] or ""),
                    f"{(r['total_ms'] or 0) / 1000:.1f} s"]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if j == 2:
                    item.setToolTip(plan_text.replace("  ", "\n"))
                if j == 4:
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                self.table.setItem(i, j, item)


def settings_card(app):
    c, cl = card()
    cl.addWidget(label("Commands (PASTA)", "h2"))
    cl.addWidget(label("In the default mode you dictate normally and address PASTA by name: “Pasta, open Chrome”. "
                       "Low-risk commands run immediately; anything that types, clicks, closes or runs a program "
                       "asks first unless PASTA is certain. Commands from the optional language model always ask.",
                       "muted", wrap=True))
    form = QFormLayout()
    cfg = app.cfg
    mode = QComboBox()
    for m in MODES:
        mode.addItem(MODE_LABELS[m], m)
    mode.setCurrentIndex(max(0, mode.findData(cfg.agent.mode)))
    wake = QLineEdit(", ".join(cfg.agent.wake_words))
    llm_on = QCheckBox("Use a local language model (Ollama) for commands the grammar doesn't understand")
    llm_on.setChecked(cfg.agent.llm_enabled)
    llm_model = QLineEdit(cfg.agent.llm_model)
    perms = {}
    for key, text in (("apps", "Open apps"), ("windows", "Manage windows"), ("browser", "Browser"),
                      ("keyboard", "Type and press keys"), ("system", "Volume and media"),
                      ("files", "Open files and folders"), ("ui_click", "Click buttons and links")):
        cb = QCheckBox(text)
        cb.setChecked(bool(getattr(cfg.permissions, key)))
        perms[key] = cb
    shell = QCheckBox("Allow-listed terminal commands (always asks)")
    shell.setChecked(cfg.permissions.shell == "allowlist")
    form.addRow("Mode", mode)
    form.addRow("Wake words", wake)
    form.addRow("", llm_on)
    form.addRow("LLM model", llm_model)
    perm_box = QWidget()
    pl = QVBoxLayout(perm_box)
    pl.setContentsMargins(0, 0, 0, 0)
    for cb in [*perms.values(), shell]:
        pl.addWidget(cb)
    form.addRow("Permissions", perm_box)
    cl.addLayout(form)

    def save() -> None:
        cfg.agent.mode = mode.currentData()
        app.session.mode_label = cfg.agent.mode
        cfg.agent.wake_words = [w.strip() for w in wake.text().split(",") if w.strip()]
        cfg.agent.llm_enabled = llm_on.isChecked()
        cfg.agent.llm_model = llm_model.text().strip()
        for key, cb in perms.items():
            setattr(cfg.permissions, key, cb.isChecked())
        cfg.permissions.shell = "allowlist" if shell.isChecked() else "none"

    return c, save


__all__ = ["install", "QLabel"]
