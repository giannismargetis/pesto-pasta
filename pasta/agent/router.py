import re
from dataclasses import dataclass

from .schemas import RouteType


@dataclass
class RouteDecision:
    route: RouteType
    command: str
    confidence: float
    reason: str


class CommandRouter:
    """Fast, low-latency intent router distinguishing between:

    - TEXT: normal dictation to be typed into the active window
    - AGENT: computer automation command to be executed
    - AMBIGUOUS: uncertain intent that should safely default to typing or ask clarification
    """

    PREFIXES_EN = [
        "pasta",
        "hey pasta",
        "ok pasta",
        "jarvis",
        "hey jarvis",
        "ok jarvis",
        "computer",
        "system",
    ]

    PREFIXES_EL = [
        "πάστα",
        "παστά",
        "παστα",
        "ρε πάστα",
        "τζάρβις",
        "τζαρβις",
        "ρε τζάρβις",
        "βάστα",
        "μπάστα",
        "υπολογιστή",
        "κομπιούτερ",
        "κομπιούτα",
        "σύστημα",
    ]

    IMPERATIVE_EN = [
        r"^open\s+",
        r"^launch\s+",
        r"^start\s+",
        r"^switch\s+to\s+",
        r"^focus\s+",
        r"^close\s+",
        r"^minimize\s+",
        r"^maximize\s+",
        r"^restore\s+",
        r"^search\s+(for\s+)?",
        r"^go\s+back",
        r"^go\s+forward",
        r"^reload(\s+page)?",
        r"^scroll\s+(up|down)",
        r"^new\s+tab",
        r"^close\s+tab",
        r"^click\s+",
        r"^type\s+",
        r"^press\s+",
        r"^copy(\s+this)?",
        r"^paste(\s+it)?",
        r"^run\s+",
        r"^mute(\s+my\s+computer|\s+the\s+computer|\s+sound)?",
        r"^unmute",
        r"^what\s+is\s+currently\s+open",
        r"^stop(\s+now)?",
    ]

    IMPERATIVE_EL = [
        r"^(?:θέλω\s+να\s+)?(?:άνοιξε|ανοιξε|ανοίξω|ανοιξω)\s+",
        r"^(?:θέλω\s+να\s+)?(?:τρέξε|τρεξε)\s+",
        r"^(?:θέλω\s+να\s+)?(?:πήγαινε|πηγαινε)\s+",
        r"^(?:θέλω\s+να\s+)?(?:ψάξε|ψαξε|ψάξω|ψαξω)\s+",
        r"^(?:θέλω\s+να\s+)?(?:βρες|βρω)\s+",
        r"^(?:θέλω\s+να\s+)?(?:κλείσε|κλεισε|κλείσω|κλεισω)\s+",
        r"^ελαχιστοποίησε\s+",
        r"^μεγιστοποίησε\s+",
        r"^γύρνα\s+πίσω",
        r"^γυρνα\s+πισω",
        r"^καινούρια\s+καρτέλα",
        r"^νέα\s+καρτέλα",
        r"^κλείσε\s+την\s+καρτέλα",
        r"^πάτα\s+",
        r"^πατα\s+",
        r"^γράψε\s+",
        r"^γραψε\s+",
        r"^κάνε\s+(copy|paste|αντιγραφή|επικόλληση)",
        r"^κλεισε\s+τον\s+ήχο",
        r"^μούγκα",
        r"^τι\s+είναι\s+ανοιχτό",
        r"^σταμάτα",
        r"^στοπ",
    ]

    def __init__(self) -> None:
        self.all_prefixes = sorted(self.PREFIXES_EN + self.PREFIXES_EL, key=len, reverse=True)

    def route(self, transcript: str, forced_mode: str = "auto") -> RouteDecision:
        text = transcript.strip()
        if not text:
            return RouteDecision(RouteType.TEXT, "", 1.0, "empty input")

        # Explicit mode overrides
        mode = (forced_mode or "auto").lower()
        if mode == "dictation":
            return RouteDecision(RouteType.TEXT, text, 1.0, "mode: dictation (forced text)")

        clean_lower = text.lower()

        # If in AGENT mode, strip any optional prefix if present, but ALWAYS execute as AGENT
        if mode == "agent":
            for prefix in self.all_prefixes:
                pattern = rf"^{re.escape(prefix)}[\s,:\-\.]+\s*(.*)$"
                match = re.match(pattern, clean_lower, flags=re.IGNORECASE)
                if match:
                    cmd = text[match.start(1) :].strip().rstrip(".!?,;")
                    return RouteDecision(RouteType.AGENT, cmd or text, 1.0, f"mode: agent (stripped '{prefix}')")
            return RouteDecision(RouteType.AGENT, text.rstrip(".!?,;"), 1.0, "mode: agent (direct command)")

        # AUTO MODE: Check explicit trigger prefix
        for prefix in self.all_prefixes:
            # Pattern matching: prefix followed by optional punctuation then rest
            pattern = rf"^{re.escape(prefix)}[\s,:\-\.]+\s*(.*)$"
            match = re.match(pattern, clean_lower, flags=re.IGNORECASE)
            if match:
                raw_command = text[match.start(1) :].strip().rstrip(".!?,;")
                if raw_command:
                    return RouteDecision(
                        RouteType.AGENT,
                        raw_command,
                        confidence=0.98,
                        reason=f"matched explicit prefix '{prefix}'",
                    )
                else:
                    return RouteDecision(
                        RouteType.AMBIGUOUS,
                        "",
                        confidence=0.50,
                        reason=f"prefix '{prefix}' with no command",
                    )

        # Check standalone stop command
        clean_no_punct = clean_lower.rstrip(".!?,;")
        if clean_no_punct in ("stop", "cancel", "στοπ", "σταμάτα", "ακύρωση"):
            return RouteDecision(
                RouteType.AGENT,
                "stop",
                confidence=1.0,
                reason="matched direct stop command",
            )

        # Check imperative command without prefix
        for pat in self.IMPERATIVE_EN + self.IMPERATIVE_EL:
            if re.search(pat, clean_lower, flags=re.IGNORECASE):
                # Strong imperative starting the sentence
                return RouteDecision(
                    RouteType.AGENT,
                    text.strip().rstrip(".!?,;"),
                    confidence=0.88,
                    reason="matched strong action imperative",
                )

        # Default: normal text dictation
        return RouteDecision(
            RouteType.TEXT,
            text,
            confidence=0.95,
            reason="standard dictation content",
        )
