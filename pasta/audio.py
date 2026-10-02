import threading
import time

import numpy as np

from .config import Config
from .logging_setup import get_logger

log = get_logger("audio")

SPEECH_ENERGY_THRESHOLD = 0.005


class AudioCapture(threading.Thread):
    def __init__(self, cfg: Config, on_partial, on_energy, on_auto_finalize=None) -> None:
        super().__init__(name="Audio", daemon=True)
        self.cfg = cfg
        self.on_partial = on_partial
        self.on_energy = on_energy
        self.on_auto_finalize = on_auto_finalize
        self.shutdown = threading.Event()
        self.recording = threading.Event()

        self._lock = threading.Lock()
        self._session: list[np.ndarray] = []
        self._pending: list[np.ndarray] = []
        self._pending_samples = 0
        self._has_speech = False
        self._silent_samples = 0
        self._auto_finalizing = False

        self.silence_flush_samples = int(cfg.silence_flush_seconds * cfg.sample_rate)
        self.partial_flush_samples = int(cfg.partial_chunk_seconds * cfg.sample_rate)
        self.max_session_samples = int(cfg.max_recording_seconds * cfg.sample_rate)

    def begin_session(self) -> None:
        with self._lock:
            self._session.clear()
            self._pending.clear()
            self._pending_samples = 0
            self._has_speech = False
            self._silent_samples = 0
            self._auto_finalizing = False
        self.recording.set()

    def end_session(self) -> np.ndarray:
        self.recording.clear()
        with self._lock:
            chunks = self._session[:]
            self._session.clear()
            self._pending.clear()
            self._pending_samples = 0
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32) / 32768.0

    def _emit_partial(self) -> None:
        with self._lock:
            if not self._session:
                return
            audio = np.concatenate(self._session).astype(np.float32) / 32768.0
            self._pending.clear()
            self._pending_samples = 0
        try:
            self.on_partial(audio)
        except Exception as exc:
            log.warning("partial callback failed: %s", exc)

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("Audio stream status: %s", status)
        chunk = indata[:, 0].copy()

        energy = float(np.mean(np.abs(chunk))) / 32768.0
        try:
            self.on_energy(energy)
        except Exception:
            pass

        if not self.recording.is_set():
            return

        finalize_now = False
        do_flush = False
        with self._lock:
            self._session.append(chunk)
            self._pending.append(chunk)
            self._pending_samples += frames

            if energy > SPEECH_ENERGY_THRESHOLD:
                self._has_speech = True
                self._silent_samples = 0
            elif self._has_speech:
                self._silent_samples += frames

            flush = False
            if self._pending_samples >= self.partial_flush_samples:
                flush = True
            elif (
                self._pending_samples >= int(0.5 * self.cfg.sample_rate)
                and self._silent_samples >= self.silence_flush_samples
            ):
                flush = True

            do_flush = flush and self._has_speech
            if do_flush:
                self._has_speech = False
                self._silent_samples = 0

            session_samples = sum(c.shape[0] for c in self._session)
            if session_samples >= self.max_session_samples and not self._auto_finalizing:
                self._auto_finalizing = True
                finalize_now = True

        if do_flush:
            self._emit_partial()

        if finalize_now and self.on_auto_finalize is not None:
            log.info("Max recording length (%ds) reached", self.cfg.max_recording_seconds)
            try:
                self.on_auto_finalize()
            except Exception as exc:
                log.error("auto-finalize failed: %s", exc)

    def run(self) -> None:
        try:
            import sounddevice as sd

            stream = sd.InputStream(
                samplerate=self.cfg.sample_rate,
                channels=1,
                dtype=np.int16,
                blocksize=0,
                latency="low",
                callback=self._callback,
            )
            with stream:
                log.info("Microphone stream active (%d Hz)", self.cfg.sample_rate)
                while not self.shutdown.is_set():
                    time.sleep(0.1)
        except Exception as exc:
            log.error("Audio thread crashed: %s", exc)
            self.shutdown.set()
