import json

import pytest

from pasta import settings  # noqa: F401
from pasta.eval.nlu import DATA, intent_match
from pasta.intents import Intent, validate
from pasta.nlu.grammar import parse, parse_keys, split_clauses
from pasta.router import Router, yes_no

ITEMS = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
KNOWN_DIFFERENCES = {"leg-08"}  # "Computer," is intentionally no longer a wake word
router = Router(["pasta", "jarvis", "πάστα", "τζάρβις"])


@pytest.mark.parametrize("item", ITEMS, ids=[i["id"] for i in ITEMS])
def test_corpus_regression(item):
    if item["id"] in KNOWN_DIFFERENCES:
        pytest.skip(item.get("note", "documented difference"))
    route = router.route(item["text"], "hybrid")
    assert route.kind == item["route"], route.reason
    if item["route"] != "command":
        return
    intents = parse(route.command)
    if item.get("oos"):
        assert intents == []
    else:
        exact, _ = intent_match(item["intents"], intents)
        assert exact, [(i.action, i.args) for i in intents]


def test_payload_keeps_original_case_and_accents():
    [it] = parse("γράψε Καλημέρα, Κύριε Παπαδόπουλε")
    assert it.args["text"] == "Καλημέρα, Κύριε Παπαδόπουλε"


def test_conjunction_inside_query_is_not_a_split():
    assert len(split_clauses("search for salt and pepper")) == 1
    assert len(split_clauses("open notepad and type hello")) == 2


def test_never_a_partial_plan():
    """An unknown tail must not be silently dropped (which would run only "open
    notepad"). It either stays part of the target (and then fails grounding) or
    rejects the parse."""
    intents = parse("open notepad and fly to the moon")
    assert not any(i.args.get("target", "").lower() == "notepad" for i in intents)


def test_keys():
    assert parse_keys("control shift t") == "ctrl+shift+t"
    assert parse_keys("Alt F4") == "alt+f4"
    assert parse_keys("κοντρόλ σ") == "ctrl+s"
    assert parse_keys("the moon") is None


@pytest.mark.parametrize("text,mode,kind", [
    ("Πάστα, άνοιξε το Chrome.", "hybrid", "command"),
    ("Πάστα με κιμά για βραδινό.", "hybrid", "dictation"),  # food, not a command
    ("Πάστα, τι καιρό θα κάνει;", "hybrid", "command"),  # addressed (comma) even if not understood
    ("Open the report and check the figures.", "hybrid", "dictation"),  # imperative dictation stays text
    ("Pasta, open Chrome", "dictation", "dictation"),
    ("open chrome", "command", "command"),
    ("Jarvis open notepad", "hybrid", "command"),  # no pause but parsable
    ("", "hybrid", "dictation"),
])
def test_router_modes(text, mode, kind):
    assert router.route(text, mode).kind == kind


def test_router_strips_wake_word():
    r = router.route("Hey Pasta, open Chrome.", "hybrid")
    assert r.kind == "command" and r.command.startswith("open Chrome")


@pytest.mark.parametrize("text,answer", [("Ναι.", True), ("yes please", True), ("Όχι", False), ("cancel", False),
                                         ("maybe later today", None)])
def test_yes_no(text, answer):
    assert yes_no(text) is answer


def test_intent_validation():
    assert validate(Intent("volume", {"op": "set", "level": 30})) is None
    assert validate(Intent("volume", {"op": "explode"})) is not None
    assert validate(Intent("rm_rf", {})) is not None
    assert validate(Intent("open", {})) is not None  # missing target
    assert validate(Intent("open", {"target": "x", "shell": "y"})) is not None
