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
        self._stream_sr = 0
        self._last_level = 0.0
        self._frames_q: collections.deque[np.ndarray] = collections.deque(maxlen=400)
        self._frames_evt = threading.Event()
        self._stop = threading.Event()
        self.error: str | None = None
        self.device_name = ""

    # -- lifecycle -------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        if self._stream is None or self.error is not None:
            return False
        try:
            return bool(self._stream.active)
        except Exception:
            return False

    def start(self) -> None:
        """Open the input stream; raises if no usable microphone exists."""
        import sounddevice as sd

        device_idx, dev_info = resolve_input_device(self.s.device)
        stream_sr = self.s.sample_rate
        self._stream_sr = stream_sr
        try:
            self._stream = sd.InputStream(
                samplerate=stream_sr, channels=1, dtype="int16", blocksize=0, latency="low",
                device=device_idx, callback=self._callback, finished_callback=self._on_finished,
            )
            self._stream.start()
        except Exception as exc:
            # Fallback for devices (e.g. Windows WDM-KS) that reject 16000 Hz: try native rate
            native_sr = int(dev_info.get("default_samplerate") or 44100)
            if native_sr != stream_sr:
                log.info("Opening microphone %s at native rate %d Hz (resampling to %d Hz)",
                         dev_info.get("name"), native_sr, stream_sr)
                self._stream = sd.InputStream(
                    samplerate=native_sr, channels=1, dtype="int16", blocksize=0, latency="low",
                    device=device_idx, callback=self._callback, finished_callback=self._on_finished,
                )
                self._stream.start()
                self._stream_sr = native_sr
            else:
                raise

        info = sd.query_devices(self._stream.device)
        self.device_name = info.get("name", "") if isinstance(info, dict) else str(info)
        self.error = None
        log.info("Microphone open: %s @ %d Hz (stream %d Hz, input latency %.0f ms)",
                 self.device_name, self.s.sample_rate, self._stream_sr,
                 self._stream.latency * 1000)
        if self.on_frames is not None and not getattr(self, "_frames_started", False):
            self._frames_started = True
            threading.Thread(target=self._frames_loop, name="AudioFrames", daemon=True).start()

    def switch_device(self, device: str) -> bool:
        """Switch input to a different device immediately."""
        self.s.device = device
        self.error = None
        with self._lock:
            self._recording = None
            self._ring.clear()
            self._ring_samples = 0
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        return self.ensure_open()

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
            self.device_name = ""

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
        if getattr(self, "_stream_sr", 0) and self._stream_sr != self.s.sample_rate:
            import scipy.signal
            target_samples = int(round(len(chunk) * self.s.sample_rate / self._stream_sr))
            chunk = scipy.signal.resample(chunk, target_samples).astype(np.int16)
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

    try:
        hostapis = {i: h.get("name", "") for i, h in enumerate(sd.query_hostapis())}
    except Exception:
        hostapis = {}

    default = sd.default.device[0] if (sd.default.device is not None and sd.default.device[0] >= 0) else None
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            api = hostapis.get(d.get("hostapi"), "")
            name = d.get("name", "")
            full_name = f"{name} [{api}]" if api else name
            devices.append({
                "index": i,
                "name": name,
                "hostapi": api,
                "full_name": full_name,
                "default": i == default,
                "channels": d.get("max_input_channels", 0),
            })
    return devices


def resolve_input_device(device_spec: str | int | None) -> tuple[int, dict]:
    """Find the best sounddevice input device index for a given device spec.

    device_spec can be:
      - None or "": Use system default
      - int: Device index
      - str: Device name or full_name ("name [hostapi]")
    """
    import sounddevice as sd

    try:
        hostapis = {i: h.get("name", "") for i, h in enumerate(sd.query_hostapis())}
    except Exception:
        hostapis = {}

    all_devices = sd.query_devices()

    # Case 1: System default
    if not device_spec:
        default_in = sd.default.device[0] if sd.default.device is not None else -1
        if default_in is None or default_in < 0:
            raise RuntimeError("Windows reports no default microphone (is the headset connected and on?)")
        info = all_devices[default_in]
        name = info.get("name", "")
        if "stereo mix" in name.lower():
            real_mics = [i for i, d in enumerate(all_devices)
                         if d.get("max_input_channels", 0) > 0 and "stereo mix" not in d.get("name", "").lower()]
            if not real_mics:
                raise RuntimeError("Windows default input is Stereo Mix (connect or switch on your microphone)")
        return default_in, info

    # Case 2: Integer index or digit string
    if isinstance(device_spec, int) or (isinstance(device_spec, str) and device_spec.isdigit()):
        idx = int(device_spec)
        if 0 <= idx < len(all_devices):
            info = all_devices[idx]
            if info.get("max_input_channels", 0) > 0:
                return idx, info

    # Case 3: String device spec
    spec_str = str(device_spec).strip()
    candidates = []

    def api_rank(api_name: str) -> int:
        low = api_name.lower()
        if "wasapi" in low:
            return 4
        if "directsound" in low:
            return 3
        if "mme" in low:
            return 2
        if "wdm-ks" in low or "wdm" in low:
            return 1
        return 0

    for i, d in enumerate(all_devices):
        if d.get("max_input_channels", 0) > 0:
            api_name = hostapis.get(d.get("hostapi"), "")
            name = d.get("name", "")
            full_label_bracket = f"{name} [{api_name}]"
            full_label_paren = f"{name} ({api_name})"
            score = 0
            if spec_str == full_label_bracket or spec_str == full_label_paren:
                score = 100
            elif spec_str.lower() == name.lower():
                score = 80
            elif spec_str.lower() in full_label_bracket.lower() or spec_str.lower() in full_label_paren.lower():
                score = 60
            elif spec_str.lower() in name.lower() or name.lower() in spec_str.lower():
                score = 40

            if score > 0:
                candidates.append((score, api_rank(api_name), i, d))

    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best_idx = candidates[0][2]
        return best_idx, candidates[0][3]

    raise RuntimeError(f"Selected microphone '{spec_str}' is not connected or turned off")
