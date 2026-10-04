"""Engine interface shared by all speech recognisers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

GREEK = (0x0370, 0x03FF)
GREEK_EXT = (0x1F00, 0x1FFF)


@dataclass
class Transcript:
    text: str
    language: str | None = None
    language_prob: float = 0.0
    timings_ms: dict[str, float] = field(default_factory=dict)  # stage -> ms
    no_speech: bool = False


def guess_language(text: str) -> str | None:
    """Script-based guess (Greek vs Latin) for engines without language ID."""
    greek = latin = 0
    for ch in text:
        o = ord(ch)
        if GREEK[0] <= o <= GREEK[1] or GREEK_EXT[0] <= o <= GREEK_EXT[1]:
            greek += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
    if not greek and not latin:
        return None
    return "el" if greek >= latin else "en"


class Engine(ABC):
    name = ""

    def __init__(self) -> None:
        self.device = "unloaded"

    @property
    @abstractmethod
    def loaded(self) -> bool: ...

    @abstractmethod
    def load(self) -> None:
        """Load weights. Must be idempotent and safe to call from any thread."""

    @abstractmethod
    def unload(self) -> None: ...

    @abstractmethod
    def transcribe(self, audio: np.ndarray, language: str | None = None, *, preview: bool = False) -> Transcript:
        """Transcribe 16 kHz mono float32 audio.

        ``language`` forces a language; ``None`` lets the engine choose among
        the configured candidate languages. ``preview`` requests the cheapest
        decoding settings (used for live partial results).
        """
