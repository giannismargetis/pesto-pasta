"""Microphone capture.

The input stream stays open so recording starts with zero device latency, and a
ring buffer keeps the last ``preroll_ms`` of audio: people routinely start
speaking at the same instant they press the key, and the first syllable used
to be clipped. The PortAudio callback only copies data; all analysis happens
on other threads.
"""

from __future__ import annotations

import collections
import threading
import time
from collections.abc import Callable

import numpy as np

from .config import AudioSettings
from .log import get_logger

log = get_logger("audio")


class Recording:
    """Audio of one utterance, with timing anchors in ``perf_counter`` time."""

    def __init__(self, preroll: list[np.ndarray], sample_rate: int, t_start: float) -> None:
        self.sample_rate = sample_rate
        self.preroll_samples = sum(c.size for c in preroll)
        self.chunks: list[np.ndarray] = list(preroll)
        self.limit_hit = False
        self.t_start = t_start  # perf_counter at the first *live* sample (key press)
        self.samples = self.preroll_samples

    def append(self, chunk: np.ndarray) -> None:
        self.chunks.append(chunk)
        self.samples += chunk.size

    @property
    def seconds(self) -> float:
        return self.samples / self.sample_rate

    def audio(self) -> np.ndarray:
        if not self.chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.chunks).astype(np.float32) / 32768.0

    def time_of(self, sample_index: int) -> float:
        """perf_counter time at which ``sample_index`` was captured."""
        return self.t_start + (sample_index - self.preroll_samples) / self.sample_rate


class Microphone:
    def __init__(
        self,
        settings: AudioSettings,
        on_level: Callable[[float], None] | None = None,
        on_frames: Callable[[np.ndarray], None] | None = None,
        on_limit: Callable[[], None] | None = None,
    ) -> None:
        self.s = settings
        self.on_level = on_level
        self.on_frames = on_frames  # raw int16 chunks for hands-free VAD (called off the audio thread)
        self.on_limit = on_limit  # maximum utterance length reached
        self._lock = threading.Lock()
        self._ring: collections.deque[np.ndarray] = collections.deque()
        self._ring_samples = 0
        self._recording: Recording | None = None
        self._stream = None
        self._last_level = 0.0
        self._frames_q: collections.deque[np.ndarray] = collections.deque(maxlen=400)
        self._frames_evt = threading.Event()
        self._stop = threading.Event()
        self.error: str | None = None
        self.device_name = ""

    # -- lifecycle -------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._stream is not None and bool(getattr(self._stream, "active", False))

    def start(self) -> None:
        """Open the input stream; raises if no usable microphone exists."""
        import sounddevice as sd

        device = self.s.device or None
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        if device is None:
            default_in = sd.default.device[0] if sd.default.device is not None else -1
            if default_in is None or default_in < 0:
                raise RuntimeError("Windows reports no default microphone (is the headset connected and on?)")
        self._stream = sd.InputStream(
            samplerate=self.s.sample_rate, channels=1, dtype="int16", blocksize=0, latency="low",
            device=device, callback=self._callback, finished_callback=self._on_finished,
        )
        self._stream.start()
        info = sd.query_devices(self._stream.device)
        self.device_name = info.get("name", "") if isinstance(info, dict) else str(info)
        self.error = None
        log.info("Microphone open: %s @ %d Hz (input latency %.0f ms)", self.device_name, self.s.sample_rate,
                 self._stream.latency * 1000)
        if self.on_frames is not None and not getattr(self, "_frames_started", False):
            self._frames_started = True
            threading.Thread(target=self._frames_loop, name="AudioFrames", daemon=True).start()

    def ensure_open(self) -> bool:
        """Reopen the microphone if it is closed or was unplugged.

        PortAudio enumerates devices only when it initialises, so a headset
        switched on after start-up is invisible until it is re-initialised.
        """
        if self.is_open:
            return True
        import sounddevice as sd

        with self._lock:
            self._recording = None
        try:
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            sd._terminate()
            sd._initialize()
            self.start()
            return True
        except Exception as exc:
            if str(exc) != self.error:
                log.warning("Microphone unavailable: %s", exc)
            self.error = str(exc)
            self.device_name = ""
            return False

    def _on_finished(self) -> None:
        if not self._stop.is_set():
            log.warning("Microphone stream stopped (device unplugged?)")
            self.error = "microphone disconnected"

    def close(self) -> None:
        self._stop.set()
        self._frames_evt.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    # -- recording -------------------------------------------------------------------
    def begin(self, t_start: float | None = None) -> Recording:
        with self._lock:
            rec = Recording(list(self._ring), self.s.sample_rate, t_start or time.perf_counter())
            self._recording = rec
        return rec

    def end(self) -> Recording | None:
        with self._lock:
            rec, self._recording = self._recording, None
        return rec

    @property
    def recording(self) -> bool:
        return self._recording is not None

    def snapshot(self) -> np.ndarray | None:
        """Copy of the in-progress recording (for live preview)."""
        with self._lock:
            rec = self._recording
            if rec is None:
                return None
            chunks = list(rec.chunks)
        return np.concatenate(chunks).astype(np.float32) / 32768.0 if chunks else None

    # -- PortAudio thread ------------------------------------------------------------
    def _callback(self, indata, frames, time_info, status) -> None:
        chunk = indata[:, 0].copy()
        preroll_max = self.s.preroll_ms * self.s.sample_rate // 1000
        with self._lock:
            if self._recording is not None:
                self._recording.append(chunk)
                if self._recording.seconds >= self.s.max_utterance_s and not self._recording.limit_hit:
                    self._recording.limit_hit = True
                    if self.on_limit is not None:
                        threading.Thread(target=self.on_limit, name="AudioLimit", daemon=True).start()
            self._ring.append(chunk)
            self._ring_samples += chunk.size
            while self._ring and self._ring_samples - self._ring[0].size >= preroll_max:
                self._ring_samples -= self._ring.popleft().size
        if self.on_frames is not None:
            self._frames_q.append(chunk)
            self._frames_evt.set()
        if self.on_level is not None:
            now = time.perf_counter()
            if now - self._last_level >= 1 / 30:
                self._last_level = now
                rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32768.0) ** 2))) if chunk.size else 0.0
                try:
                    self.on_level(rms)
                except Exception:
                    pass

    def _frames_loop(self) -> None:
        while not self._stop.is_set():
            self._frames_evt.wait(0.2)
            self._frames_evt.clear()
            while self._frames_q:
                chunk = self._frames_q.popleft()
                try:
                    self.on_frames(chunk)
                except Exception:
                    log.exception("frame consumer failed")


def list_input_devices() -> list[dict]:
    import sounddevice as sd

    default = sd.default.device[0] if sd.default.device else None
    return [
        {"index": i, "name": d["name"], "default": i == default, "channels": d["max_input_channels"]}
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]
