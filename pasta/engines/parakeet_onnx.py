import threading
import time

import numpy as np

from ..config import Config
from ..logging_setup import get_logger
from .base import Engine, TranscriptionResult, guess_language, split_long_audio

log = get_logger("parakeet")


def resolve_providers(preference: str) -> list[str] | None:
    try:
        import onnxruntime as ort

        available = ort.get_available_providers()
    except Exception as exc:
        log.warning("onnxruntime unavailable (%s), using onnx-asr defaults", exc)
        return None
    if preference == "cpu":
        return ["CPUExecutionProvider"]
    wanted = {
        "cuda": ["CUDAExecutionProvider"],
        "directml": ["DmlExecutionProvider"],
        "tensorrt": ["TensorrtExecutionProvider"],
    }.get(preference, ["TensorrtExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider"])
    providers = [p for p in wanted if p in available]
    if "CPUExecutionProvider" in available:
        providers.append("CPUExecutionProvider")
    return providers or None


class ParakeetOnnxEngine(Engine):
    name = "parakeet"
    description = "NVIDIA Parakeet-TDT 0.6B v3 via ONNX (25 languages incl. Greek)"

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.model_name = cfg.parakeet_model
        self.quantization = cfg.parakeet_quantization or None
        self.device_label = "cpu"
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        import onnx_asr

        started = time.perf_counter()
        providers = resolve_providers(self.cfg.parakeet_provider.lower())
        load_kwargs = {"quantization": self.quantization}
        if providers:
            load_kwargs["providers"] = providers
            self.device_label = providers[0].replace("ExecutionProvider", "").lower() or "cpu"
        else:
            self.device_label = "default"
        with self._lock:
            self._model = onnx_asr.load_model(self.model_name, **load_kwargs)
        self._loaded = True
        log.info(
            "Parakeet '%s' (int8=%s) ready on %s in %.1fs",
            self.model_name,
            self.quantization,
            self.device_label,
            time.perf_counter() - started,
        )

    def unload(self) -> None:
        with self._lock:
            self._model = None
        self._loaded = False
        log.info("Parakeet unloaded")

    @staticmethod
    def _result_text(result) -> str:
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, (list, tuple)):
            texts = [ParakeetOnnxEngine._result_text(item) for item in result]
            return " ".join(t for t in texts if t)
        return (getattr(result, "text", "") or "").strip()

    def transcribe(
        self, audio: np.ndarray, language: str | None = None, is_partial: bool = False
    ) -> TranscriptionResult:
        with self._lock:
            model = self._model
        if model is None or audio.size == 0:
            return TranscriptionResult("")
        parts = []
        for chunk in split_long_audio(audio, self.cfg.sample_rate):
            result = model.recognize(chunk.astype(np.float32), sample_rate=self.cfg.sample_rate)
            text = self._result_text(result)
            if text:
                parts.append(text)
        text = " ".join(parts).strip()
        return TranscriptionResult(text, guess_language(text), 1.0 if text else 0.0)
