from pathlib import Path
from typing import Any

from ...config import CACHE_DIR
from ...logging_setup import get_logger
from ..schemas import Decision
from .base import DecisionModel
from .mock import MockDecisionModel

log = get_logger("model.gguf")


class DeciderGGUFModel(DecisionModel):
    """GGUF runtime for Mapika/decider-2b-GGUF (e.g.

    decider-2b-v11-Q4_K_M.gguf).
    """

    def __init__(
        self,
        model_filename: str = "decider-2b-v11-Q4_K_M.gguf",
        model_path: Path | None = None,
    ) -> None:
        self.model_filename = model_filename
        self.model_path = model_path or (CACHE_DIR / "models" / model_filename)
        self._engine = None
        self._fallback = MockDecisionModel()

    def is_loaded(self) -> bool:
        return self._engine is not None

    def load(self) -> None:
        if self._engine is not None:
            return
        if not self.model_path.exists():
            log.warning("GGUF model file not found at %s. Using fallback.", self.model_path)
            return

        try:
            from decider.engine_gguf import GGUFEngine

            self._engine = GGUFEngine(str(self.model_path))
            log.info("Loaded GGUF engine with model %s", self.model_path)
        except Exception as exc:
            log.warning("Failed to initialize GGUF engine: %s. Using fallback.", exc)
            self._engine = None

    def unload(self) -> None:
        if self._engine is not None:
            log.info("Unloading GGUF model...")
            self._engine = None

    def decide(self, state: dict[str, Any], questions: list[dict[str, Any]]) -> list[Decision]:
        if self._engine is None:
            try:
                self.load()
            except Exception:
                pass

        if self._engine is None:
            return self._fallback.decide(state, questions)

        try:
            # GGUF inference through decider engine
            # Returns decisions with probabilities
            res = self._engine.decide(state, questions)
            results: list[Decision] = []
            for i, r in enumerate(res):
                q = questions[i] if i < len(questions) else {}
                action_id = str(r.get("choice", "")) if isinstance(r, dict) else str(r)
                probs = r.get("probabilities", {}) if isinstance(r, dict) else {action_id: 1.0}
                confidence = float(r.get("confidence", max(probs.values()) if probs else 0.8))

                results.append(
                    Decision(
                        action_id=action_id,
                        probability=confidence,
                        confidence=confidence,
                        raw_scores=probs,
                        question=q.get("question", ""),
                    )
                )
            return results
        except Exception as exc:
            log.error("GGUF decide failed: %s, falling back", exc)
            return self._fallback.decide(state, questions)
