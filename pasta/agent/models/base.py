from typing import Any, Protocol, runtime_checkable

from ..schemas import Decision


@runtime_checkable
class DecisionModel(Protocol):
    """Protocol for finite-action decision models (Decider-2B, Jev, GGUF).

    Does not generate freeform tokens; returns calibrated probability
    distributions over discrete candidate options.
    """

    def decide(self, state: dict[str, Any], questions: list[dict[str, Any]]) -> list[Decision]:
        """Perform typed decision scoring.

        Args:
            state: Dictionary containing current OS/browser/task state.
            questions: List of question dicts, each with 'question' and 'options'.

        Returns:
            List of Decision objects with probabilities for each option.
        """
        ...

    def is_loaded(self) -> bool:
        """Check if model weights are loaded in memory."""
        ...

    def load(self) -> None:
        """Load model into memory (GPU/RAM)."""
        ...

    def unload(self) -> None:
        """Unload model from memory to free VRAM."""
        ...
