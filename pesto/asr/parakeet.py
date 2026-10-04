"""NVIDIA Parakeet-TDT 0.6B v3 (25 European languages incl. Greek) via onnx-asr.

Unlike Whisper, a FastConformer-TDT encoder processes only the real audio
length (no 30 s padding), so cost scales with utterance length. The model has
no language-ID output; language is guessed from the output script.

GPU execution needs ``onnxruntime-gpu`` plus CUDA 12 / cuDNN 9 runtime DLLs.
The old code requested the CUDA provider without checking that onnxruntime
actually offered it; with the CPU-only wheel installed it silently ran on CPU
while the UI claimed CUDA. We report the provider that was really bound.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from pathlib import Path

import numpy as np

from ..config import AsrSettings
from ..log import get_logger
from .base import Engine, Transcript, guess_language
from .models import PARAKEET_REPOS, resolve_snapshot

log = get_logger("asr.parakeet")

MAX_CHUNK_S = 25.0  # attention cost grows quadratically; split very long input at quiet points


def _register_cuda_dlls() -> None:
    """Make CUDA/cuDNN DLLs visible to onnxruntime-gpu without importing torch."""
    try:
        import onnxruntime as ort

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls(cuda=True, cudnn=True, msvc=False)
    except Exception as exc:
        log.debug("preload_dlls: %s", exc)
    for pkg in ("torch", "ctranslate2"):
        spec = importlib.util.find_spec(pkg)
        if spec and spec.origin:
            lib = Path(spec.origin).parent / ("lib" if pkg == "torch" else "")
            if lib.is_dir() and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(lib))
                os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")


def split_at_quiet_points(audio: np.ndarray, sr: int, max_s: float = MAX_CHUNK_S) -> list[np.ndarray]:
    max_len = int(max_s * sr)
    if audio.size <= max_len:
        return [audio]
    mid = audio.size // 2
    win = min(sr, audio.size // 4)
    lo = mid - win // 2
    # 20 ms RMS frames; cut at the quietest frame near the middle
    frames = audio[lo : lo + win][: (win // 320) * 320].reshape(-1, 320)
    cut = lo + int(np.argmin((frames**2).mean(axis=1))) * 320 + 160
    return split_at_quiet_points(audio[:cut], sr, max_s) + split_at_quiet_points(audio[cut:], sr, max_s)


class ParakeetEngine(Engine):
    name = "parakeet"

    def __init__(self, settings: AsrSettings, sample_rate: int = 16000) -> None:
        super().__init__()
        self.s = settings
        self.sr = sample_rate
        self._model = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            import onnxruntime as ort

            want_gpu = self.s.device in ("auto", "cuda") and "CUDAExecutionProvider" in ort.get_available_providers()
            if want_gpu:
                _register_cuda_dlls()
            import onnx_asr

            quant = self.s.parakeet_quantization or None
            repo = PARAKEET_REPOS.get(self.s.parakeet_model, self.s.parakeet_model)
            pattern = ["*.int8.onnx", "config.json", "vocab.txt"] if quant == "int8" else [
                "encoder-model.onnx", "encoder-model.onnx.data", "decoder_joint-model.onnx", "config.json", "vocab.txt"]
            path = resolve_snapshot(repo, allow_patterns=pattern)
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if want_gpu else ["CPUExecutionProvider"]
            self._model = onnx_asr.load_model(self.s.parakeet_model, path, quantization=quant, providers=providers)
            self.device = self._bound_provider() or "cpu"
        self.transcribe(np.zeros(self.sr, dtype=np.float32))  # warm up kernels / allocator
        log.info("Parakeet ready on %s (quantization=%s)", self.device, self.s.parakeet_quantization or "none")

    def _bound_provider(self) -> str | None:
        """Inspect the encoder session for the provider actually in use."""
        try:
            asr = getattr(self._model, "asr", self._model)
            session = getattr(asr, "_encoder", None)
            providers = session.get_providers() if session is not None else []
            if providers:
                return "cuda" if providers[0] == "CUDAExecutionProvider" else "cpu"
        except Exception:
            pass
        return None

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self.device = "unloaded"

    def transcribe(self, audio, language=None, *, preview=False) -> Transcript:
        t0 = time.perf_counter()
        with self._lock:
            model = self._model
            if model is None or audio.size == 0:
                return Transcript("", no_speech=True)
            parts = []
            for chunk in split_at_quiet_points(np.ascontiguousarray(audio, dtype=np.float32), self.sr):
                result = model.recognize(chunk, sample_rate=self.sr)
                text = (result if isinstance(result, str) else getattr(result, "text", "")).strip()
                if text:
                    parts.append(text)
        text = " ".join(parts)
        lang = guess_language(text) or language
        return Transcript(text, lang, 1.0 if text else 0.0, {"total": (time.perf_counter() - t0) * 1e3},
                          no_speech=not text)
