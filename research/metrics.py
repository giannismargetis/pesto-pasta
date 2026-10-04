"""Accuracy and latency metrics used by every evaluation in this repository.

Design notes (see docs/EVALUATION.md for the full methodology):

* WER/CER are computed at **corpus level** (total edits / total reference
  units), which is the standard in ASR literature; per-utterance values are
  kept only for distributions and paired tests.
* Three text views are reported because they answer different questions:
    - ``normalized``  : case/punctuation-insensitive (classic ASR WER)
    - ``no_accents``  : additionally strips Greek tonos/diaeresis, isolating
                        diacritic errors (CER_normalized - CER_no_accents)
    - ``formatted``   : case- and punctuation-sensitive tokens, i.e. what a
                        dictation user actually receives
* Confidence intervals use a percentile bootstrap over utterances with a fixed
  seed, so reruns produce identical intervals.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

_APOSTROPHES = "'’ʼ`´"
_WS = re.compile(r"\s+")
_FORMATTED_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn"))


def normalize(text: str, *, accents: bool = True) -> str:
    """Case/punctuation-insensitive normalization for Greek and English."""
    text = unicodedata.normalize("NFC", text).lower().replace("ς", "σ")
    for ch in _APOSTROPHES:
        text = text.replace(ch, "")
    text = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in text)
    if not accents:
        text = _strip_accents(text)
    return _WS.sub(" ", text).strip()


def formatted_tokens(text: str) -> list[str]:
    """Tokens that keep case and punctuation (punctuation marks are tokens)."""
    return _FORMATTED_TOKEN.findall(unicodedata.normalize("NFC", text))


def edit_distance(ref: Sequence, hyp: Sequence) -> int:
    """Levenshtein distance (unit costs) between two sequences."""
    if len(ref) < len(hyp):
        ref, hyp = hyp, ref
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class UtteranceScore:
    """Edit counts for one utterance under every text view."""

    word_edits: int
    words: int
    char_edits: int
    chars: int
    char_edits_no_accents: int
    chars_no_accents: int
    fmt_edits: int
    fmt_tokens: int

    @property
    def wer(self) -> float:
        return self.word_edits / max(self.words, 1)

    @property
    def cer(self) -> float:
        return self.char_edits / max(self.chars, 1)


def score(reference: str, hypothesis: str) -> UtteranceScore:
    ref_n, hyp_n = normalize(reference), normalize(hypothesis)
    ref_a, hyp_a = normalize(reference, accents=False), normalize(hypothesis, accents=False)
    ref_f, hyp_f = formatted_tokens(reference), formatted_tokens(hypothesis)
    return UtteranceScore(
        word_edits=edit_distance(ref_n.split(), hyp_n.split()),
        words=len(ref_n.split()),
        char_edits=edit_distance(ref_n, hyp_n),
        chars=len(ref_n),
        char_edits_no_accents=edit_distance(ref_a, hyp_a),
        chars_no_accents=len(ref_a),
        fmt_edits=edit_distance(ref_f, hyp_f),
        fmt_tokens=len(ref_f),
    )


_RATE_FIELDS = {
    "wer": ("word_edits", "words"),
    "cer": ("char_edits", "chars"),
    "cer_no_accents": ("char_edits_no_accents", "chars_no_accents"),
    "wer_formatted": ("fmt_edits", "fmt_tokens"),
}


def _arrays(scores: Sequence[UtteranceScore]) -> dict[str, np.ndarray]:
    names = {n for pair in _RATE_FIELDS.values() for n in pair}
    return {n: np.array([getattr(s, n) for s in scores], dtype=np.float64) for n in names}


def corpus_rates(scores: Sequence[UtteranceScore]) -> dict[str, float]:
    arr = _arrays(scores)
    return {k: float(arr[e].sum() / max(arr[d].sum(), 1.0)) for k, (e, d) in _RATE_FIELDS.items()}


def bootstrap_ci(
    scores: Sequence[UtteranceScore], *, n_boot: int = 2000, seed: int = 1234, alpha: float = 0.05
) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap CI of each corpus-level rate."""
    arr = _arrays(scores)
    n = len(scores)
    idx = np.random.default_rng(seed).integers(0, n, size=(n_boot, n))
    out = {}
    for key, (e, d) in _RATE_FIELDS.items():
        rates = arr[e][idx].sum(axis=1) / np.maximum(arr[d][idx].sum(axis=1), 1.0)
        out[key] = (float(np.quantile(rates, alpha / 2)), float(np.quantile(rates, 1 - alpha / 2)))
    return out


def paired_bootstrap_delta(
    a: Sequence[UtteranceScore],
    b: Sequence[UtteranceScore],
    *,
    metric: str = "wer",
    n_boot: int = 2000,
    seed: int = 1234,
) -> dict[str, float]:
    """Paired bootstrap of rate(b) - rate(a) over the same utterances.

    Returns the point estimate, its 95% CI and the fraction of resamples in
    which b was worse than a (a one-sided bootstrap 'p-value').
    """
    if len(a) != len(b):
        raise ValueError("paired comparison needs the same utterances in both systems")
    e, d = _RATE_FIELDS[metric]
    ea, da = _arrays(a)[e], _arrays(a)[d]
    eb, db = _arrays(b)[e], _arrays(b)[d]
    n = len(a)
    idx = np.random.default_rng(seed).integers(0, n, size=(n_boot, n))
    ra = ea[idx].sum(1) / np.maximum(da[idx].sum(1), 1.0)
    rb = eb[idx].sum(1) / np.maximum(db[idx].sum(1), 1.0)
    delta = rb - ra
    point = float(eb.sum() / max(db.sum(), 1.0) - ea.sum() / max(da.sum(), 1.0))
    return {
        "delta": point,
        "ci_low": float(np.quantile(delta, 0.025)),
        "ci_high": float(np.quantile(delta, 0.975)),
        "p_b_worse": float((delta > 0).mean()),
    }


def latency_summary(values_ms: Sequence[float]) -> dict[str, float]:
    """Distribution summary; never just the mean."""
    v = np.asarray(values_ms, dtype=np.float64)
    if v.size == 0:
        return {"n": 0}
    return {
        "n": int(v.size),
        "mean": float(v.mean()),
        "sd": float(v.std(ddof=1)) if v.size > 1 else 0.0,
        "min": float(v.min()),
        "p50": float(np.percentile(v, 50)),
        "p90": float(np.percentile(v, 90)),
        "p95": float(np.percentile(v, 95)),
        "p99": float(np.percentile(v, 99)),
        "max": float(v.max()),
    }
