"""Participant-facing study runner (transcription task).

Hosts PESTO in-process, so voice conditions use the real pipeline: the
participant dictates into the trial's text box exactly as they would into any
application, and every utterance is also logged as an interaction (with the
full latency decomposition) tagged with participant and condition.

Per trial we record: presented phrase, final text, time of first input (first
key press or first speech feedback), completion time, keystrokes, backspaces,
utterances, WPM, MSD error rate (literal and normalised) and the IDs of the
interactions produced during the trial. Practice trials are stored but flagged.
"""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

from pesto.events import Phase, Status
from pesto.telemetry import Telemetry, now_iso

from .measures import TLX_SCALES, msd_error_rate, tlx_raw, wpm
from .protocol import Condition, Protocol

TEXT = {
    "el": {
        "welcome": "Καλώς ορίσατε", "start": "Έναρξη", "next": "Επόμενο (Ctrl+Enter)", "continue": "Συνέχεια",
        "practice": "Δοκιμαστική πρόταση", "trial": "Πρόταση", "block": "Ενότητα",
        "type_here": "Γράψτε ή υπαγορεύστε εδώ…",
        "rate_q": "Πόσο γρήγορα σας φάνηκε ότι αντέδρασε το σύστημα;",
        "rate_lo": "1 = πολύ αργά", "rate_hi": "7 = αμέσως",
        "tlx_title": "Πώς σας φάνηκε αυτή η ενότητα;",
        "done": "Ευχαριστούμε! Η συνεδρία ολοκληρώθηκε.",
        "tlx": {"mental": ("Νοητική απαίτηση", "Πόση σκέψη και προσοχή χρειάστηκε;"),
                "physical": ("Σωματική απαίτηση", "Πόση σωματική προσπάθεια χρειάστηκε;"),
                "temporal": ("Χρονική πίεση", "Πόσο βιαστικός ήταν ο ρυθμός;"),
                "performance": ("Απόδοση", "Πόσο επιτυχημένος/η ήσασταν; (0 = τέλεια, 100 = αποτυχία)"),
                "effort": ("Προσπάθεια", "Πόσο σκληρά δουλέψατε για αυτή την απόδοση;"),
                "frustration": ("Εκνευρισμός", "Πόσο εκνευρισμένος/η ή αγχωμένος/η νιώσατε;")},
        "low": "Πολύ χαμηλή", "high": "Πολύ υψηλή", "perf_low": "Τέλεια", "perf_high": "Αποτυχία",
        "move_all": "Μετακινήστε και τις έξι κλίμακες για να συνεχίσετε.",
    },
    "en": {
        "welcome": "Welcome", "start": "Start", "next": "Next (Ctrl+Enter)", "continue": "Continue",
        "practice": "Practice sentence", "trial": "Sentence", "block": "Block",
        "type_here": "Type or dictate here…",
        "rate_q": "How quickly did the system seem to respond?", "rate_lo": "1 = very slowly", "rate_hi": "7 = instantly",
        "tlx_title": "How was this block?", "done": "Thank you! The session is complete.",
        "tlx": {"mental": ("Mental demand", "How much thinking and attention was required?"),
                "physical": ("Physical demand", "How much physical effort was required?"),
                "temporal": ("Temporal demand", "How hurried was the pace?"),
                "performance": ("Performance", "How successful were you? (0 = perfect, 100 = failure)"),
                "effort": ("Effort", "How hard did you have to work for that performance?"),
                "frustration": ("Frustration", "How irritated or stressed did you feel?")},
        "low": "Very low", "high": "Very high", "perf_low": "Perfect", "perf_high": "Failure",
        "move_all": "Move all six scales to continue.",
    },
}


class _KeyCounter(QObject):
    """Counts physical key presses in the response box (synthetic dictation
    input arrives as VK_PACKET and is reported by Qt without a key code)."""

    pressed = Signal(int)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress and not ev.isAutoRepeat() and ev.key() not in (0, Qt.Key.Key_unknown):
            self.pressed.emit(ev.key())
        return False


