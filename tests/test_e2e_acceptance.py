import time
import pytest

from pasta.agent.candidates import CandidateBuilder
from pasta.agent.models.mock import MockDecisionModel
from pasta.agent.router import CommandRouter, RouteType
from pasta.agent.schemas import ComputerState


@pytest.fixture
def setup_suite():
    router = CommandRouter()
    builder = CandidateBuilder()
    model = MockDecisionModel()
    dummy_state = ComputerState(timestamp=time.time())
    return router, builder, model, dummy_state


ACCEPTANCE_TEST_CASES = [
    ("Pasta, open Calculator.", "AGENT", "launch_calculator"),
    ("Pasta, open Chrome and search for Python documentation.", "AGENT", "search_web"),
    ("Pasta, switch to VS Code.", "AGENT", "focus_vscode"),
    ("Pasta, open Downloads.", "AGENT", "open_downloads"),
    ("Pasta, create a new browser tab and open github.com.", "AGENT", "new_browser_tab"),
    ("Pasta, go back.", "AGENT", "browser_back"),
    ("Pasta, copy this and paste it into Notepad.", "AGENT", "copy_selection"),
    ("Pasta, run git status in this repository.", "AGENT", "run_git_status"),
    ("Pasta, mute the computer.", "AGENT", "toggle_mute"),
    ("Pasta, stop.", "AGENT", "stop"),
]


@pytest.mark.parametrize("transcript,expected_route,expected_top_action", ACCEPTANCE_TEST_CASES)
def test_acceptance_cases(setup_suite, transcript, expected_route, expected_top_action):
    router, builder, model, state = setup_suite

    # Step 1: Routing
    route_res = router.route(transcript)
    assert route_res.route.value == expected_route

    # Step 2: Candidates
    goal = route_res.command or transcript
    candidates = builder.build_candidates(state, goal)
    cand_ids = [c.id for c in candidates]
    assert expected_top_action in cand_ids

    # Step 3: Decider Top-1
    questions = [{"question": f"What to do for '{goal}'?", "options": cand_ids}]
    decisions = model.decide(state.to_summary_dict(), questions)
    assert len(decisions) == 1
    assert decisions[0].action_id == expected_top_action
