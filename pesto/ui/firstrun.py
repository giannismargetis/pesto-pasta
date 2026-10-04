"""First-run setup window for non-technical users.

Downloads the speech model with visible progress, checks the microphone with a
live level meter, and explains the two gestures. Shown whenever the default
model is not in the local cache.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import paths
from ..asr.models import WHISPER_REPOS

REPO = WHISPER_REPOS["large-v3-turbo"]


def model_cached(repo: str = REPO) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo, local_files_only=True)
        return True
    except Exception:
        return False


class _Downloader(QObject):
    progress = Signal(float, float)  # downloaded MB, total MB
    finished = Signal(str)  # "" = ok, else error message

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            from huggingface_hub import HfApi, snapshot_download

            info = HfApi().model_info(REPO, files_metadata=True)
            total = sum((s.size or 0) for s in info.siblings) / 2**20
            folder = paths.MODELS_DIR / ("models--" + REPO.replace("/", "--"))
            done = threading.Event()
            err: list[str] = []

            def work():
                try:
                    snapshot_download(REPO)
                except Exception as exc:  # network, disk full, ...
                    err.append(str(exc))
                finally:
                    done.set()

            threading.Thread(target=work, daemon=True).start()
            while not done.wait(0.3):
                got = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 2**20 if folder.exists() else 0
                self.progress.emit(min(got, total), total)
            self.progress.emit(total, total)
            self.finished.emit(err[0] if err else "")
        except Exception as exc:
            self.finished.emit(str(exc))


def _label(text: str, size: float = 10.5, bold: bool = False, muted: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"font-size: {size}pt; font-weight: {600 if bold else 400};"
                      + ("color: #a0a6b0;" if muted else ""))
    return lbl


class FirstRun(QDialog):
    def __init__(self, product: str = "PASTA") -> None:
        super().__init__()
        self.setWindowTitle(f"{product} — Εγκατάσταση / Setup")
        self.setFixedSize(620, 440)
        self.product = product
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.addWidget(self.stack)
        self._welcome()
        self._download()
        self._mic()
        self._done()
        self.stack.setCurrentIndex(0)

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)
        v.addWidget(_label(title, 17, True))
        v.addWidget(_label(subtitle, 10, muted=True))
        v.addSpacing(10)
        self.stack.addWidget(w)
        return w, v

    def _buttons(self, v: QVBoxLayout, primary: str, on_primary, secondary: str | None = None, on_secondary=None):
        v.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        if secondary:
            b2 = QPushButton(secondary)
            b2.clicked.connect(on_secondary)
            row.addWidget(b2)
        b = QPushButton(primary)
        b.setProperty("role", "primary")
        b.clicked.connect(on_primary)
        row.addWidget(b)
        v.addLayout(row)
        return b

    # -- pages ------------------------------------------------------------------------
    def _welcome(self) -> None:
        _, v = self._page(f"Καλώς ήρθες στο {self.product}",
                          "Welcome. Speak instead of typing — in Greek and English, fully on this computer.")
        v.addWidget(_label("Πριν ξεκινήσεις, θα κατεβάσουμε μία φορά το μοντέλο αναγνώρισης ομιλίας "
                           "(περίπου 1,6 GB). Μετά από αυτό, όλα λειτουργούν χωρίς internet και ο ήχος σου "
                           "δεν φεύγει ποτέ από τον υπολογιστή."))
        v.addWidget(_label("We'll download the speech model once (about 1.6 GB). After that everything works "
                           "offline and your voice never leaves this computer.", 9.5, muted=True))
        self._buttons(v, "Συνέχεια  ›", self._start_download)

    def _download(self) -> None:
        _, v = self._page("Λήψη μοντέλου ομιλίας", "Downloading the speech model")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setStyleSheet("QProgressBar { background: #20242a; border: none; border-radius: 5px; }"
                               "QProgressBar::chunk { background: #4ade80; border-radius: 5px; }")
        v.addWidget(self.bar)
        self.dl_text = _label("Σύνδεση… / Connecting…", 10, muted=True)
        v.addWidget(self.dl_text)
        self.dl_error = _label("", 10)
        self.dl_error.setStyleSheet("color: #f87171;")
        v.addWidget(self.dl_error)
        self.retry_btn = self._buttons(v, "Δοκίμασε ξανά / Retry", self._start_download)
        self.retry_btn.hide()

    def _mic(self) -> None:
        _, v = self._page("Έλεγχος μικροφώνου", "Microphone check — say something")
        self.mic_name = _label("", 10.5, True)
        v.addWidget(self.mic_name)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(14)
        self.level.setStyleSheet("QProgressBar { background: #20242a; border: none; border-radius: 7px; }"
                                 "QProgressBar::chunk { background: #4ade80; border-radius: 7px; }")
        v.addWidget(self.level)
        self.mic_hint = _label("", 10, muted=True)
        v.addWidget(self.mic_hint)
        self._buttons(v, "Συνέχεια  ›", self._finish_mic, "Ξανά έλεγχος / Recheck", self._open_mic)

    def _done(self) -> None:
        _, v = self._page("Έτοιμο!", "All set")
        v.addWidget(_label("🎙  <b>Υπαγόρευση</b>: κράτα πατημένο το <b>δεξί Ctrl</b>, μίλα, και άφησέ το. "
                           "Το κείμενο εμφανίζεται εκεί που γράφεις.", 11))
        v.addWidget(_label("⚡  <b>Εντολές</b>: ξεκίνα με «<b>Πάστα,</b>» — π.χ. «Πάστα, άνοιξε το Chrome» ή "
                           "«Πάστα, βάλε την ένταση στο 30».", 11))
        v.addWidget(_label("⎋  <b>Esc</b> ακυρώνει. Θα βρεις το πρόγραμμα στο εικονίδιο κάτω δεξιά στη γραμμή εργασιών.",
                           11))
        v.addWidget(_label("Hold Right Ctrl, speak, release. Say “Pasta, …” for commands. Esc cancels. "
                           "The app lives in the system tray.", 9.5, muted=True))
        self._buttons(v, "Ξεκίνα / Start", self.accept)

    # -- behaviour ----------------------------------------------------------------------
    def _start_download(self) -> None:
        self.stack.setCurrentIndex(1)
        if model_cached():
            self._open_mic()
            return
        self.dl_error.setText("")
        self.retry_btn.hide()
        self._t0 = time.time()
        self.dl = _Downloader()
        self.dl.progress.connect(self._on_progress)
        self.dl.finished.connect(self._on_downloaded)
        self.dl.start()

    def _on_progress(self, got: float, total: float) -> None:
        if total <= 0:
            return
        self.bar.setValue(int(1000 * got / total))
        speed = got / max(time.time() - self._t0, 0.5)
        eta = (total - got) / speed if speed > 0.1 else 0
        self.dl_text.setText(f"{got / 1024:.2f} / {total / 1024:.2f} GB · {speed:.1f} MB/s"
                             + (f" · ~{int(eta // 60)}:{int(eta % 60):02d}" if eta else ""))

    def _on_downloaded(self, error: str) -> None:
        if error:
            self.dl_error.setText("Η λήψη απέτυχε. Έλεγξε τη σύνδεση στο internet και πάτησε «Δοκίμασε ξανά».\n"
                                  f"Download failed: {error[:160]}")
            self.retry_btn.show()
            return
        self._open_mic()

    def _open_mic(self) -> None:
        self.stack.setCurrentIndex(2)
        self._close_mic()
        self._peak = 0.0
        try:
            import sounddevice as sd

            sd._terminate()
            sd._initialize()
            dev = sd.default.device[0]
            if dev is None or dev < 0:
                raise RuntimeError("no default microphone")
            self.mic_name.setText("🎙  " + sd.query_devices(dev)["name"])
            self._stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                          callback=self._mic_cb)
            self._stream.start()
            self.mic_hint.setText("Μίλα — η μπάρα πρέπει να κινείται. / Speak — the bar should move.")
            self._timer = QTimer(self, interval=50, timeout=self._update_level)
            self._timer.start()
        except Exception:
            self._stream = None
            self.mic_name.setText("Δεν βρέθηκε μικρόφωνο / No microphone found")
            self.mic_hint.setText("Σύνδεσε ή άναψε το μικρόφωνο/headset και πάτησε «Ξανά έλεγχος». Μπορείς και να "
                                  "συνεχίσεις — το πρόγραμμα θα το εντοπίσει μόλις συνδεθεί.")

    def _mic_cb(self, indata, frames, t, status) -> None:
        self._peak = max(self._peak, float(np.sqrt(np.mean(indata[:, 0] ** 2))))

    def _update_level(self) -> None:
        self.level.setValue(min(100, int(self._peak * 1200)))
        if self._peak > 0.02:
            self.mic_hint.setText("✓ Σε ακούω! / I can hear you.")
        self._peak *= 0.6

    def _close_mic(self) -> None:
        if getattr(self, "_timer", None):
            self._timer.stop()
        if getattr(self, "_stream", None) is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _finish_mic(self) -> None:
        self._close_mic()
        self.stack.setCurrentIndex(3)

    def done(self, r: int) -> None:  # noqa: D401 - Qt override
        self._close_mic()
        super().done(r)
