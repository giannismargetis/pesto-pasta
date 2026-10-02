import pytest

from pasta.agent.candidates import CandidateBuilder
from pasta.agent.schemas import ComputerState, WindowState


@pytest.fixture
def builder():
    return CandidateBuilder()


def test_candidates_open_chrome(builder):
    state = ComputerState(timestamp=0)
    candidates = builder.build_candidates(state, "open Chrome")
    c_ids = [c.id for c in candidates]

    assert "launch_chrome" in c_ids
    assert "stop" in c_ids
    assert 3 <= len(candidates) <= 12


def test_candidates_focus_chrome_when_open(builder):
    state = ComputerState(
        timestamp=0,
        windows=[WindowState(hwnd=1234, title="New Tab - Google Chrome", process_name="chrome.exe")],
    )
    candidates = builder.build_candidates(state, "switch to Chrome")
    c_ids = [c.id for c in candidates]

    assert "focus_chrome" in c_ids


def test_candidates_search_web(builder):
    state = ComputerState(timestamp=0)
    candidates = builder.build_candidates(state, "search for RTX 5090 prices")
    c_ids = [c.id for c in candidates]

    assert "search_web" in c_ids


def test_candidates_calculator(builder):
    state = ComputerState(timestamp=0)
    candidates = builder.build_candidates(state, "open Calculator")
    c_ids = [c.id for c in candidates]

    assert "launch_calculator" in c_ids


def test_candidates_git_status(builder):
    state = ComputerState(timestamp=0)
    candidates = builder.build_candidates(state, "run git status in terminal")
    c_ids = [c.id for c in candidates]

    assert "run_git_status" in c_ids


def test_candidates_mute(builder):
    state = ComputerState(timestamp=0)
    candidates = builder.build_candidates(state, "mute my computer")
    c_ids = [c.id for c in candidates]

    assert "toggle_mute" in c_ids
