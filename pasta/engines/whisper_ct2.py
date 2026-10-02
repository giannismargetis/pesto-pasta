import threading
import time

import numpy as np

from ..config import CACHE_DIR, Config
from ..logging_setup import get_logger
from .base import Engine, TranscriptionResult

log = get_logger("whisper")

_MODELS = {
    "tiny", "base", "small", "medium", "large-v2", "large-v3",
    "large-v3-turbo", "distil-large-v3", "distil-large-v3.5",
}


class WhisperCT2Engine(Engine):
    name = "whisper"
    description = "OpenAI Whisper via faster-whisper (CTranslate2)"

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.model_name = cfg.whisper_model if cfg.whisper_model in _MODELS else "large-v3-turbo"
        self.device = "cpu"
        self.compute_type = cfg.whisper_compute_cpu
        self._model = None
        self._lock = threading.Lock()

    def _cuda_available(self) -> bool:
        try:
            import ctranslate2

            return ctranslate2.get_cuda_device_count() > 0
        except Exception as exc:
            log.warning("CUDA probe failed: %s", exc)
            return False

    def load(self) -> None:
        from faster_whisper import WhisperModel

        started = time.perf_counter()
        download_root = str(CACHE_DIR / "huggingface")

        if self._cuda_available():
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device="cuda",
                    compute_type=self.cfg.whisper_compute_cuda,
                    download_root=download_root,
                    cpu_threads=0,
                    num_workers=1,
                )
                self.device = "cuda"
                self.compute_type = self.cfg.whisper_compute_cuda
            except Exception as exc:
                log.warning("CUDA load failed (%s), falling back to CPU", exc)
                self._model = None
        if self._model is None:
            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type=self.cfg.whisper_compute_cpu,
                download_root=download_root,
                cpu_threads=4,
                num_workers=1,
            )
            self.device = "cpu"
            self.compute_type = self.cfg.whisper_compute_cpu
        self._warmup()
        self._loaded = True
        log.info(
            "Whisper '%s' ready on %s (%s) in %.1fs",
            self.model_name,
            self.device.upper(),
            self.compute_type,
            time.perf_counter() - started,
        )

    def _warmup(self) -> None:
        try:
            silence = np.zeros(16000, dtype=np.float32)
            list(self._model.transcribe(silence, language="en", beam_size=1))
        except Exception as exc:
            log.warning("Warmup skipped: %s", exc)

    def unload(self) -> None:
        with self._lock:
            self._model = None
        self._loaded = False
        log.info("Whisper unloaded")

    def transcribe(
        self, audio: np.ndarray, language: str | None = None, is_partial: bool = False
    ) -> TranscriptionResult:
        with self._lock:
            model = self._model
        if model is None or audio.size == 0:
            return TranscriptionResult("")

        beam_size = 1 if is_partial else max(1, getattr(self.cfg, "whisper_beam_size", 2))
        use_vad = getattr(self.cfg, "whisper_vad_filter", True)

        prompt = "Ελληνικά και English dictation με σωστούς τόνους και σημεία στίξης."
        if language == "en":
            prompt = "English dictation with correct punctuation and capitalization."
        elif language == "el":
            prompt = "Ελληνικά με σωστούς τόνους και σημεία στίξης."

        kwargs = {
            "language": language,
            "beam_size": beam_size,
            "best_of": beam_size,
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "without_timestamps": True,
            "vad_filter": use_vad,
            "initial_prompt": prompt,
        }
        if use_vad:
            kwargs["vad_parameters"] = dict(min_silence_duration_ms=250 if is_partial else 400, speech_pad_ms=200)

        try:
            segments, info = model.transcribe(audio, **kwargs)
            parts = []
            for segment in segments:
                t = segment.text.strip()
                # Filter common Whisper hallucination artifacts
                if t and not any(h in t.lower() for h in [
                    "[music]", "[blank_audio]", "(music)", "thanks for watching",
                    "thank you for watching", "υπότιτλοι", "subtitles by"
                ]):
                    parts.append(t)
            prob = float(getattr(info, "language_probability", 0.0) or 0.0)
            return TranscriptionResult(" ".join(parts), getattr(info, "language", None), prob)
        except Exception as exc:
            log.warning("Whisper transcription error: %s", exc)
            return TranscriptionResult("")
