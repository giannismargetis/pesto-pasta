import math
import re
from typing import Any

from ..schemas import Decision
from .base import DecisionModel


class MockDecisionModel(DecisionModel):
    """Deterministic, fast decision model used for:

    - Unit testing & CI without GPU
    - Offline fallback
    - Sanity checking candidate options
    """

    def __init__(self, default_confidence: float = 0.95) -> None:
        self.default_confidence = default_confidence
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def decide(self, state: dict[str, Any], questions: list[dict[str, Any]]) -> list[Decision]:
        results: list[Decision] = []
        task_str = str(state.get("goal") or state.get("task") or "").lower()
        task_words = set(re.findall(r"\w+", task_str))

        for q in questions:
            question_text = q.get("question", "")
            effective_task = task_str or question_text.lower()
            effective_words = set(re.findall(r"\w+", effective_task))
            options = q.get("options", [])
            if not options:
                continue

            raw_scores: dict[str, float] = {}
            for opt in options:
                opt_str = str(opt).lower()
                opt_words = set(re.findall(r"\w+", opt_str))
                overlap = len(effective_words.intersection(opt_words))

                score = 1.0 + (overlap * 4.0)

                # Prioritize specific action prefixes matching task
                if ("chrome" in effective_task or "browser" in effective_task) and ("chrome" in opt_str or "browser" in opt_str):
                    score += 6.0
                if ("search" in effective_task or "ψάξε" in effective_task) and ("search" in opt_str):
                    score += 7.0
                if ("calc" in effective_task or "calculator" in effective_task) and ("calc" in opt_str):
                    score += 8.0
                if ("vs code" in effective_task or "vscode" in effective_task or "code" in effective_task) and ("code" in opt_str):
                    score += 6.0
                if ("notepad" in effective_task) and ("notepad" in opt_str):
                    score += 7.0
                if ("terminal" in effective_task or "git" in effective_task) and ("git" in opt_str or "terminal" in opt_str):
                    score += 7.0
                if ("python" in effective_task) and ("python" in opt_str):
                    score += 8.0
                if ("new tab" in effective_task or "tab" in effective_task) and ("tab" in opt_str):
                    score += 6.0
                if ("back" in effective_task or "πίσω" in effective_task) and ("back" in opt_str):
                    score += 7.0
                if ("copy" in effective_task or "αντιγραφή" in effective_task) and ("copy" in opt_str):
                    score += 12.0
                if ("paste" in effective_task or "επικόλληση" in effective_task) and ("paste" in opt_str):
                    score += 7.0
                if ("enter" in effective_task) and ("enter" in opt_str):
                    score += 7.0
                if ("type" in effective_task or "write" in effective_task or "γράψε" in effective_task) and ("type" in opt_str):
                    score += 8.0
                if ("scroll" in effective_task) and ("scroll" in opt_str):
                    score += 7.0
                    if ("down" in effective_task or "κάτω" in effective_task) and ("down" in opt_str):
                        score += 3.0
                    elif ("up" in effective_task or "πάνω" in effective_task) and ("up" in opt_str):
                        score += 3.0
                if ("download" in effective_task or "λήψεις" in effective_task) and ("download" in opt_str):
                    score += 7.0
                if ("find" in effective_task or "βρες" in effective_task or "search file" in effective_task) and ("find" in opt_str):
                    score += 8.0
                if ("mute" in effective_task or "σίγαση" in effective_task or "sound" in effective_task) and ("mute" in opt_str):
                    score += 8.0
                if ("minimize" in effective_task or "ελαχιστοποίησε" in effective_task) and ("minimize" in opt_str):
                    score += 9.0
                if ("what is currently open" in effective_task or "τι είναι ανοιχτό" in effective_task or "inspect" in effective_task) and ("inspect" in opt_str):
                    score += 9.0
                if any(ext in effective_task for ext in (".com", ".org", ".io", ".net", ".edu", ".gr", ".dev", ".co", ".ai")) and ("open_url" in opt_str):
                    score += 8.0
                if ("switch" in effective_task or "focus" in effective_task) and ("focus" in opt_str):
                    score += 8.0
                if ("stop" in effective_task or "σταμάτα" in effective_task or "cancel" in effective_task or "στοπ" in effective_task) and ("stop" in opt_str):
                    score += 10.0
                elif opt_str == "stop":
                    score = 0.2

                raw_scores[opt] = score

            # Apply softmax
            max_score = max(raw_scores.values()) if raw_scores else 0.0
            exp_scores = {k: math.exp(v - max_score) for k, v in raw_scores.items()}
            total_exp = sum(exp_scores.values()) or 1.0
            probs = {k: v / total_exp for k, v in exp_scores.items()}

            best_option = max(probs.keys(), key=lambda k: probs[k])
            best_prob = probs[best_option]

            results.append(
                Decision(
                    action_id=best_option,
                    probability=best_prob,
                    confidence=best_prob,
                    raw_scores=probs,
                    question=question_text,
                )
            )

        return results
