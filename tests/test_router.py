import pytest

from pasta.agent.router import CommandRouter, RouteType


@pytest.fixture
def router():
    return CommandRouter()


def test_router_normal_text_english(router):
    res = router.route("The meeting is tomorrow at 10 AM.")
    assert res.route == RouteType.TEXT


def test_router_normal_text_greek(router):
    res = router.route("Καλησπέρα Γιάννη, σου στέλνω το αρχείο που ζήτησες.")
    assert res.route == RouteType.TEXT


def test_router_explicit_prefix_english(router):
    res = router.route("Pasta, open Chrome.")
    assert res.route == RouteType.AGENT
    assert res.command.lower() == "open chrome"
    assert res.confidence >= 0.90


def test_router_explicit_prefix_greek(router):
    res = router.route("Πάστα, άνοιξε το Calculator.")
    assert res.route == RouteType.AGENT
    assert "calculator" in res.command.lower() or "αριθμομηχανή" in res.command.lower()


def test_router_computer_prefix(router):
    res = router.route("Computer, switch to VS Code.")
    assert res.route == RouteType.AGENT
    assert "vs code" in res.command.lower()


def test_router_imperative_without_prefix(router):
    res = router.route("Search for RTX 5090 prices")
    assert res.route == RouteType.AGENT


def test_router_empty_input(router):
    res = router.route("   ")
    assert res.route == RouteType.TEXT


def test_router_stop_command(router):
    res = router.route("Pasta, stop.")
    assert res.route == RouteType.AGENT
    assert res.command.lower() == "stop"


def test_router_jarvis_prefix_english(router):
    res = router.route("Jarvis, open Notepad.")
    assert res.route == RouteType.AGENT
    assert res.command.lower() == "open notepad"


def test_router_jarvis_prefix_greek(router):
    res = router.route("Τζάρβις, άνοιξε το YouTube.")
    assert res.route == RouteType.AGENT
    assert "youtube" in res.command.lower()


def test_router_greek_phonetic_variants(router):
    for phrase in ("Παστά, άνοιξε το Chrome.", "Βάστα, κλείσε το notepad."):
        res = router.route(phrase)
        assert res.route == RouteType.AGENT


def test_router_forced_agent_mode(router):
    # In AGENT mode, no wake word needed!
    res = router.route("άνοιξε το notepad", forced_mode="agent")
    assert res.route == RouteType.AGENT
    assert "notepad" in res.command.lower()


def test_router_forced_dictation_mode(router):
    # In DICTATION mode, even wake words are typed as text
    res = router.route("Jarvis, open Notepad.", forced_mode="dictation")
    assert res.route == RouteType.TEXT
