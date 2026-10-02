from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..config import Config


@dataclass
class TranscriptionResult:
    text: str
    language: str | None = None
    language_probability: float = 0.0


GREEK_RANGE = (0x0370, 0x03FF)


def guess_language(text: str) -> str | None:
    if not text:
        return None
    greek = sum(1 for ch in text if GREEK_RANGE[0] <= ord(ch) <= GREEK_RANGE[1])
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if greek == 0 and latin == 0:
        return None
    return "el" if greek >= latin else "en"


class Engine(ABC):
    name: str = ""
    description: str = ""

    def __init__(self) -> None:
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def unload(self) -> None: ...

    @abstractmethod
    def transcribe(
        self, audio: np.ndarray, language: str | None = None, is_partial: bool = False
    ) -> TranscriptionResult: ...

    @classmethod
    def download(cls, cfg: Config) -> None:
        engine = cls()
        engine.load()
        engine.unload()


def split_long_audio(audio: np.ndarray, sample_rate: int, max_seconds: float = 14.0) -> list[np.ndarray]:
    max_samples = int(max_seconds * sample_rate)
    if audio.size <= max_samples:
        return [audio]

    def _split(chunk: np.ndarray) -> list[np.ndarray]:
        if chunk.size <= max_samples:
            return [chunk]
        middle = chunk.size // 2
        window = min(sample_rate, chunk.size // 4)
        search_start, search_end = middle - window // 2, middle + window // 2
        energy = np.abs(chunk[search_start:search_end])
        cut = int(search_start + np.argmin(energy))
        cut = max(int(0.5 * sample_rate), min(cut, chunk.size - int(0.5 * sample_rate)))
        return _split(chunk[:cut]) + _split(chunk[cut:])

    return _split(audio)
