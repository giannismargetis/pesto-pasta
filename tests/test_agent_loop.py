import pytest

from pasta.agent.loop import AgentLoop
from pasta.agent.models.mock import MockDecisionModel
from pasta.config import Config


@pytest.fixture
def agent_loop():
    cfg = Config()
    cfg.agent.max_steps = 5
    model = MockDecisionModel()
    return AgentLoop(cfg, model)


def test_agent_loop_stop_action(agent_loop):
    res = agent_loop.execute_goal("stop", transcript="Pasta, stop.")
    assert res["status"] in ("completed", "stopped")
    assert res["success"] is True


def test_agent_loop_cancel_via_event(agent_loop):
    agent_loop.cancel()
    res = agent_loop.execute_goal("open Chrome", transcript="Pasta, open Chrome.")
    assert res["status"] == "cancelled"
    assert res["success"] is False


def test_agent_loop_safe_command(agent_loop):
    res = agent_loop.execute_goal("run git status", transcript="Pasta, run git status.")
    assert res["success"] is True
    assert res["steps"] >= 1