class StudyWindow(QWidget):
    def __init__(self, app, protocol: Protocol, participant: str, index: int, telemetry: Telemetry) -> None:
        super().__init__()
        self.app, self.p, self.participant, self.tel = app, protocol, participant, telemetry
        self.t = TEXT.get(protocol.language, TEXT["en"])
        self.plan = protocol.assign(participant, index)
        self.block = -1
        self.queue: list[tuple[str, bool]] = []  # (phrase, is_practice)
        self.trial_no = 0
        self.setWindowTitle(f"Study · {protocol.name} · {participant}")
        self.resize(1100, 720)
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(self.stack)
        self._build_pages()
        if app is not None:
            app.bus.subscribe(self._on_status_threadsafe, Status)
        self._status_sig.connect(self._on_status)
        self.stack.setCurrentWidget(self.page_intro)

    _status_sig = Signal(object)

    # -- pages ------------------------------------------------------------------------
    def _big(self, text: str, size: int = 20, bold: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # the app stylesheet sets a global font size, so size via stylesheet too
        lbl.setStyleSheet(f"font-size: {size}pt; font-weight: {600 if bold else 400};")
        return lbl

    def _build_pages(self) -> None:
        t = self.t
        # intro / instructions
        self.page_intro = QWidget()
        il = QVBoxLayout(self.page_intro)
        self.intro_title = self._big(t["welcome"], 24, True)
        self.intro_text = self._big("", 15)
        self.intro_btn = QPushButton(t["start"])
        self.intro_btn.setProperty("role", "primary")
        self.intro_btn.clicked.connect(self._start_block)
        il.addStretch(1)
        il.addWidget(self.intro_title)
        il.addSpacing(16)
        il.addWidget(self.intro_text)
        il.addSpacing(24)
        il.addWidget(self.intro_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        il.addStretch(1)
        self.stack.addWidget(self.page_intro)

        # trial
        self.page_trial = QWidget()
        tl = QVBoxLayout(self.page_trial)
        self.progress = QLabel()
        self.progress.setProperty("role", "muted")
        self.stimulus = self._big("", 22, True)
        self.response = QPlainTextEdit()
        self.response.setPlaceholderText(t["type_here"])
        self.response.setStyleSheet("font-size: 18pt;")
        self.counter = _KeyCounter()
        self.counter.pressed.connect(self._on_key)
        self.response.installEventFilter(self.counter)
        self.response.textChanged.connect(self._on_text_changed)
        self.next_btn = QPushButton(t["next"])
        self.next_btn.setProperty("role", "primary")
        self.next_btn.clicked.connect(self._finish_trial)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._finish_trial)
        tl.addWidget(self.progress)
        tl.addStretch(1)
        tl.addWidget(self.stimulus)
        tl.addSpacing(20)
        tl.addWidget(self.response, 2)
        tl.addWidget(self.next_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self.stack.addWidget(self.page_trial)

        # perceived-speed rating
        self.page_rate = QWidget()
        rl = QVBoxLayout(self.page_rate)
        rl.addStretch(1)
        rl.addWidget(self._big(t["rate_q"], 18, True))
        row = QHBoxLayout()
        self.rate_group = QButtonGroup(self)
        for v in range(1, 8):
            b = QPushButton(str(v))
            b.setFixedSize(64, 64)
            self.rate_group.addButton(b, v)
            row.addWidget(b)
        self.rate_group.idClicked.connect(self._on_rating)
        rl.addLayout(row)
        hint = QHBoxLayout()
        hint.addWidget(QLabel(t["rate_lo"]))
        hint.addStretch(1)
        hint.addWidget(QLabel(t["rate_hi"]))
        rl.addLayout(hint)
        rl.addStretch(1)
        self.stack.addWidget(self.page_rate)

        # NASA-TLX
        self.page_tlx = QWidget()
        xl = QVBoxLayout(self.page_tlx)
        xl.addSpacing(24)
        xl.addWidget(self._big(t["tlx_title"], 18, True))
        xl.addSpacing(24)
        grid = QGridLayout()
        grid.setVerticalSpacing(18)
        self.sliders: dict[str, QSlider] = {}
        self.touched: set[str] = set()
        for i, scale in enumerate(TLX_SCALES):
            name, desc = t["tlx"][scale]
            lbl = QLabel(f"<b>{name}</b><br><span style='color:#a0a6b0'>{desc}</span>")
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 100)
            s.setSingleStep(5)
            s.setPageStep(5)
            s.setTickInterval(5)
            s.setTickPosition(QSlider.TickPosition.TicksBelow)
            s.setValue(50)
            # A value only counts once the participant has moved the slider:
            # pre-positioned sliders invite anchoring on the default.
            s.sliderPressed.connect(lambda sc=scale: self._touch(sc))
            s.valueChanged.connect(lambda _v, sc=scale: self._touch(sc))
            self.sliders[scale] = s
            lo, hi = (t["perf_low"], t["perf_high"]) if scale == "performance" else (t["low"], t["high"])
            grid.addWidget(lbl, i, 0)
            grid.addWidget(QLabel(lo), i, 1)
            grid.addWidget(s, i, 2)
            grid.addWidget(QLabel(hi), i, 3)
        grid.setColumnStretch(2, 1)
        xl.addLayout(grid)
        xl.addStretch(1)
        self.tlx_hint = QLabel(t["move_all"])
        self.tlx_hint.setProperty("role", "muted")
        self.tlx_btn = QPushButton(t["continue"])
        self.tlx_btn.setProperty("role", "primary")
        self.tlx_btn.clicked.connect(self._submit_tlx)
        row = QHBoxLayout()
        row.addWidget(self.tlx_hint)
        row.addStretch(1)
        row.addWidget(self.tlx_btn)
        xl.addLayout(row)
        self.stack.addWidget(self.page_tlx)

        self.page_done = QWidget()
        dl = QVBoxLayout(self.page_done)
        dl.addWidget(self._big(t["done"], 22, True))
        self.stack.addWidget(self.page_done)

    # -- flow -------------------------------------------------------------------------
    def show_block_intro(self) -> None:
        cond = self.plan[self.block + 1][0]
        self.intro_title.setText(f"{self.t['block']} {self.block + 2}/{len(self.plan)}")
        self.intro_text.setText(cond.instructions)
        self.intro_btn.setText(self.t["start"])
        self.stack.setCurrentWidget(self.page_intro)

    def _start_block(self) -> None:
        if self.block == -1 and self.intro_title.text() == self.t["welcome"]:
            self.show_block_intro()
            return
        self.block += 1
        cond, practice, trials = self.plan[self.block]
        self._configure(cond)
        self.queue = [(ph, True) for ph in practice] + [(ph, False) for ph in trials]
        self.trial_no = 0
        self._next_trial()

    def _configure(self, cond: Condition) -> None:
        if self.app is None:
            return
        cfg = self.app.cfg
        cfg.experiment.participant = self.participant
        cfg.experiment.condition = cond.name
        cfg.experiment.added_latency_ms = cond.added_latency_ms
        cfg.ui.live_preview = cond.live_preview
        self.app.session.enabled = cond.input != "keyboard"
        if cond.input in ("ptt", "vad"):
            self.app.session.set_input_mode(cond.input)

    def _next_trial(self) -> None:
        if not self.queue:
            self._end_block()
            return
        phrase, practice = self.queue.pop(0)
        self.trial_no += 1
        n_trials = len(self.plan[self.block][2])
        label = self.t["practice"] if practice else f"{self.t['trial']} {self.trial_no - self.p.practice_trials}/{n_trials}"
        # Condition names are never shown: naming a manipulation ("delay_700")
        # would tell participants what is being studied (demand characteristics).
        self.progress.setText(f"{self.t['block']} {self.block + 1}/{len(self.plan)} · {label}")
        self.stimulus.setText(phrase)
        self.cur = {"phrase": phrase, "practice": practice, "t0": time.perf_counter(), "started_at": now_iso(),
                    "first_key": None, "first_speech": None, "keys": 0, "backspaces": 0, "utterances": 0,
                    "interactions": [], "first_change": None}
        self.response.blockSignals(True)
        self.response.clear()
        self.response.blockSignals(False)
        self.stack.setCurrentWidget(self.page_trial)
        self.activateWindow()
        self.response.setFocus()

    def _on_key(self, key: int) -> None:
        if self.stack.currentWidget() is not self.page_trial:
            return
        cur = self.cur
        if cur["first_key"] is None and key not in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt):
            cur["first_key"] = time.perf_counter()
        cur["keys"] += 1
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            cur["backspaces"] += 1

    def _on_text_changed(self) -> None:
        if getattr(self, "cur", None) and self.cur["first_change"] is None:
            self.cur["first_change"] = time.perf_counter()

    def _on_status_threadsafe(self, st: Status) -> None:
        self._status_sig.emit(st)

    def _on_status(self, st: Status) -> None:
        cur = getattr(self, "cur", None)
        if cur is None or self.stack.currentWidget() is not self.page_trial:
            return
        if st.phase == Phase.LISTENING and cur["first_speech"] is None:
            hold = self.app.cfg.input.hold_threshold_ms / 1000.0 if self.app else 0.0
            cur["first_speech"] = st.t - (hold if self.app and self.app.cfg.input.mode == "ptt" else 0.0)
        if st.phase == Phase.DONE and st.interaction_id:
            cur["utterances"] += 1
            cur["interactions"].append(st.interaction_id)

    def _finish_trial(self) -> None:
        if self.stack.currentWidget() is not self.page_trial:
            return
        cur = self.cur
        t_end = time.perf_counter()
        response = self.response.toPlainText().strip()
        starts = [t for t in (cur["first_key"], cur["first_speech"], cur["first_change"]) if t is not None]
        t_first = min(starts) if starts else t_end
        secs = max(t_end - t_first, 1e-3)
        cond = self.plan[self.block][0]
        self.last_trial = {
            "study": self.p.name, "participant": self.participant, "condition": cond.name, "block": self.block + 1,
            "trial": self.trial_no, "stimulus": cur["phrase"], "response": response, "started_at": cur["started_at"],
            "first_input_ms": (t_first - cur["t0"]) * 1000, "completed_ms": (t_end - cur["t0"]) * 1000,
            "keystrokes": cur["keys"], "backspaces": cur["backspaces"], "utterances": cur["utterances"],
            "wpm": wpm(response, secs), "msd_error": msd_error_rate(cur["phrase"], response),
            "cer": msd_error_rate(cur["phrase"], response, normalized=True),
            "data": {"practice": cur["practice"], "input": cond.input, "added_latency_ms": cond.added_latency_ms,
                     "interaction_ids": cur["interactions"],
                     "first_key_ms": _rel(cur["first_key"], cur["t0"]),
                     "first_speech_ms": _rel(cur["first_speech"], cur["t0"])},
        }
        if self.p.rate_each_trial and cond.input != "keyboard":
            self.stack.setCurrentWidget(self.page_rate)
        else:
            self._store_trial(None)

    def _on_rating(self, value: int) -> None:
        self._store_trial(value)

    def _store_trial(self, rating: int | None) -> None:
        row = dict(self.last_trial)
        data = row.pop("data")
        data["perceived_speed"] = rating
        row["data_json"] = json.dumps(data, ensure_ascii=False)
        self.tel.record_trial(row)
        QTimer.singleShot(150, self._next_trial)

    def _touch(self, scale: str) -> None:
        if self.stack.currentWidget() is self.page_tlx:
            self.touched.add(scale)
            self.tlx_btn.setEnabled(len(self.touched) == len(self.sliders))
            self.tlx_hint.setVisible(len(self.touched) < len(self.sliders))

    def _end_block(self) -> None:
        if self.p.tlx_after_block:
            for s in self.sliders.values():
                s.blockSignals(True)
                s.setValue(50)
                s.blockSignals(False)
            self.touched.clear()
            self.tlx_btn.setEnabled(False)
            self.tlx_hint.setVisible(True)
            self.stack.setCurrentWidget(self.page_tlx)
        else:
            self._after_tlx()

    def _submit_tlx(self) -> None:
        answers = {k: s.value() for k, s in self.sliders.items()}
        self.tel.record_questionnaire({
            "study": self.p.name, "participant": self.participant, "condition": self.plan[self.block][0].name,
            "instrument": "nasa_tlx_raw", "answers_json": json.dumps(answers), "score": tlx_raw(answers),
            "created_at": now_iso()})
        self._after_tlx()

    def _after_tlx(self) -> None:
        if self.block + 1 < len(self.plan):
            self.show_block_intro()
        else:
            if self.app is not None:
                self.app.session.enabled = True
                self.app.cfg.experiment.condition = ""
                self.app.cfg.experiment.added_latency_ms = 0
            self.tel.flush()
            self.stack.setCurrentWidget(self.page_done)


def _rel(t: float | None, t0: float) -> float | None:
    return None if t is None else (t - t0) * 1000
