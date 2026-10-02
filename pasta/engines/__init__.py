from ..config import Config
from .base import Engine, TranscriptionResult, guess_language, split_long_audio
from .parakeet_onnx import ParakeetOnnxEngine
from .whisper_ct2 import WhisperCT2Engine

__all__ = [
    "Engine",
    "TranscriptionResult",
    "guess_language",
    "split_long_audio",
    "ParakeetOnnxEngine",
    "WhisperCT2Engine",
    "create_engine",
]


def create_engine(name: str, cfg: Config) -> Engine:
    factories = {
        "parakeet": ParakeetOnnxEngine,
        "whisper": WhisperCT2Engine,
    }
    factory = factories.get(name)
    if factory is None:
        raise ValueError(f"Unknown engine '{name}'. Available: {', '.join(factories)}")
    return factory(cfg)
