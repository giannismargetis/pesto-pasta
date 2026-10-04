"""The floating status capsule.

* never takes focus and ignores the mouse (text must keep going to the app
  the user is working in);
* renders one explicit visual state per :class:`~pesto.events.Phase`;
* animates only while something is changing (no idle CPU).
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..events import Phase, Status
from . import theme

H = 52.0
STEP_H = 24.0
MIN_W, MAX_W = 250.0, 640.0
HIDE_AFTER = {Phase.DONE: 1.1, Phase.EMPTY: 0.8, Phase.CANCELLED: 0.7, Phase.FAILED: 2.8}
BUSY = {Phase.TRANSCRIBING, Phase.INJECTING, Phase.UNDERSTANDING, Phase.EXECUTING, Phase.VERIFYING}


def accent(phase: Phase, command: bool) -> QColor:
    if phase == Phase.FAILED:
        return theme.RED
    if phase == Phase.CONFIRM:
        return theme.AMBER
    if phase in (Phase.CANCELLED, Phase.EMPTY):
        return theme.NEUTRAL
    return theme.BLUE if command else theme.GREEN


class Hud(QWidget):
    def __init__(self, position: str = "bottom") -> None:
        super().__init__(None)
        self.position = position
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.f_main = theme.ui_font(10.5, theme.QFont.Weight.Medium)
        self.f_meta = theme.ui_font(9.0)
        self.f_step = theme.ui_font(9.5)
        self.phase = Phase.IDLE
        self.interaction = ""
        self.title = ""
        self.meta = ""
        self.command = False
        self.steps: list[dict] = []
        self.level = 0.0
        self._level_target = 0.0
        self._bars = [0.0] * 5
        self._t0 = time.perf_counter()
        self._phase_t = self._t0
        self._hide_at: float | None = None
        self._width = MIN_W
        self._opacity = 0.0
        self._tick = QTimer(self, interval=16, timeout=self._frame)
        self._fade = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._set_opacity)
        self._resize = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.Type.OutCubic)
        self._resize.valueChanged.connect(self._set_width)
        self.setWindowOpacity(0.0)

    # -- public API (GUI thread) -------------------------------------------------------
    def on_status(self, st: Status) -> None:
        if st.phase == Phase.IDLE:
            return
        if st.phase == Phase.LISTENING:  # a new interaction starts clean
            self.interaction = st.interaction_id
            self.steps, self.title, self.meta = [], "", st.message
            self.command = bool(st.data.get("command", False))
        else:
            self.interaction = st.interaction_id or self.interaction
            if "command" in st.data:
                self.command = bool(st.data["command"])
            self.title, self.meta = st.message, st.detail
        self.phase = st.phase
        self._phase_t = time.perf_counter()
        if "steps" in st.data:
            self.steps = list(st.data["steps"])[:7]
        self._hide_at = self._phase_t + HIDE_AFTER[st.phase] if st.phase in HIDE_AFTER else None
        if st.phase == Phase.CONFIRM:
            self._hide_at = None
        self._appear()
        self._relayout()

    def on_preview(self, ev) -> None:
        if self.phase == Phase.LISTENING and (not self.interaction or ev.interaction_id == self.interaction):
            self.title = ev.text
            self._relayout()

    def on_level(self, rms: float) -> None:
        self._level_target = rms

    # -- geometry / animation ----------------------------------------------------------
    def _target_height(self) -> float:
        return H + (STEP_H * len(self.steps) + 10 if self.steps else 0)

    def _relayout(self) -> None:
        fm = QFontMetricsF(self.f_main)
        text_w = fm.horizontalAdvance(self.title or self._placeholder())
        meta_w = QFontMetricsF(self.f_meta).horizontalAdvance(self.meta) if self.meta else 0
        steps_w = max((QFontMetricsF(self.f_step).horizontalAdvance(s.get("label", "")) + 70 for s in self.steps), default=0)
        target = max(MIN_W, min(MAX_W, max(text_w + meta_w + 96, steps_w)))
        self._resize.stop()
        self._resize.setStartValue(self._width)
        self._resize.setEndValue(target)
        self._resize.start()
        self._place()

    def _set_width(self, w) -> None:
        self._width = float(w)
        self._place()

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        h = self._target_height()
        win_w, win_h = int(MAX_W + 24), int(h + 24)
        x = area.x() + (area.width() - win_w) // 2
        y = area.y() + 56 if self.position == "top" else area.y() + area.height() - win_h - 56
        self.setGeometry(x, y, win_w, win_h)
        self.update()

    def _appear(self) -> None:
        if not self.isVisible():
            self._place()
            self.show()
            _no_activate(self)
        if self._opacity < 1.0:
            self._fade.stop()
            self._fade.setStartValue(self._opacity)
            self._fade.setEndValue(1.0)
            self._fade.start()
        if not self._tick.isActive():
            self._tick.start()

    def _disappear(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(0.0)
        self._fade.setDuration(220)
        self._fade.start()

    def _set_opacity(self, v) -> None:
        self._opacity = float(v)
        self.setWindowOpacity(self._opacity)
        if self._opacity <= 0.01 and self._hide_at is None and self.phase in HIDE_AFTER:
            self.hide()
            self._tick.stop()
            self._fade.setDuration(140)

    def _frame(self) -> None:
        now = time.perf_counter()
        if self._hide_at is not None and now >= self._hide_at:
            self._hide_at = None
            self._disappear()
        k = 0.45 if self._level_target > self.level else 0.18
        self.level += (self._level_target - self.level) * k
        self._level_target *= 0.92
        for i in range(len(self._bars)):
            wobble = 0.55 + 0.45 * math.sin(now * 9.0 + i * 1.3)
            target = min(1.0, self.level * (0.6 + 0.4 * wobble) * (1.0 - abs(i - 2) * 0.16))
            self._bars[i] += (target - self._bars[i]) * 0.35
        self.update()

    # -- painting ----------------------------------------------------------------------
    def _placeholder(self) -> str:
        return {Phase.LISTENING: "Listening…", Phase.TRANSCRIBING: "Transcribing…",
                Phase.UNDERSTANDING: "Understanding…"}.get(self.phase, "")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._target_height()
        w = self._width
        rect = QRectF((self.width() - w) / 2, self.height() - h - 12, w, h)
        radius = H / 2 if not self.steps else 18.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        # soft shadow
        for i, a in enumerate((26, 14, 6)):
            sp = QPainterPath()
            r = rect.adjusted(-2 - 2 * i, -1 - i, 2 + 2 * i, 3 + 2 * i)
            sp.addRoundedRect(r, radius + 2 + 2 * i, radius + 2 + 2 * i)
            p.fillPath(sp, QColor(0, 0, 0, a))
        bg = QColor(theme.BG)
        bg.setAlpha(242)
        p.fillPath(path, bg)
        p.setPen(QPen(theme.BORDER, 1.0))
        p.drawPath(path)

        col = accent(self.phase, self.command)
        row = QRectF(rect.x(), rect.y(), rect.width(), H)
        icon_c = QPointF(row.x() + 28, row.center().y())
        self._paint_indicator(p, icon_c, col)

        # meta (right)
        meta_w = 0.0
        if self.meta:
            p.setFont(self.f_meta)
            fm = QFontMetricsF(self.f_meta)
            meta_w = fm.horizontalAdvance(self.meta) + 8
            p.setPen(theme.TEXT_3)
            p.drawText(QRectF(row.right() - meta_w - 18, row.y(), meta_w, H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.meta)
        # primary text
        text = self.title or self._placeholder()
        p.setFont(self.f_main)
        fm = QFontMetricsF(self.f_main)
        avail = row.width() - 56 - meta_w - 26
        mode = Qt.TextElideMode.ElideLeft if self.phase == Phase.LISTENING else Qt.TextElideMode.ElideRight
        p.setPen(theme.TEXT if self.title else theme.TEXT_2)
        p.drawText(QRectF(row.x() + 54, row.y(), avail, H), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(text, mode, avail))

        if self.steps:
            self._paint_steps(p, QRectF(rect.x() + 18, rect.y() + H - 4, rect.width() - 36, h - H))
        p.end()

    def _paint_indicator(self, p: QPainter, c: QPointF, col: QColor) -> None:
        now = time.perf_counter()
        age = now - self._phase_t
        if self.phase == Phase.LISTENING:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            for i, v in enumerate(self._bars):
                bh = 4 + 18 * v
                x = c.x() - 10 + i * 5
                p.drawRoundedRect(QRectF(x - 1.5, c.y() - bh / 2, 3, bh), 1.5, 1.5)
        elif self.phase in BUSY:
            p.setPen(QPen(QColor(255, 255, 255, 28), 2.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = QRectF(c.x() - 9, c.y() - 9, 18, 18)
            p.drawEllipse(r)
            pen = QPen(col, 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            start = -int((now * 360 * 1.4) % 360) * 16
            span = int((90 + 60 * math.sin(now * 3.2)) * 16)
            p.drawArc(r, start, span)
        elif self.phase == Phase.DONE:
            prog = min(1.0, age / 0.18)
            pen = QPen(col, 2.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            pts = [QPointF(c.x() - 7, c.y()), QPointF(c.x() - 2, c.y() + 5), QPointF(c.x() + 8, c.y() - 6)]
            seg1 = min(1.0, prog / 0.4)
            p.drawLine(pts[0], pts[0] + (pts[1] - pts[0]) * seg1)
            if prog > 0.4:
                seg2 = (prog - 0.4) / 0.6
                p.drawLine(pts[1], pts[1] + (pts[2] - pts[1]) * seg2)
        elif self.phase in (Phase.FAILED, Phase.CONFIRM):
            pulse = 1.0 + (0.08 * math.sin(now * 6) if self.phase == Phase.CONFIRM else 0)
            p.setPen(Qt.PenStyle.NoPen)
            fill = QColor(col)
            fill.setAlpha(40)
            p.setBrush(fill)
            p.drawEllipse(c, 11 * pulse, 11 * pulse)
            p.setPen(col)
            p.setFont(theme.ui_font(11, theme.QFont.Weight.Bold))
            p.drawText(QRectF(c.x() - 11, c.y() - 11, 22, 22), Qt.AlignmentFlag.AlignCenter,
                       "!" if self.phase == Phase.FAILED else "?")
        else:  # cancelled / empty
            pen = QPen(col, 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(c.x() - 6, c.y()), QPointF(c.x() + 6, c.y()))

    def _paint_steps(self, p: QPainter, area: QRectF) -> None:
        p.setFont(self.f_step)
        fm = QFontMetricsF(self.f_step)
        now = time.perf_counter()
        for i, step in enumerate(self.steps):
            y = area.y() + i * STEP_H
            c = QPointF(area.x() + 10, y + STEP_H / 2)
            state = step.get("state", "pending")
            col = {"done": theme.GREEN, "running": theme.BLUE, "failed": theme.RED, "confirm": theme.AMBER,
                   "unverified": theme.AMBER, "skipped": theme.TEXT_3}.get(state, theme.TEXT_3)
            if state == "running":
                pen = QPen(col, 1.8)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(c.x() - 5, c.y() - 5, 10, 10), -int((now * 500) % 360) * 16, 100 * 16)
            elif state == "done":
                pen = QPen(col, 1.8)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(c.x() - 4, c.y()), QPointF(c.x() - 1, c.y() + 3))
                p.drawLine(QPointF(c.x() - 1, c.y() + 3), QPointF(c.x() + 5, c.y() - 4))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(c, 3.2, 3.2)
            p.setPen(theme.TEXT if state in ("running", "confirm") else theme.TEXT_2)
            label = step.get("label", "")
            hint = step.get("hint", "")
            text_rect = QRectF(area.x() + 24, y, area.width() - 24, STEP_H)
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(label, Qt.TextElideMode.ElideRight, text_rect.width() - (120 if hint else 0)))
            if hint:
                p.setPen(theme.TEXT_3)
                p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, hint)


def _no_activate(widget: QWidget) -> None:
    """Belt and braces: WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW."""
    try:
        import ctypes

        hwnd = int(widget.winId())
        GWL_EXSTYLE = -20
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | 0x08000000 | 0x00000020 | 0x00000080)
    except Exception:
        pass
