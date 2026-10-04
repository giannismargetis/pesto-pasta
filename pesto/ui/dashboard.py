"""Dashboard window: overview, history, settings, diagnostics (+ extension pages)."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QMainWindow, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTableView,
    QVBoxLayout, QWidget,
)

from .. import gpu, paths, telemetry
from ..events import Phase, Settings, Status
from . import theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("role", "card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)
    return f, lay


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    if not paths.DB_PATH.exists():
        return []
    try:
        conn = telemetry.connect(paths.DB_PATH, readonly=True)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []


class LatencyChart(QWidget):
    """Histogram of release->text latency with p50/p90 and perceptual bands."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(170)
        self.values = np.zeros(0)

    def set_values(self, values) -> None:
        self.values = np.asarray([v for v in values if v is not None], dtype=float)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -26)
        p.setFont(theme.ui_font(8.5))
        if self.values.size < 3:
            p.setPen(theme.TEXT_3)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Latency distribution appears after a few dictations")
            p.end()
            return
        hi = max(1500.0, float(np.percentile(self.values, 98)) * 1.1)
        bins = np.linspace(0, hi, 31)
        counts, _ = np.histogram(np.clip(self.values, 0, hi), bins)
        bw = r.width() / len(counts)
        top = counts.max() or 1
        # perceptual reference lines (Card/Miller/Nielsen): 100 ms "instant", 1 s "flow"
        for ms, name in ((100, "0.1 s"), (1000, "1 s")):
            if ms < hi:
                x = r.x() + r.width() * ms / hi
                p.setPen(QPen(theme.BORDER, 1, Qt.PenStyle.DashLine))
                p.drawLine(int(x), int(r.y()), int(x), int(r.bottom()))
                p.setPen(theme.TEXT_3)
                p.drawText(QRectF(x + 3, r.y(), 50, 14), Qt.AlignmentFlag.AlignLeft, name)
        p.setPen(Qt.PenStyle.NoPen)
        for i, c in enumerate(counts):
            h = r.height() * c / top
            col = theme.GREEN if bins[i + 1] <= 1000 else theme.AMBER
            col = theme.QColor(col)
            col.setAlpha(190)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(r.x() + i * bw + 1, r.bottom() - h, bw - 2, h), 2, 2)
        for q, name in ((50, "p50"), (90, "p90")):
            v = float(np.percentile(self.values, q))
            x = r.x() + r.width() * v / hi
            p.setPen(QPen(theme.TEXT, 1.2))
            p.drawLine(int(x), int(r.y() + 14), int(x), int(r.bottom()))
            p.drawText(QRectF(x - 40, r.bottom() + 4, 80, 16), Qt.AlignmentFlag.AlignCenter, f"{name} {v:.0f} ms")
        p.end()


