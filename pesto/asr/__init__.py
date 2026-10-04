"""Speech recognition engines."""

from ..config import AsrSettings
from .base import Engine, Transcript, guess_language

ENGINE_LABELS = {
    "whisper": "Whisper large-v3-turbo",
    "parakeet": "Parakeet TDT 0.6B v3",
}


def create_engine(name: str, settings: AsrSettings) -> Engine:
    if name == "whisper":
        from .whisper import WhisperEngine

        return WhisperEngine(settings)
    if name == "parakeet":
        from .parakeet import ParakeetEngine

        return ParakeetEngine(settings)
    raise ValueError(f"unknown engine {name!r}")


__all__ = ["Engine", "Transcript", "guess_language", "create_engine", "ENGINE_LABELS"]
