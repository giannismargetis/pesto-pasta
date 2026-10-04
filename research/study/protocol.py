"""Study protocols: conditions, counterbalancing and phrase assignment.

A protocol is a JSON file in ``research/study/protocols``. Each participant
receives a condition order from a balanced Latin square (Williams design:
every condition appears in every position, and — for an even number of
conditions — every condition follows every other equally often), and a
disjoint, participant-specific set of phrases per condition.
"""

from __future__ import annotations

import json
import random
import zlib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTOCOLS = HERE / "protocols"


@dataclass(frozen=True)
class Condition:
    name: str
    input: str  # keyboard | ptt | vad
    added_latency_ms: int = 0
    live_preview: bool = True
    instructions: str = ""


@dataclass
class Protocol:
    name: str
    language: str  # el | en
    conditions: list[Condition]
    trials_per_condition: int = 8
    practice_trials: int = 2
    rate_each_trial: bool = False  # 7-point perceived-speed rating after every trial
    tlx_after_block: bool = True
    description: str = ""
    research_questions: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, name_or_path: str) -> Protocol:
        path = Path(name_or_path)
        if not path.exists():
            path = PROTOCOLS / f"{name_or_path}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["conditions"] = [Condition(**c) for c in data["conditions"]]
        return cls(**data)

    def phrases(self) -> list[str]:
        lines = (HERE / f"phrases_{self.language}.txt").read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]

    def order(self, participant_index: int) -> list[Condition]:
        rows = latin_square(len(self.conditions))
        return [self.conditions[i] for i in rows[participant_index % len(rows)]]

    def assign(self, participant: str, participant_index: int) -> list[tuple[Condition, list[str], list[str]]]:
        """[(condition, practice phrases, trial phrases)] in presentation order."""
        per_block = self.trials_per_condition + self.practice_trials
        pool = self.phrases()
        needed = per_block * len(self.conditions)
        if needed > len(pool):
            raise ValueError(f"protocol needs {needed} phrases, only {len(pool)} available")
        rng = random.Random(zlib.crc32(f"{self.name}:{participant}".encode()))
        rng.shuffle(pool)
        out = []
        for k, cond in enumerate(self.order(participant_index)):
            chunk = pool[k * per_block:(k + 1) * per_block]
            out.append((cond, chunk[: self.practice_trials], chunk[self.practice_trials:]))
        return out


def latin_square(n: int) -> list[list[int]]:
    """Williams balanced Latin square rows (2n rows when n is odd)."""
    first = [0]
    lo, hi = 1, n - 1
    take_lo = True
    while len(first) < n:
        first.append(lo if take_lo else hi)
        lo, hi = (lo + 1, hi) if take_lo else (lo, hi - 1)
        take_lo = not take_lo
    rows = [[(c + r) % n for c in first] for r in range(n)]
    if n % 2:
        rows += [list(reversed(r)) for r in rows]
    return rows
