"""Silero VAD v6 (ONNX, CPU) — used for two things:

* a **speech gate** before ASR: a press with no speech is answered in a few
  milliseconds instead of running a 30-second Whisper encoder (and Whisper's
  well-known hallucinations on silence, e.g. "Thanks for watching", vanish);
* the **hands-free (VAD) input mode** endpointing, via :class:`StreamingVad`.

faster-whisper's own wrapper resets the recurrent state on every call, so it
cannot stream; this one carries ``h``/``c`` and the 64-sample context across
frames as the model expects.
"""

from __future__ import annotations

import os
import threading

import numpy as np

FRAME = 512  # samples @ 16 kHz = 32 ms
CONTEXT = 64

_session = None
_session_lock = threading.Lock()


def _get_session():
    global _session
    with _session_lock:
        if _session is None:
            import onnxruntime
            from faster_whisper.utils import get_assets_path

            opts = onnxruntime.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.log_severity_level = 4
            _session = onnxruntime.InferenceSession(
                os.path.join(get_assets_path(), "silero_vad_v6.onnx"),
                providers=["CPUExecutionProvider"],
                sess_options=opts,
            )
        return _session


def speech_probabilities(audio: np.ndarray) -> np.ndarray:
    """Per-frame (32 ms) speech probability for a whole buffer (batched)."""
    if audio.size < FRAME:
        return np.zeros(0, dtype=np.float32)
    n = audio.size // FRAME
    frames = audio[: n * FRAME].astype(np.float32).reshape(n, FRAME)
    context = np.zeros((n, CONTEXT), dtype=np.float32)
    context[1:] = frames[:-1, -CONTEXT:]
    batch = np.concatenate([context, frames], axis=1)
    h = np.zeros((1, 1, 128), dtype=np.float32)
    c = np.zeros((1, 1, 128), dtype=np.float32)
    out, _, _ = _get_session().run(None, {"input": batch, "h": h, "c": c})
    return np.asarray(out, dtype=np.float32).reshape(-1)


def speech_seconds(audio: np.ndarray, threshold: float = 0.5) -> float:
    probs = speech_probabilities(audio)
    return float((probs >= threshold).sum()) * FRAME / 16000.0


class StreamingVad:
    """Frame-by-frame VAD with hysteresis, for hands-free endpointing."""

    def __init__(self, threshold: float = 0.5, neg_threshold: float | None = None) -> None:
        self.threshold = threshold
        self.neg_threshold = neg_threshold if neg_threshold is not None else max(threshold - 0.15, 0.01)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self.in_speech = False

    def process(self, chunk: np.ndarray) -> list[tuple[float, bool]]:
        """Feed audio; returns ``(probability, is_speech)`` for each full frame."""
        self._pending = np.concatenate([self._pending, chunk.astype(np.float32)])
        results = []
        session = _get_session()
        while self._pending.size >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            x = np.concatenate([self._context, frame[None, :]], axis=1)
            out, self._h, self._c = session.run(None, {"input": x, "h": self._h, "c": self._c})
            self._context = frame[None, -CONTEXT:]
            p = float(np.asarray(out).reshape(-1)[0])
            if self.in_speech:
                self.in_speech = p >= self.neg_threshold
            else:
                self.in_speech = p >= self.threshold
            results.append((p, self.in_speech))
        return results
