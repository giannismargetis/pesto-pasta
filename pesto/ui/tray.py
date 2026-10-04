"""System tray icon: state at a glance + the few controls people actually use."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..events import Phase, Settings, Status
from . import theme

ENGINE_TITLES = {
    "whisper": "Whisper large-v3-turbo — Greek + English",
    "parakeet": "Parakeet 0.6B — English (weak Greek)",
}


def state_icon(color: QColor, busy: bool = False) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(28, 31, 36))
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 16, 16)
    p.setBrush(color)
    heights = (16, 30, 22) if not busy else (24, 24, 24)
    for i, h in enumerate(heights):
        p.drawRoundedRect(QRectF(17 + i * 12, 32 - h / 2, 7, h), 3.5, 3.5)
    p.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    def __init__(self, app, open_dashboard, quit_app, product: str) -> None:
        super().__init__()
        self.app = app
        self.product = product
        self._icons = {
            "idle": state_icon(theme.TEXT_2),
            "listening": state_icon(theme.GREEN),
            "busy": state_icon(theme.BLUE, busy=True),
            "error": state_icon(theme.RED),
            "paused": state_icon(theme.TEXT_3),
        }
        self.setIcon(self._icons["idle"])
        self.setToolTip(product)
        menu = QMenu()
        menu.addAction("Open dashboard", open_dashboard)
        menu.addSeparator()
        self.status_action = menu.addAction("Starting…")
        self.status_action.setEnabled(False)
        menu.addSeparator()

        eng_menu = menu.addMenu("Speech engine")
        self.engine_group = QActionGroup(menu)
        self.engine_actions = {}
        for name, title in ENGINE_TITLES.items():
            a = QAction(title, menu, checkable=True)
            a.triggered.connect(lambda _=False, n=name: app.session.set_engine(n))
            self.engine_group.addAction(a)
            eng_menu.addAction(a)
            self.engine_actions[name] = a

        lang_menu = menu.addMenu("Language")
        self.lang_group = QActionGroup(menu)
        self.lang_actions = {}
        for mode, title in (("auto", "Automatic (Ελληνικά + English)"), ("el", "Ελληνικά"), ("en", "English")):
            a = QAction(title, menu, checkable=True)
            a.triggered.connect(lambda _=False, m=mode: app.session.set_language(m))
            self.lang_group.addAction(a)
            lang_menu.addAction(a)
            self.lang_actions[mode] = a

        self.extra_menu_anchor = menu.addSeparator()
        self.pause_action = menu.addAction("Pause (free GPU memory)", self._toggle_pause)
        menu.addAction(f"Quit {product}", quit_app)
        self.menu = menu
        self.setContextMenu(menu)
        self.activated.connect(lambda reason: open_dashboard()
                               if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    def add_menu(self, title: str) -> QMenu:
        sub = QMenu(title, self.menu)
        self.menu.insertMenu(self.extra_menu_anchor, sub)
        return sub

    def _toggle_pause(self) -> None:
        self.app.session.set_paused(not self.app.session.paused)

    def on_settings(self, s: Settings) -> None:
        if s.engine in self.engine_actions:
            self.engine_actions[s.engine].setChecked(True)
        if s.language in self.lang_actions:
            self.lang_actions[s.language].setChecked(True)
        state = {"ready": f"Ready · {s.engine} on {s.device}", "loading": f"Loading {s.engine}…",
                 "unloaded": f"{s.engine} (loads on first use)", "error": f"{s.engine} failed to load"}[s.engine_state]
        if s.input_mode == "paused":
            state = "Paused"
        self.status_action.setText(state)
        self.pause_action.setText("Resume" if s.input_mode == "paused" else "Pause (free GPU memory)")
        self.setToolTip(f"{self.product} — {state}")
        self.setIcon(self._icons["paused" if s.input_mode == "paused" else
                                 "error" if s.engine_state == "error" else
                                 "busy" if s.engine_state == "loading" else "idle"])

    def on_status(self, st: Status) -> None:
        if st.phase == Phase.LISTENING:
            self.setIcon(self._icons["listening"])
        elif st.phase in (Phase.TRANSCRIBING, Phase.EXECUTING, Phase.UNDERSTANDING, Phase.VERIFYING):
            self.setIcon(self._icons["busy"])
        elif st.phase == Phase.FAILED:
            self.setIcon(self._icons["error"])
        elif st.phase in (Phase.DONE, Phase.CANCELLED, Phase.EMPTY):
            self.setIcon(self._icons["idle"])