class HistoryModel(QAbstractTableModel):
    COLS = ("Time", "Text", "Words", "Lang", "Engine", "Latency", "App", "Outcome")

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[sqlite3.Row] = []

    def load(self, search: str = "") -> None:
        self.beginResetModel()
        if search:
            self.rows = query("SELECT * FROM interactions WHERE text LIKE ? ORDER BY started_at DESC LIMIT 1000",
                              (f"%{search}%",))
        else:
            self.rows = query("SELECT * FROM interactions ORDER BY started_at DESC LIMIT 1000")
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(r["started_at"])[:19].replace("T", " ")
            if col == 1:
                return r["text"] or ""
            if col == 2:
                return r["words"] or 0
            if col == 3:
                return r["language"] or ""
            if col == 4:
                return r["engine"] or ""
            if col == 5:
                v = r["release_to_text_ms"]
                return f"{v:.0f} ms" if v is not None else ("legacy" if r["legacy"] else "")
            if col == 6:
                return r["target_app"] or ""
            if col == 7:
                return r["outcome"] or ""
        if role == Qt.ItemDataRole.ToolTipRole and col == 1:
            return r["text"]
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (2, 5):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class Dashboard(QMainWindow):
    def __init__(self, app, product: str = "PESTO", subtitle: str = "") -> None:
        super().__init__()
        self.app = app
        self.setWindowTitle(product)
        self.resize(1060, 700)
        self.setMinimumSize(860, 560)
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        side = QWidget()
        side.setFixedWidth(196)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 6, 14)
        title = label(product, "h1")
        sl.addWidget(title)
        sl.addWidget(label(subtitle, "faint", wrap=True))
        sl.addSpacing(12)
        self.nav = QListWidget(objectName="nav")
        sl.addWidget(self.nav, 1)
        self.engine_line = label("", "faint", wrap=True)
        sl.addWidget(self.engine_line)
        lay.addWidget(side)

        self.pages = QStackedWidget()
        lay.addWidget(self.pages, 1)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        self.add_page("Overview", self._overview())
        self.add_page("History", self._history())
        self.settings_page = SettingsPage(app)
        self.add_page("Settings", _scroll(self.settings_page))
        self.add_page("Diagnostics", self._diagnostics())
        self.nav.setCurrentRow(0)

        self._timer = QTimer(self, interval=4000, timeout=self.refresh)
        self._timer.start()
        self.refresh()

    def add_page(self, name: str, widget: QWidget, index: int | None = None) -> None:
        if index is None:
            self.nav.addItem(name)
            self.pages.addWidget(widget)
        else:
            self.nav.insertItem(index, name)
            self.pages.insertWidget(index, widget)

    # -- overview ------------------------------------------------------------------------
    def _overview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(14)
        lay.addWidget(label("Overview", "h1"))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.m_today = self._metric(grid, 0, "Today", "words dictated")
        self.m_latency = self._metric(grid, 1, "Release → text", "median · last 200")
        self.m_tail = self._metric(grid, 2, "Slow tail", "90th percentile")
        self.m_engine = self._metric(grid, 3, "Engine", "")
        lay.addLayout(grid)
        c, cl = card()
        cl.addWidget(label("Latency distribution", "h2"))
        cl.addWidget(label("Time from releasing the key to the text appearing. Bars past 1 s break the "
                           "sense of uninterrupted flow.", "muted", wrap=True))
        self.chart = LatencyChart()
        cl.addWidget(self.chart)
        lay.addWidget(c)
        c2, cl2 = card()
        cl2.addWidget(label("Recent", "h2"))
        self.recent = QVBoxLayout()
        self.recent.setSpacing(4)
        cl2.addLayout(self.recent)
        lay.addWidget(c2)
        lay.addStretch(1)
        return _scroll(w)

    def _metric(self, grid: QGridLayout, col: int, title: str, sub: str) -> tuple[QLabel, QLabel]:
        c, cl = card()
        cl.addWidget(label(title, "muted"))
        value = label("—", "metric")
        cl.addWidget(value)
        subl = label(sub, "faint")
        cl.addWidget(subl)
        grid.addWidget(c, 0, col)
        return value, subl

    def refresh(self) -> None:
        if not self.isVisible():
            return
        today = datetime.now().strftime("%Y-%m-%d")
        row = query("SELECT COALESCE(SUM(words),0) w, COUNT(*) n FROM interactions WHERE outcome='inserted' "
                    "AND started_at >= ?", (today,))
        if row:
            self.m_today[0].setText(f"{row[0]['w']:,}")
            self.m_today[1].setText(f"words dictated · {row[0]['n']} dictations")
        lat = [r["release_to_text_ms"] for r in query(
            "SELECT release_to_text_ms FROM interactions WHERE outcome='inserted' AND legacy=0 "
            "AND release_to_text_ms IS NOT NULL ORDER BY started_at DESC LIMIT 200")]
        if lat:
            self.m_latency[0].setText(f"{np.median(lat):.0f} ms")
            self.m_tail[0].setText(f"{np.percentile(lat, 90):.0f} ms")
        self.chart.set_values(lat)
        while self.recent.count():
            item = self.recent.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for r in query("SELECT started_at, text, release_to_text_ms, language, outcome, kind FROM interactions "
                       "WHERE outcome IN ('inserted','command') ORDER BY started_at DESC LIMIT 8"):
            line = QWidget()
            hl = QHBoxLayout(line)
            hl.setContentsMargins(0, 2, 0, 2)
            hl.addWidget(label(str(r["started_at"])[11:16], "faint"))
            t = label((("⌘ " if r["kind"] == "command" else "") + (r["text"] or "")))
            t.setTextFormat(Qt.TextFormat.PlainText)
            t.setMinimumWidth(100)
            hl.addWidget(t, 1)
            ms = r["release_to_text_ms"]
            hl.addWidget(label(f"{ms:.0f} ms" if ms else "", "faint"))
            self.recent.addWidget(line)
        snap = gpu.snapshot()
        self.m_engine[0].setText(self.app.engines.active_name.capitalize())
        dev = self.app.engines.device
        vram = f" · VRAM {snap.used_mb / 1024:.1f}/{snap.total_mb / 1024:.0f} GB" if snap.available else ""
        self.m_engine[1].setText(f"{dev}{vram}")

    def on_status(self, st: Status) -> None:
        if st.phase in (Phase.DONE,) and self.isVisible():
            QTimer.singleShot(600, self.refresh)

    def on_settings(self, s: Settings) -> None:
        self.engine_line.setText(f"{s.engine} · {s.engine_state} · {s.device}")

    # -- history -------------------------------------------------------------------------
    def _history(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.addWidget(label("History", "h1"))
        self.search = QLineEdit(placeholderText="Search dictated text…")
        lay.addWidget(self.search)
        self.hmodel = HistoryModel()
        view = QTableView()
        view.setModel(self.hmodel)
        view.setAlternatingRowColors(True)
        view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        view.verticalHeader().hide()
        header = view.horizontalHeader()
        header.setStretchLastSection(False)
        for col in range(len(HistoryModel.COLS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        view.doubleClicked.connect(lambda idx: QApplication.clipboard().setText(self.hmodel.rows[idx.row()]["text"] or ""))
        lay.addWidget(view, 1)
        lay.addWidget(label("Double-click a row to copy its text.", "faint"))
        self.search.textChanged.connect(lambda t: self.hmodel.load(t.strip()))
        self.nav.currentRowChanged.connect(lambda i: self.hmodel.load(self.search.text().strip())
                                           if self.nav.item(i) and self.nav.item(i).text() == "History" else None)
        return w

    # -- diagnostics ---------------------------------------------------------------------
    def _diagnostics(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(12)
        lay.addWidget(label("Diagnostics", "h1"))
        c, cl = card()
        self.diag = label("", None, wrap=True)
        self.diag.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.diag)
        lay.addWidget(c)
        row = QHBoxLayout()
        b1 = QPushButton("Open logs folder")
        b1.clicked.connect(lambda: os.startfile(paths.LOG_DIR))
        b2 = QPushButton("Open data folder")
        b2.clicked.connect(lambda: os.startfile(paths.DATA_DIR))
        b3 = QPushButton("Refresh")
        b3.clicked.connect(self._refresh_diag)
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.nav.currentRowChanged.connect(lambda i: self._refresh_diag()
                                           if self.nav.item(i) and self.nav.item(i).text() == "Diagnostics" else None)
        return w

    def _refresh_diag(self) -> None:
        a = self.app
        snap = gpu.snapshot()
        loads = ", ".join(f"{k} {v:.1f} s" for k, v in a.engines.load_seconds.items()) or "not loaded yet"
        db_mb = paths.DB_PATH.stat().st_size / 2**20 if paths.DB_PATH.exists() else 0
        lines = [
            f"<b>Microphone</b>: {a.session.mic.device_name or 'unavailable'}",
            f"<b>Engine</b>: {a.engines.active_name} · state {a.engines.state} · device {a.engines.device}",
            f"<b>Model load time</b>: {loads}",
            f"<b>GPU</b>: {snap.name if snap.available else 'none detected'}"
            + (f" · {snap.used_mb:.0f}/{snap.total_mb:.0f} MB used · {snap.util_pct:.0f}% util" if snap.available else ""),
            f"<b>Input</b>: {a.cfg.input.mode.upper()} · key '{a.cfg.input.ptt_key}' · hold ≥ {a.cfg.input.hold_threshold_ms} ms",
            f"<b>Telemetry DB</b>: {paths.DB_PATH} ({db_mb:.1f} MB)",
            f"<b>Models</b>: {paths.MODELS_DIR}",
            f"<b>Config</b>: {paths.CONFIG_PATH}",
        ]
        if a.engines.last_error:
            lines.append(f"<b>Last engine error</b>: {a.engines.last_error}")
        self.diag.setText("<br>".join(lines))


class SettingsPage(QWidget):
    """Edits the live Config. Fields marked ↻ apply after restart."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        cfg = app.cfg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(14)
        lay.addWidget(label("Settings", "h1"))

        def section(title: str, note: str = "") -> QFormLayout:
            c, cl = card()
            cl.addWidget(label(title, "h2"))
            if note:
                cl.addWidget(label(note, "muted", wrap=True))
            form = QFormLayout()
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(8)
            cl.addLayout(form)
            lay.addWidget(c)
            return form

        f = section("Speech recognition",
                    "Whisper is recommended for Greek. Parakeet is faster for English but cannot write the final "
                    "sigma (ς) and has ~3× Whisper's Greek word error rate (docs/EVALUATION.md).")
        self.engine = _combo([("whisper", "Whisper large-v3-turbo"), ("parakeet", "Parakeet TDT 0.6B v3")], cfg.asr.engine)
        self.language = _combo([("auto", "Automatic (Ελληνικά + English)"), ("el", "Ελληνικά"), ("en", "English")],
                               cfg.asr.language)
        f.addRow("Engine", self.engine)
        f.addRow("Language", self.language)

        f = section("Input")
        self.mode = _combo([("ptt", "Push-to-talk (hold a key)"), ("vad", "Hands-free (voice activity) ↻")], cfg.input.mode)
        self.ptt_key = QLineEdit(cfg.input.ptt_key)
        self.hold = _spin(0, 1000, cfg.input.hold_threshold_ms, " ms")
        self.end_sil = _spin(200, 3000, cfg.input.vad_end_silence_ms, " ms")
        f.addRow("Mode", self.mode)
        f.addRow("Push-to-talk key ↻", self.ptt_key)
        f.addRow("Minimum hold ↻", self.hold)
        f.addRow("Hands-free end silence", self.end_sil)

        f = section("Feedback & insertion")
        self.preview = QCheckBox("Show live text while speaking")
        self.preview.setChecked(cfg.ui.live_preview)
        self.sounds = QCheckBox("Sounds")
        self.sounds.setChecked(cfg.ui.sounds)
        self.hud = QCheckBox("Floating status capsule ↻")
        self.hud.setChecked(cfg.ui.hud)
        self.trailing = QCheckBox("Add a space after inserted text")
        self.trailing.setChecked(cfg.inject.trailing_space)
        self.method = _combo([("auto", "Automatic"), ("unicode", "Type (keeps clipboard)"), ("clipboard", "Paste")],
                             cfg.inject.method)
        for wdg in (self.preview, self.sounds, self.hud, self.trailing):
            f.addRow("", wdg)
        f.addRow("Insertion method", self.method)

        f = section("Study / experiment",
                    "Used by the HCI study platform. 'Added latency' delays text by a fixed amount to study "
                    "perceived latency; keep it at 0 for normal use.")
        self.participant = QLineEdit(cfg.experiment.participant)
        self.condition = QLineEdit(cfg.experiment.condition)
        self.added = _spin(0, 5000, cfg.experiment.added_latency_ms, " ms")
        self.save_audio = QCheckBox("Keep audio of each utterance (for later accuracy scoring)")
        self.save_audio.setChecked(cfg.experiment.save_audio)
        f.addRow("Participant", self.participant)
        f.addRow("Condition", self.condition)
        f.addRow("Added latency", self.added)
        f.addRow("", self.save_audio)

        self.extra_sections = lay  # extensions may append cards
        row = QHBoxLayout()
        self.saved = label("", "faint")
        save = QPushButton("Save")
        save.setProperty("role", "primary")
        save.clicked.connect(self.save)
        row.addWidget(self.saved, 1)
        row.addWidget(save)
        self._footer = row
        lay.addLayout(row)
        lay.addStretch(1)
        self.extra_savers = []

    def add_section(self, widget: QWidget, saver) -> None:
        self.extra_sections.insertWidget(self.extra_sections.count() - 2, widget)
        self.extra_savers.append(saver)

    def save(self) -> None:
        cfg, s = self.app.cfg, self.app.session
        if self.engine.currentData() != cfg.asr.engine:
            s.set_engine(self.engine.currentData())
        s.set_language(self.language.currentData())
        cfg.input.mode = self.mode.currentData()
        cfg.input.ptt_key = self.ptt_key.text().strip() or "right ctrl"
        cfg.input.hold_threshold_ms = self.hold.value()
        cfg.input.vad_end_silence_ms = self.end_sil.value()
        cfg.ui.live_preview = self.preview.isChecked()
        cfg.ui.sounds = self.sounds.isChecked()
        self.app.sounds.enabled = cfg.ui.sounds
        cfg.ui.hud = self.hud.isChecked()
        cfg.inject.trailing_space = self.trailing.isChecked()
        cfg.inject.method = self.method.currentData()
        cfg.experiment.participant = self.participant.text().strip()
        cfg.experiment.condition = self.condition.text().strip()
        cfg.experiment.added_latency_ms = self.added.value()
        cfg.experiment.save_audio = self.save_audio.isChecked()
        for saver in self.extra_savers:
            saver()
        cfg.save()
        self.saved.setText("Saved. Settings marked ↻ apply after restart.")


def _combo(items, current) -> QComboBox:
    c = QComboBox()
    for value, text in items:
        c.addItem(text, value)
    idx = c.findData(current)
    c.setCurrentIndex(max(0, idx))
    return c


def _spin(lo: int, hi: int, value: int, suffix: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    s.setSuffix(suffix)
    s.setSingleStep(10 if hi <= 3000 else 50)
    return s


def _scroll(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(widget)
    return sa
