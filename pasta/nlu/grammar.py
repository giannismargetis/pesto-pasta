"""Deterministic bilingual (Greek/English) command grammar.

Design: an utterance is split into clauses at conjunctions *only when the next
words start a new command* ("open Chrome and search for cats" -> 2 clauses,
but "search for salt and pepper" stays one). Each clause is matched against an
ordered list of rules on its normalised form (lowercase, accent-free); the
free-text payload (search query, text to type, target name) is sliced from
the *original* words so case and accents survive.

The grammar never guesses: if no rule matches, the parse is empty and the
caller may fall back to the (confirmation-gated) LLM parser.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..intents import Intent
from ..world.sites import BROWSERS, SEARCHABLE, SITES
from .text import find_domain, norm, spoken_urls

# --------------------------------------------------------------------------- lexicon
ART = r"(?:the|a|an|my|this|that|το|τη|την|τον|τα|τισ|τουσ|ο|η|οι|ενα|μια|μου|σου|αυτο|αυτη|αυτην)"
PREP_IN = r"(?:in|on|at|into|σε|στο|στη|στην|στον|στα|στισ|στουσ|μεσα σε|μεσα στο|μεσα στη|μεσα στην)"
FILLERS_START = re.compile(
    r"^(?:(?:please|pls|hey|ok|okay|so|now|just|can you|could you|would you|will you|i want to|i'd like to|"
    r"i would like to|i need to|let's|lets|go ahead and|παρακαλω|σε παρακαλω|ρε|λοιπον|τωρα|απλα|μπορεισ να|"
    r"θελω να|θα ηθελα να|θελω|πρεπει να|για|ελα|αντε|γρηγορα)\s+)+"
)
FILLERS_END = re.compile(r"(?:\s+(?:please|pls|for me|now|thanks|thank you|παρακαλω|σε παρακαλω|ευχαριστω|"
                         r"για μενα|τωρα|γρηγορα|λιγο))+$")

V_OPEN = r"(?:open|launch|start|run|load|fire up|bring up|ανοιξε|ανοιξτε|ανοιγε|ανοιξω|ανοιξεισ|ξεκινα|ξεκινησε|" \
         r"ξεκινησω|τρεξε|εκκινησε|φορτωσε|ανοιγμα)"
V_CLOSE = r"(?:close|quit|exit|shut|shut down|terminate|κλεισε|κλειστε|κλεισω|κλεισιμο|τερματισε|βγεσ απο)"
V_FOCUS = r"(?:switch back to|switch to|switch over to|go back to|go to|go over to|return to|focus(?: on)?|" \
          r"show me|jump back to|jump to|take me to|" \
          r"πηγαινε|παω|παμε|μπεσ|αλλαξε|εστιασε|δειξε μου|δειξε|φερε μου|φερε|γυρνα)"
V_MIN = r"(?:minimi[sz]e|hide|ελαχιστοποιησε|κατεβασε|κρυψε)"
V_MAX = r"(?:maximi[sz]e|make (?:this |the |it )?(?:window )?(?:full ?screen|bigger|maximi[sz]ed)|" \
        r"make full ?screen|full ?screen|μεγιστοποιησε|μεγαλωσε|πληρησ οθονη)"
V_RESTORE = r"(?:restore|unminimi[sz]e|επαναφερε|επαναφορα)"
V_SEARCH = r"(?:search(?: the web| online| google| the internet)?(?: for)?|google|look up|look for|find online|" \
           r"ψαξε(?: στο (?:google|ιντερνετ|internet|διαδικτυο))?(?: για)?|ψαξω(?: για)?|αναζητησε(?: για)?|" \
           r"γκουγκλαρε|βρεσ στο (?:google|ιντερνετ|internet|διαδικτυο))"
V_TYPE = r"(?:type|write|dictate|enter the text|γραψε|πληκτρολογησε|γραψω)"
V_PRESS = r"(?:press|hit|push|πατα|πατησε|παταω|πατησω)"
V_CLICK = r"(?:click(?: on)?|tap(?: on)?|select|κανε κλικ(?: σε| στο| στη| στην)?|κλικ(?: σε| στο| στη| στην)?|" \
          r"πατα(?: σε| στο| στη| στην)|επελεξε)"
V_RUN = r"(?:run|execute|τρεξε|εκτελεσε)"
V_FIND_FILE = r"(?:find|locate|search for|look for|open|βρεσ|ψαξε(?: για)?|ανοιξε|εντοπισε)"
FILE_WORD = r"(?:file|document|pdf|αρχειο|εγγραφο|αρχειο pdf)"

# verbs that may start a new clause after "and"/"και"
CLAUSE_START = re.compile(
    rf"^(?:{V_OPEN}|{V_CLOSE}|{V_FOCUS}|{V_MIN}|{V_MAX}|{V_RESTORE}|{V_SEARCH}|{V_TYPE}|{V_PRESS}|{V_CLICK}|"
    r"scroll|σκρολαρε|κυλησε|mute|unmute|σιγαση|play|pause|παιξε|βαλε|new tab|νεα καρτελα|καινουρια καρτελα|"
    r"copy|paste|cut|undo|save|select all|αντεγραψε|αντιγραψε|επικολλησε|κοψε|αναιρεσε|αποθηκευσε|σωσε|"
    r"go back|πισω|γυρνα πισω|reload|refresh|ανανεωσε|turn|δυναμωσε|χαμηλωσε|μπεσ|visit|navigate)\b"
)
CONJ = re.compile(r"\s+(?:and then|and also|and|then|after that|afterwards|και μετα|και επειτα|και μετα να|"
                  r"μετα|επειτα|και|κι)\s+")

KEY_NAMES = {
    "enter": "enter", "return": "enter", "εντερ": "enter", "ενταρ": "enter",
    "escape": "esc", "esc": "esc", "εσκειπ": "esc", "tab": "tab", "ταμπ": "tab", "space": "space", "spacebar": "space",
    "κενο": "space", "backspace": "backspace", "delete": "delete", "del": "delete", "διαγραφη": "delete",
    "up": "up", "down": "down", "left": "left", "right": "right", "πανω": "up", "κατω": "down",
    "αριστερα": "left", "δεξια": "right", "home": "home", "end": "end", "page up": "pageup", "page down": "pagedown",
    "control": "ctrl", "ctrl": "ctrl", "κοντρολ": "ctrl", "shift": "shift", "σιφτ": "shift", "alt": "alt",
    "αλτ": "alt", "windows": "win", "win": "win", "γουιντοουζ": "win",
}
KEY_NAMES.update({f"f{i}": f"f{i}" for i in range(1, 13)})
KEY_NAMES.update({c: c for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
GREEK_LETTER_KEYS = {"σ": "s", "α": "a", "ζ": "z", "χ": "x", "β": "b", "ν": "n", "τ": "t", "ε": "e", "ο": "o"}

FOLDERS = {
    "downloads": "downloads", "download": "downloads", "ληψεισ": "downloads", "ληψη": "downloads",
    "documents": "documents", "εγγραφα": "documents", "desktop": "desktop", "επιφανεια εργασιασ": "desktop",
    "pictures": "pictures", "photos": "pictures", "εικονεσ": "pictures", "φωτογραφιεσ": "pictures",
    "music": "music", "μουσικη": "music", "videos": "videos", "βιντεο": "videos", "home": "home",
    "home folder": "home", "user folder": "home", "προσωπικοσ φακελοσ": "home",
}
FOLDER_RE = "|".join(sorted((re.escape(k) for k in FOLDERS), key=len, reverse=True))

SHELL_PROGRAMS = ("git", "python", "py", "pip", "ipconfig", "hostname", "whoami", "nvidia-smi", "dir", "ver",
                  "systeminfo", "tasklist", "node", "npm")


@dataclass
class Clause:
    words: list[str]  # original tokens
    norms: list[str]  # normalised tokens (aligned 1:1)
    breaks: frozenset[int] = frozenset()  # token indices followed by , or ;

    @property
    def text(self) -> str:
        return " ".join(self.norms)

    @property
    def original(self) -> str:
        return " ".join(self.words)

    def tail(self, norm_offset: int) -> str:
        """Original words from the token at character offset ``norm_offset``."""
        idx = self.text[:norm_offset].count(" ")
        return " ".join(self.words[idx:]).strip(" ,.;:!?·;\"'«»")

    def slice(self, start: int, end: int) -> str:
        a = self.text[:start].count(" ")
        b = self.text[:end].count(" ") + 1
        return " ".join(self.words[a:b]).strip(" ,.;:!?·;\"'«»")


def tokenize(text: str) -> Clause:
    words, norms, breaks = [], [], set()
    for w in text.split():
        n = norm(w)
        if n:
            for part in n.split(" "):  # norm may split "e.g.," style tokens
                words.append(w if " " not in n else part)
                norms.append(part)
            if w.endswith((",", ";", "·")):
                breaks.add(len(norms) - 1)
    return Clause(words, norms, frozenset(breaks))


def split_clauses(text: str) -> list[Clause]:
    whole = tokenize(text)
    if not whole.norms:
        return []
    joined = whole.text
    cuts: list[tuple[int, int]] = []  # (end of left clause, start of right clause) as token indices
    for m in CONJ.finditer(joined):
        if CLAUSE_START.match(_strip_fillers(joined[m.end():])):
            cuts.append((joined[: m.start()].count(" ") + 1 if m.start() else 0, joined[: m.end()].count(" ")))
    for i in sorted(whole.breaks):
        right = " ".join(whole.norms[i + 1 :])
        if right and CLAUSE_START.match(_strip_fillers(right)):
            cuts.append((i + 1, i + 1))
    clauses: list[Clause] = []
    start = 0
    for a, b in sorted(cuts):
        if a > start:
            clauses.append(Clause(whole.words[start:a], whole.norms[start:a]))
        start = max(start, b)
    clauses.append(Clause(whole.words[start:], whole.norms[start:]))
    return [c for c in clauses if c.norms]


def _strip_fillers(s: str) -> str:
    s = FILLERS_START.sub("", s)
    return FILLERS_END.sub("", s).strip()


_KANE = re.compile(r"^(?:κανε|κανω|καντο|κανε ενα|κανε μου)\s+(?=(?:focus|save|copy|paste|cut|search|scroll|refresh|"
                   r"reload|close|open|minimi[sz]e|maximi[sz]e|mute|unmute|undo|redo|play|pause|select all|google|"
                   r"click|restart)\b)")


def _clean_clause(c: Clause) -> Clause:
    m = _KANE.match(c.text)
    if m:
        k = c.text[: m.end()].count(" ")
        c = Clause(c.words[k:], c.norms[k:])
    s = c.text
    m = FILLERS_START.match(s)
    if m:
        k = s[: m.end()].count(" ")
        c = Clause(c.words[k:], c.norms[k:])
    s = c.text
    m = FILLERS_END.search(s)
    if m and m.start() > 0:
        k = s[: m.start()].count(" ") + 1
        c = Clause(c.words[:k], c.norms[:k])
    return c


def _target(raw: str) -> str:
    """Strip articles/prepositions/'app'/'window' words around a target name."""
    t = raw.strip(" ,.;:!?·\"'«»")
    t = re.sub(rf"^(?:(?:{ART}|{PREP_IN})\s+)+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+(?:app|application|program|window|browser|εφαρμογη|προγραμμα|παραθυρο)$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(?:the |το |την |τη )?(?:app|application|program|window|button|link|εφαρμογη|προγραμμα|"
               r"παραθυρο|κουμπι|κουμπί|συνδεσμο|σύνδεσμο)\s+", "", t, flags=re.IGNORECASE)
    return t.strip()


def parse_keys(spec: str) -> str | None:
    """'control shift t' / 'ctrl+s' / 'alt f4' / 'enter' -> 'ctrl+shift+t'."""
    s = norm(spec).replace("+", " ").replace(" plus ", " ")
    s = re.sub(r"\b(?:key|button|πληκτρο|κουμπι|the|το)\b", " ", s)
    s = re.sub(r"\bpage (up|down)\b", r"page\1", s)
    out = []
    for tok in s.split():
        if tok in ("pageup", "pagedown"):
            out.append(tok)
        elif tok in KEY_NAMES:
            out.append(KEY_NAMES[tok])
        elif tok in GREEK_LETTER_KEYS:
            out.append(GREEK_LETTER_KEYS[tok])
        else:
            return None
    if not out:
        return None
    mods = [k for k in out if k in ("ctrl", "shift", "alt", "win")]
    rest = [k for k in out if k not in ("ctrl", "shift", "alt", "win")]
    if len(rest) > 1 and mods:
        return None
    if not rest and len(mods) == 1:
        return mods[0]
    return "+".join(dict.fromkeys(mods + rest))


# --------------------------------------------------------------------------- rules
Rule = tuple[re.Pattern, Callable[[re.Match, Clause], Intent | None]]
RULES: list[Rule] = []


def rule(pattern: str):
    def deco(fn):
        RULES.append((re.compile(pattern), fn))
        return fn
    return deco


I = Intent  # noqa: E741


UNSUPPORTED = "unsupported"


@rule(r"^(?:shut ?down|restart|reboot|turn off|power off|log ?off|sign out|hibernate|put)(?: (?:the|my))?"
      r"(?: computer| pc| laptop| system| machine)?(?: to sleep)?$|^(?:κλεισε|σβησε|επανεκκινησε|κανε επανεκκινηση)"
      r"(?: (?:τον|το))? (?:υπολογιστη|pc|λαπτοπ|συστημα)$|^(?:delete|remove|erase|wipe|format|σβησε|διεγραψε|"
      r"διαγραψε)\b.*")
def _unsupported(m, c):
    """Power and deletion requests are deliberately outside PASTA's action space;
    they must yield "not understood", never a near-miss such as close(...)."""
    return UNSUPPORTED


@rule(r"^(?:stop|cancel|abort|never ?mind|forget it|σταματα|σταματησε|ακυρο|ακυρωσε|ακυρωση|στοπ|αστο|ασ το|"
      r"αφησε το|ξεχνα το)$")
def _stop(m, c):
    return I("stop")


@rule(r"^(?:what(?:s| is)? (?:currently )?open|what windows are open|which windows are open|list (?:all )?(?:the )?"
      r"(?:open )?windows|τι (?:ειναι|εχω|εχει) ανοιχτο|ποια παραθυρα (?:ειναι|εχω) ανοιχτα|δειξε (?:μου )?τα "
      r"(?:ανοιχτα )?παραθυρα)$")
def _list(m, c):
    return I("list_windows")


@rule(r"^(?:show (?:the |me the )?desktop|go to (?:the )?desktop|minimi[sz]e (?:all|everything)(?: windows)?|"
      r"hide (?:everything|all(?: windows)?)(?: and show (?:me )?the desktop)?|"
      r"(?:δειξε(?: μου)?|πηγαινε σ?την?) (?:την )?επιφανεια εργασιασ|ελαχιστοποιησε (?:τα )?ολα|κρυψε (?:τα )?ολα)$")
def _desktop(m, c):
    return I("show_desktop")


@rule(r"^(?:open |create |make )?(?:a )?new (?:browser )?tab$|^(?:ανοιξε )?(?:μια )?(?:νεα|καινουρια|καινουργια) καρτελα$")
def _new_tab(m, c):
    return I("browser", {"op": "new_tab"})


@rule(r"^(?:close|κλεισε) (?:this |the |current |αυτη την |αυτην |την |τη )?(?:tab|καρτελα)$")
def _close_tab(m, c):
    return I("browser", {"op": "close_tab"})


@rule(r"^(?:(?:go to |switch to )?(?:the )?(next|previous|prev) tab|(?:πηγαινε στην )?(επομενη|προηγουμενη) καρτελα)$")
def _tab_nav(m, c):
    word = m.group(1) or m.group(2)
    return I("browser", {"op": "next_tab" if word in ("next", "επομενη") else "prev_tab"})


@rule(r"^(?:go back|back|navigate back|previous page|go to the previous page|(?:πηγαινε |γυρνα |παμε |παω )?πισω"
      r"(?: μια σελιδα)?|προηγουμενη σελιδα)$")
def _back(m, c):
    return I("browser", {"op": "back"})


@rule(r"^(?:go forward|forward|next page|(?:πηγαινε |παμε )?μπροστα|επομενη σελιδα)$")
def _forward(m, c):
    return I("browser", {"op": "forward"})


@rule(r"^(?:reload|refresh)(?: (?:the|this))?(?: page)?$|^(?:ανανεωσε|ανανεωση|ξαναφορτωσε)(?: (?:τη|την))?(?: σελιδα)?$")
def _reload(m, c):
    return I("browser", {"op": "reload"})


@rule(r"^(?:mute|silence)(?: (?:the |my )?(?:sound|audio|volume|computer|pc|speakers))?$|^(?:σιγαση|βουβο|μουγκα|"
      r"κλεισε (?:τον |το )?(?:ηχο|ηχοσ))(?: του υπολογιστη)?$")
def _mute(m, c):
    return I("volume", {"op": "mute"})


@rule(r"^(?:unmute|turn (?:the )?sound (?:back )?on)(?: (?:the )?(?:sound|audio|volume|computer))?$|^(?:ανοιξε "
      r"(?:τον |το )?ηχο|επαναφορα ηχου)$")
def _unmute(m, c):
    return I("volume", {"op": "unmute"})


@rule(r"^(?:(?:set|put|change) (?:the )?volume (?:to|at) |volume (?:to |at )?|(?:βαλε|ρυθμισε) (?:την |τον )?"
      r"(?:ενταση|ηχο) (?:στο |στα |σε )|ενταση (?:στο |σε ))(\d{1,3})(?: ?%| percent| τοισ εκατο)?$")
def _volume_set(m, c):
    return I("volume", {"op": "set", "level": max(0, min(100, int(m.group(1))))})


@rule(r"^(?:volume up|turn (?:it|the volume|the sound) up|louder|increase (?:the )?volume|δυναμωσε(?: (?:τον |την )?"
      r"(?:ηχο|ενταση))?|ανεβασε (?:τον |την )?(?:ηχο|ενταση)|πιο δυνατα)$")
def _vol_up(m, c):
    return I("volume", {"op": "up"})


@rule(r"^(?:volume down|turn (?:it|the volume|the sound) down|quieter|lower (?:the )?volume|decrease (?:the )?volume|"
      r"χαμηλωσε(?: (?:τον |την )?(?:ηχο|ενταση))?|κατεβασε (?:τον |την )?(?:ηχο|ενταση)|πιο σιγα)$")
def _vol_down(m, c):
    return I("volume", {"op": "down"})


@rule(r"^(?:next (?:song|track)|skip(?: (?:this )?(?:song|track))?|(?:επομενο|αλλο) (?:τραγουδι|κομματι))$")
def _next_track(m, c):
    return I("media", {"op": "next"})


@rule(r"^(?:previous (?:song|track)|last (?:song|track)|(?:προηγουμενο) (?:τραγουδι|κομματι))$")
def _prev_track(m, c):
    return I("media", {"op": "previous"})


@rule(r"^(?:play|pause|resume|stop the music|pause (?:the )?(?:music|song|video)|play (?:the )?(?:music|song|video)|"
      r"resume (?:the )?(?:music|song|video)|παυση|συνεχισε|σταματα (?:τη |την )?μουσικη|παιξε (?:τη |την )?μουσικη|"
      r"βαλε (?:τη |την )?μουσικη)$")
def _play_pause(m, c):
    return I("media", {"op": "play_pause"})


# YouTube before generic search/open
@rule(r"^(?:(?:play|search|find|look up|look for|put on|watch|show me)\s+(?P<a>.+?)\s+(?:on|in) youtube"
      r"|(?:search |open )?youtube (?:and )?(?:search |play |find )?(?:for )?(?P<b>.+)"
      r"|(?:παιξε|βαλε|ψαξε|βρεσ|δειξε)(?: μου)?(?: στο)? youtube(?: για)? (?P<c>.+)"
      r"|(?:παιξε|βαλε|ψαξε|βρεσ|δειξε)(?: μου)? (?P<d>.+?) στο youtube)$")
def _youtube(m, c):
    key = next(k for k in "abcd" if m.group(k))
    query = c.slice(m.start(key), m.end(key))
    query = re.sub(r"^(?:for|για)\s+", "", query, flags=re.IGNORECASE)
    return I("web_search", {"query": query, "site": "youtube"}) if query else None


@rule(r"^(?:play|παιξε|βαλε)(?: μου)? (?P<q>.+)$")
def _play_something(m, c):
    q = c.slice(m.start("q"), m.end("q"))
    if norm(q) in ("music", "μουσικη", "τη μουσικη", "την μουσικη"):
        return I("media", {"op": "play_pause"})
    return I("web_search", {"query": q, "site": "youtube"}, confidence=0.85)


@rule(r"^(?:search|look up|ψαξε|αναζητησε)\s+(?:(?:on|in|στο|στη|στην)\s+)?(?P<site>wikipedia|βικιπαιδεια|google|"
      r"youtube|maps|google maps)\s+(?:for|για)\s+(?P<q>.+)$")
def _search_site_first(m, c):
    site = {"wikipedia": "wikipedia", "βικιπαιδεια": "wikipedia", "youtube": "youtube", "maps": "maps",
            "google maps": "maps"}.get(m.group("site"), "web")
    return I("web_search", {"query": c.slice(m.start("q"), m.end("q")), "site": site})


@rule(rf"^{V_SEARCH}\s+(?P<q>.+?)(?:\s+(?:on|in|στο|στη|στην)\s+(?P<site>google|bing|the web|wikipedia|"
      r"βικιπαιδεια|google maps|maps|χαρτη|χαρτεσ|ιντερνετ|internet))?$")
def _search(m, c):
    query = c.slice(m.start("q"), m.end("q"))
    query = re.sub(r"^(?:for|για)\s+", "", query, flags=re.IGNORECASE)
    site_word = m.group("site") or ""
    site = ("wikipedia" if site_word in ("wikipedia", "βικιπαιδεια") else
            "maps" if site_word in ("google maps", "maps", "χαρτη", "χαρτεσ") else "web")
    return I("web_search", {"query": query, "site": site}) if query else None


@rule(r"^(?:(?:where is|show me|find|locate|δειξε(?: μου)?|βρεσ(?: μου)?|που ειναι)\s+(?P<q>.+?) (?:on (?:the )?map|"
      r"in maps|στο χαρτη|στον χαρτη)|(?:(?:show me |get |give me |find )?directions to|navigate to|"
      r"οδηγιεσ για|πωσ θα παω σ(?:το|τη|την)) (?P<r>.+))$")
def _maps(m, c):
    k = "q" if m.group("q") else "r"
    return I("web_search", {"query": c.slice(m.start(k), m.end(k)), "site": "maps"})


@rule(rf"^(?:{V_OPEN}|{V_FOCUS}|visit|navigate to|browse to|μπεσ|επισκεψου)?\s*(?:(?:{ART}|{PREP_IN}|to|σ)\s+)*"
      r"(?:site |website |page |ιστοσελιδα |σελιδα |σαιτ )?(?P<url>\S+\.(?:com|org|net|gr|io|dev|ai|edu|eu|co|uk|de|"
      r"app|tv|me|info)(?:/\S*)?)$")
def _url(m, c):
    domain = find_domain(c.original) or m.group("url")
    return I("open_url", {"url": domain})


@rule(rf"^{V_TYPE}\s+(?:(?:that|the text|the words|this|το κειμενο|οτι|το)\s+)?(?P<t>.+)$")
def _type(m, c):
    text = re.sub(r"^(?:μου|me|for me)\s+", "", c.tail(m.start("t")), flags=re.IGNORECASE)
    return I("type_text", {"text": text}) if text else None


@rule(r"^(?:copy|copy (?:that|this|it|the selection|selection)|αντιγραφη|αντεγραψε|αντιγραψε)(?: (?:το|αυτο|τα))?$")
def _copy(m, c):
    return I("edit", {"op": "copy"})


@rule(r"^(?:paste|paste (?:it|that|this)(?: here)?|paste here|επικολληση|επικολλησε|κανε επικολληση|κανε paste)(?: (?:το|εδω))?$")
def _paste(m, c):
    return I("edit", {"op": "paste"})


@rule(r"^(?:cut|cut (?:that|this|it)|αποκοπη|κοψε(?: το)?)$")
def _cut(m, c):
    return I("edit", {"op": "cut"})


@rule(r"^(?:undo|undo (?:that|it)|αναιρεση|αναιρεσε(?: το)?)$")
def _undo(m, c):
    return I("edit", {"op": "undo"})


@rule(r"^(?:redo|ξανακανε το|επαναληψη)$")
def _redo(m, c):
    return I("edit", {"op": "redo"})


@rule(r"^(?:select all|select everything|επιλογη ολων|επελεξε (?:τα )?ολα|μαρκαρε (?:τα )?ολα)$")
def _select_all(m, c):
    return I("edit", {"op": "select_all"})


@rule(r"^(?:save|save (?:it|this|that|the file|the document|my work)|αποθηκευση|αποθηκευσε(?: (?:το|το αρχειο))?|"
      r"σωσε(?: το)?)$")
def _save(m, c):
    return I("edit", {"op": "save"})


@rule(r"^(?:save|αποθηκευσε|σωσε)\s+(?:(?:the|το|τη|την)\s+)?(?P<t>.+)$")
def _save_in(m, c):
    t = _target(c.tail(m.start("t")))
    return [I("focus", {"target": t}), I("edit", {"op": "save"})] if t else None


@rule(r"^(?:scroll|σκρολαρε|κυλησε|κυλα)(?: (?P<d>up|down|πανω|κατω))?(?: (?P<amt>a lot|a bit|a little|πολυ|λιγο))?$"
      r"|^(?P<pg>page (?:up|down))$|^(?P<el>κατεβα|ανεβα)(?: (?:λιγο|πολυ))?$")
def _scroll(m, c):
    d = m.group("d") or ""
    if m.group("pg"):
        return I("scroll", {"direction": "up" if "up" in m.group("pg") else "down", "amount": "page"})
    if m.group("el"):
        d = "down" if m.group("el") == "κατεβα" else "up"
    direction = "up" if d in ("up", "πανω") else "down"
    amt = m.group("amt") or ""
    amount = "large" if amt in ("a lot", "πολυ") else "small" if amt else "page"
    return I("scroll", {"direction": direction, "amount": amount})


@rule(rf"^{V_PRESS}\s+(?P<k>.+?)(?:\s+(?:key|button|πληκτρο|κουμπι))?$")
def _press(m, c):
    keys = parse_keys(m.group("k"))
    if keys:
        return I("press", {"keys": keys})
    label = _target(c.slice(m.start("k"), m.end("k")))  # "press the Save button" -> click
    return I("click", {"label": label}, confidence=0.9) if label else None


@rule(rf"^{V_RUN}\s+(?:(?:the )?command\s+|(?:την )?εντολη\s+)?(?P<cmd>(?:{'|'.join(map(re.escape, SHELL_PROGRAMS))})"
      r"(?:\s.*)?)$")
def _run_cmd(m, c):
    cmd = c.slice(m.start("cmd"), m.end("cmd"))
    cmd = re.sub(r"\s+(?:in (?:the )?(?:terminal|console)|στο τερματικο)$", "", cmd, flags=re.IGNORECASE)
    return I("run_command", {"command": cmd})


@rule(rf"^{V_RUN}\s+(?:(?:the )?command\s+|(?:την )?εντολη\s+)(?P<cmd>.+)$|^{V_RUN}\s+(?P<cmd2>\S+\s+.*(?:\s|^)[-/]\S*.*)$")
def _run_other(m, c):
    """Anything that looks like a shell command goes to run_command, where the
    allowlist decides — it must never fall through to "open app"."""
    k = "cmd" if m.group("cmd") else "cmd2"
    return I("run_command", {"command": c.slice(m.start(k), m.end(k))})


@rule(rf"^{V_FIND_FILE}\s+(?:{ART}\s+)*{FILE_WORD}\s+(?:(?:called|named|με ονομα|που λεγεται)\s+)?(?P<q>.+)$"
      rf"|^(?:find|locate|βρεσ)\s+(?:{ART}\s+)*(?P<q2>\S+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|zip|png|jpe?g|mp3|mp4))$")
def _find_file(m, c):
    k = "q" if m.group("q") else "q2"
    q = _target(c.slice(m.start(k), m.end(k)))
    q = re.sub(r"\s+(?:μου|my)$", "", q, flags=re.IGNORECASE)
    return I("find_file", {"query": q}) if q else None


@rule(rf"^(?:{V_OPEN}|{V_FOCUS})\s+(?:(?:{ART}|{PREP_IN})\s+)*(?:folder\s+|φακελο\s+)?(?P<f>{FOLDER_RE})"
      r"(?: folder| directory| φακελο)?$")
def _folder(m, c):
    return I("open_folder", {"folder": FOLDERS[m.group("f")]})


@rule(rf"^{V_MIN}(?:\s+(?P<t>.+))?$")
def _minimize(m, c):
    t = _target(c.tail(m.start("t"))) if m.group("t") else ""
    return I("minimize", {"target": t} if t and t not in ("it", "this", "το", "αυτο") else {})


@rule(rf"^{V_MAX}(?:\s+(?P<t>.+))?$")
def _maximize(m, c):
    t = _target(c.tail(m.start("t"))) if m.group("t") else ""
    return I("maximize", {"target": t} if t and t not in ("it", "this", "το", "αυτο") else {})


@rule(rf"^{V_RESTORE}(?:\s+(?P<t>.+))?$")
def _restore(m, c):
    t = _target(c.tail(m.start("t"))) if m.group("t") else ""
    return I("restore", {"target": t} if t else {})


@rule(rf"^{V_CLOSE}(?:\s+(?P<t>.+))?$")
def _close(m, c):
    t = _target(c.tail(m.start("t"))) if m.group("t") else ""
    if t in ("it", "this", "that", "this window", "το", "αυτο", "αυτο το παραθυρο", "παραθυρο", "window"):
        t = ""
    return I("close", {"target": t} if t else {})


@rule(rf"^{V_CLICK}\s+(?P<l>.+?)(?:\s+(?:button|link|tab|menu|κουμπι|συνδεσμο|συνδεσμοσ|μενου))?$")
def _click(m, c):
    label = _target(c.slice(m.start("l"), m.end("l")))
    return I("click", {"label": label}) if label else None


@rule(rf"^{V_FOCUS}\s+(?:(?:to|back to|over to|σε|στο|στη|στην|στον|πισω στο|πισω στη|πισω στην)\s+)?(?P<t>.+)$")
def _focus(m, c):
    t = _target(c.tail(m.start("t")))
    return I("focus", {"target": t}) if t else None


_IN_BROWSER = re.compile(r"\s+(?:in|with|on|στο|στον|με το|με τον)\s+(" + "|".join(
    sorted((re.escape(b) for b in BROWSERS if b), key=len, reverse=True)) + r")$")


_SHELLISH = re.compile(r"[/\\|&<>]|(?:^|\s)-{1,2}\w")


@rule(rf"^{V_OPEN}(?:\s+up)?\s+(?P<t>.+)$")
def _open(m, c):
    if c.norms[0] in ("run", "execute", "τρεξε", "εκτελεσε") and _SHELLISH.search(c.tail(m.start("t"))):
        return I("run_command", {"command": c.tail(m.start("t"))})  # the allowlist decides
    rest = c.text[m.start("t"):]
    b = _IN_BROWSER.search(rest)
    if b and b.start() > 0:
        t = _target(c.slice(m.start("t"), m.start("t") + b.start()))
        return I("open", {"target": t, "browser": BROWSERS[b.group(1)]}) if t else None
    t = _target(c.tail(m.start("t")))
    return I("open", {"target": t}) if t else None


# --------------------------------------------------------------------------- entry
def parse(text: str) -> list[Intent]:
    """Parse an utterance into intents. Empty list = not understood."""
    intents: list[Intent] = []
    for clause in split_clauses(spoken_urls(text)):
        clause = _clean_clause(clause)
        if not clause.norms:
            continue
        parsed = parse_clause(clause)
        if not parsed:
            return []  # one clause not understood -> never run a partial plan
        for intent in parsed:
            intent.text = clause.original
            intents.append(intent)
    return merge_context(intents)


def parse_clause(clause: Clause) -> list[Intent]:
    s = clause.text
    for pattern, handler in RULES:
        m = pattern.match(s)
        if m:
            result = handler(m, clause)
            if result == UNSUPPORTED:
                return []
            if result:
                return result if isinstance(result, list) else [result]
    return []


def _site_of(intent: Intent) -> str | None:
    if intent.action in ("open", "focus"):
        t = norm(intent.args.get("target", ""))
        return t if t in SITES else None
    return None


def _browser_of(intent: Intent) -> str | None:
    """'' = generic browser, None = not a browser."""
    if intent.action in ("open", "focus"):
        t = norm(intent.args.get("target", ""))
        if t in BROWSERS:
            return BROWSERS[t]
    return None


def merge_context(intents: list[Intent]) -> list[Intent]:
    """Fold multi-clause phrasings into the step the user means:

    open Chrome + go to YouTube + search X  ->  web_search(X, site=youtube, browser=chrome)
    open YouTube + search X                 ->  web_search(X, site=youtube)
    open Chrome + github.com                ->  open_url(github.com, browser=chrome)
    """
    out: list[Intent] = []
    for it in intents:
        prev = out[-1] if out else None
        if prev is not None and prev.action == it.action and prev.args == it.args:
            continue  # "hide everything and show the desktop": Win+D twice would toggle back
        if prev is not None:
            browser = _browser_of(prev)
            site = _site_of(prev)
            if browser is not None and it.action in ("web_search", "open_url"):
                if browser:
                    it.args.setdefault("browser", browser)
                out.pop()
            elif browser is not None and _site_of(it):
                args = {"target": it.args["target"]}
                if browser:
                    args["browser"] = browser
                it = Intent("open", args, min(prev.confidence, it.confidence), it.source, it.text)
                out.pop()
            elif site in SEARCHABLE and it.action == "web_search" and it.args.get("site", "web") in ("web", "youtube"):
                if it.args.get("site", "web") == "web":
                    it.args["site"] = SEARCHABLE[site]
                if prev.args.get("browser"):
                    it.args.setdefault("browser", prev.args["browser"])
                out.pop()
        out.append(it)
    return out
