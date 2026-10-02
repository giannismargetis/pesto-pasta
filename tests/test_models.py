import pytest

from pasta.agent.models.base import DecisionModel
from pasta.agent.models.mock import MockDecisionModel


def test_mock_model_implements_protocol():
    model = MockDecisionModel()
    assert isinstance(model, DecisionModel)
    assert model.is_loaded() is True


def test_mock_model_probability_sum_to_one():
    model = MockDecisionModel()
    state = {"goal": "open Chrome"}
    questions = [
        {
            "question": "What to do next?",
            "options": ["launch_chrome", "open_notepad", "stop"],
        }
    ]

    decisions = model.decide(state, questions)
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action_id == "launch_chrome"
    assert d.confidence > 0.50

    total_prob = sum(d.raw_scores.values())
    assert pytest.approx(total_prob, 0.001) == 1.0


def test_mock_model_unload_and_load():
    model = MockDecisionModel()
    model.unload()
    assert model.is_loaded() is False
    model.load()
    assert model.is_loaded() is True
