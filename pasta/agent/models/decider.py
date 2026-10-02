import json
from typing import Any

from ...logging_setup import get_logger
from ..schemas import Decision
from .base import DecisionModel
from .mock import MockDecisionModel

log = get_logger("model.decider")


class DeciderPyTorchModel(DecisionModel):
    """Mapika/decider-2b decision model using PyTorch / CUDA runtime.

    Scores candidate actions directly via single forward pass.
    """

    def __init__(self, model_id: str = "Mapika/decider-2b", device: str = "cuda") -> None:
        self.model_id = model_id
        self.device = device
        self._model = None
        self._load_attempted = False
        self._fallback = MockDecisionModel()

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        self._load_attempted = True
        log.info("Loading Decider model: %s on %s...", self.model_id, self.device)
        try:
            from decider.infer import Decider

            self._model = Decider(self.model_id)
            log.info("Decider model loaded successfully.")
        except Exception as exc:
            log.warning("Failed to load Decider from HuggingFace (%s), using fallback: %s", self.model_id, exc)
            self._model = None

    def unload(self) -> None:
        if self._model is not None:
            log.info("Unloading Decider model from VRAM...")
            self._model = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    def decide(self, state: dict[str, Any], questions: list[dict[str, Any]]) -> list[Decision]:
        if self._model is None and not self._load_attempted:
            self.load()

        if self._model is None:
            # Use deterministic heuristic fallback
            return self._fallback.decide(state, questions)

        state_str = json.dumps(state) if isinstance(state, dict) else str(state)

        try:
            raw_decisions = self._model.decide(state_str, questions)
            results: list[Decision] = []

            for i, d in enumerate(raw_decisions):
                q = questions[i] if i < len(questions) else {}
                q_text = q.get("question", "")

                # decider returns typed decision results with choice and probabilities
                if isinstance(d, dict):
                    action_id = str(d.get("choice", ""))
                    probs = d.get("probabilities", {})
                    confidence = float(d.get("confidence", max(probs.values()) if probs else 0.8))
                elif hasattr(d, "choice"):
                    action_id = str(getattr(d, "choice"))
                    probs = getattr(d, "probabilities", {}) or {}
                    confidence = float(getattr(d, "confidence", 0.85))
                else:
                    action_id = str(d)
                    probs = {action_id: 1.0}
                    confidence = 0.85

                results.append(
                    Decision(
                        action_id=action_id,
                        probability=confidence,
                        confidence=confidence,
                        raw_scores=probs,
                        question=q_text,
                    )
                )

            return results
        except Exception as exc:
            log.error("Decider inference failed (%s), falling back: %s", self.model_id, exc)
            return self._fallback.decide(state, questions)
