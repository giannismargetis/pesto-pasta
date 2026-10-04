"""Dictation vs. command routing.

The old router treated any sentence *starting with an imperative* ("open…",
"γράψε…", "search…") as a command even without a wake word, so dictating
"Open the report and check the figures" executed actions instead of typing
the sentence. In an HCI system that is an unpredictable boundary; here it is
explicit:

* ``dictation`` mode — everything is typed.
* ``command``  mode — everything is a command (an optional wake word is ignored).
* ``hybrid``   mode — a command needs the wake word at the start. If the wake
  word is followed by a pause (the ASR writes "Πάστα, …") the utterance is
  addressed to PASTA even if it does not parse (you get "didn't understand",
  never typed text). Without a pause, it is a command only if it parses, so
  "Πάστα με κιμά…" (pasta with mince) is still dictated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .nlu import grammar
from .nlu.text import phonetic_key, similarity

_LEAD = re.compile(r"^\W*(?:(?:hey|ok|okay|ρε|ε|έλα|ela)\s+)?", re.IGNORECASE)
STOP_WORDS = {"stop", "cancel", "σταματα", "σταμάτα", "ακυρο", "άκυρο", "στοπ", "ακυρωση", "ακύρωση"}


@dataclass(frozen=True)
class Route:
    kind: str  # dictation | command
    command: str = ""
    wake_word: str = ""
    addressed: bool = False  # wake word + pause: definitely meant for PASTA
    reason: str = ""


class Router:
    def __init__(self, wake_words: list[str]) -> None:
        self.wake_words = wake_words
        self._keys = {phonetic_key(w): w for w in wake_words}

    def _wake(self, text: str) -> tuple[str, str, bool] | None:
        """(wake word, remainder, followed_by_pause) if the text starts with a wake word."""
        m = _LEAD.match(text)
        rest = text[m.end():] if m else text
        tok = re.match(r"([^\s,.:;!?·]+)([\s,.:;!?·]*)(.*)$", rest, re.DOTALL)
        if not tok:
            return None
        word, sep, remainder = tok.group(1), tok.group(2), tok.group(3)
        key = phonetic_key(word)
        for wk, wake in self._keys.items():
            if key == wk or (len(key) >= 4 and similarity(word, wake) >= 0.8):
                return wake, remainder.strip(), any(ch in sep for ch in ",.:;!·")
        return None

    def route(self, text: str, mode: str) -> Route:
        text = text.strip()
        if not text or mode == "dictation":
            return Route("dictation", reason=f"mode={mode}")
        wake = self._wake(text)
        if mode == "command":
            cmd = wake[1] if wake else text
            return Route("command", cmd, wake[0] if wake else "", True, "mode=command")
        if wake is None:
            return Route("dictation", reason="no wake word")
        word, remainder, pause = wake
        if not remainder:
            return Route("command" if pause else "dictation", "", word, pause, "wake word only")
        if pause:
            return Route("command", remainder, word, True, "wake word + pause")
        if grammar.parse(remainder):
            return Route("command", remainder, word, False, "wake word + parsable command")
        return Route("dictation", reason="wake-word-like start but not a command")


YES = {"yes", "yeah", "yep", "ok", "okay", "sure", "do it", "go", "go ahead", "confirm", "run it", "ναι", "νε",
       "εντάξει", "ενταξει", "οκ", "κάν' το", "καν το", "κανε το", "προχώρα", "προχωρα", "επιβεβαιώνω", "σωστά"}
NO = {"no", "nope", "cancel", "stop", "don't", "dont", "όχι", "οχι", "άκυρο", "ακυρο", "ακύρωση", "σταμάτα", "μην",
      "μη", "όχι ευχαριστώ"}


def yes_no(text: str) -> bool | None:
    t = re.sub(r"[^\w\s']", "", text.lower()).strip()
    t = re.sub(r"^(?:pasta|πάστα|παστα|jarvis)\s+", "", t)
    if t in YES or t.split()[:1] and t.split()[0] in YES and len(t.split()) <= 3:
        return True
    if t in NO or t.split()[:1] and t.split()[0] in NO and len(t.split()) <= 3:
        return False
    return None
