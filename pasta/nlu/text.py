"""Text normalisation for bilingual (Greek/English) command understanding."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_PUNCT = re.compile(r"[^\w\s./:+#@%-]", re.UNICODE)
_WS = re.compile(r"\s+")

# Greek letters -> Latin, for matching spoken app names ("κρόουμ" ~ "chrome",
# "ντισκορντ" ~ "discord"). Digraphs first.
_GREEKLISH_DI = [("ου", "ou"), ("μπ", "b"), ("ντ", "d"), ("γκ", "g"), ("γγ", "g"), ("τσ", "ts"), ("τζ", "tz"),
                 ("αι", "e"), ("ει", "i"), ("οι", "i"), ("αυ", "av"), ("ευ", "ev")]
_GREEKLISH = str.maketrans({
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i", "κ": "k",
    "λ": "l", "μ": "m", "ν": "n", "ξ": "ks", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t",
    "υ": "i", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
})


def strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", "".join(c for c in nfd if unicodedata.category(c) != "Mn"))


def norm(text: str) -> str:
    """Lowercase, accent-free, punctuation-light form used by the grammar."""
    t = strip_accents(unicodedata.normalize("NFC", text).lower()).replace("ς", "σ")
    t = t.replace("’", "'").replace("`", "'")
    t = _PUNCT.sub(" ", t)
    t = re.sub(r"(?<!\w)[.:/-]+|[.:/-]+(?!\w)", " ", t)  # keep dots/colons only inside tokens (urls, 10:30)
    return _WS.sub(" ", t).strip()


def greeklish(text: str) -> str:
    t = strip_accents(text.lower())
    for gr, lat in _GREEKLISH_DI:
        t = t.replace(gr, lat)
    return t.translate(_GREEKLISH)


def phonetic_key(text: str) -> str:
    """Rough sound-alike key: Latin-transliterate, collapse doubles and vowels
    that ASR and transliteration confuse (e/i/y, o/u), drop separators."""
    t = greeklish(text)
    t = re.sub(r"[^a-z0-9]", "", t)
    t = t.replace("ph", "f").replace("ck", "k").replace("c", "k").replace("q", "k").replace("w", "v")
    t = t.replace("x", "ks").replace("ou", "u").replace("oo", "u").replace("ee", "i")
    t = re.sub(r"[eiy]", "i", t)
    t = re.sub(r"[ou]", "o", t)
    t = re.sub(r"h", "", t)
    return re.sub(r"(.)\1+", r"\1", t)


def similarity(a: str, b: str) -> float:
    """0..1 similarity robust to Greek/English spelling of the same name."""
    if not a or not b:
        return 0.0
    na, nb = norm(a), norm(b)
    if na == nb:
        return 1.0
    pa, pb = phonetic_key(a), phonetic_key(b)
    if pa and pa == pb:
        return 0.93
    r1 = SequenceMatcher(None, na, nb).ratio()
    r2 = SequenceMatcher(None, pa, pb).ratio() if pa and pb else 0.0
    return max(r1, r2 * 0.95)


_SPOKEN_URL = [
    (r"\s+(?:dot|τελεια|τελεία|ντοτ)\s+", "."),
    (r"\s+(?:slash|καθετοσ|κάθετος)\s+", "/"),
]
TLDS = ("com", "org", "net", "gr", "io", "dev", "ai", "edu", "eu", "co", "uk", "de", "app", "tv", "me", "info")
_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:" + "|".join(TLDS) + r"))(/[^\s]*)?\b")


def spoken_urls(text: str) -> str:
    t = text
    for pat, rep in _SPOKEN_URL:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    return t


def find_domain(text: str) -> str | None:
    m = _DOMAIN.search(spoken_urls(text.lower()))
    return m.group(0) if m else None
