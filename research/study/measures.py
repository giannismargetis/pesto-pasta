"""Text-entry and workload measures (standard definitions).

* Words per minute (MacKenzie 2002): WPM = (|T| − 1) / S × 60 / 5, where T is
  the final transcribed text and S the seconds from the first input to the
  end of the trial. One "word" = 5 characters including spaces.
* Minimum-string-distance error rate (Soukoreff & MacKenzie 2001):
  MSD(P, T) / max(|P|, |T|) × 100, character level, P = presented phrase.
  Reported both literally and case/punctuation-insensitively, because ASR
  output differs from typed text mainly in formatting.
* Raw NASA-TLX (Hart 2006): unweighted mean of the six 0–100 subscales.
"""

from __future__ import annotations

from research.metrics import edit_distance, normalize

TLX_SCALES = ("mental", "physical", "temporal", "performance", "effort", "frustration")


def wpm(transcribed: str, seconds: float) -> float:
    t = transcribed.strip()
    if seconds <= 0 or len(t) < 2:
        return 0.0
    return (len(t) - 1) / seconds * 60.0 / 5.0


def msd_error_rate(presented: str, transcribed: str, *, normalized: bool = False) -> float:
    p, t = presented.strip(), transcribed.strip()
    if normalized:
        p, t = normalize(p), normalize(t)
    longest = max(len(p), len(t))
    return 100.0 * edit_distance(p, t) / longest if longest else 0.0


def tlx_raw(answers: dict[str, float]) -> float:
    missing = [s for s in TLX_SCALES if s not in answers]
    if missing:
        raise ValueError(f"missing NASA-TLX subscales: {missing}")
    return sum(float(answers[s]) for s in TLX_SCALES) / len(TLX_SCALES)
