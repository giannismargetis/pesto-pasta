import pytest

from pasta.agent.safety import SafetyPolicy
from pasta.agent.schemas import AgentAction, RiskLevel
from pasta.config import Config


@pytest.fixture
def policy():
    cfg = Config()
    cfg.agent.confidence_threshold = 0.72
    cfg.agent.confirmation_threshold = 0.55
    return SafetyPolicy(cfg)


def test_safety_high_confidence_allowed(policy):
    action = AgentAction(id="launch_chrome", description="Open Chrome", category="app", risk=RiskLevel.LOW)
    check = policy.evaluate(action, confidence=0.85)
    assert check.allowed is True
    assert check.requires_confirmation is False


def test_safety_moderate_confidence_requires_confirmation(policy):
    action = AgentAction(id="launch_chrome", description="Open Chrome", category="app", risk=RiskLevel.LOW)
    check = policy.evaluate(action, confidence=0.62)
    assert check.allowed is True
    assert check.requires_confirmation is True


def test_safety_low_confidence_abstains(policy):
    action = AgentAction(id="launch_chrome", description="Open Chrome", category="app", risk=RiskLevel.LOW)
    check = policy.evaluate(action, confidence=0.45)
    assert check.allowed is False


def test_safety_destructive_action_always_confirms(policy):
    policy.perm_cfg.filesystem_write = True
    action = AgentAction(id="delete_database", description="Delete database", category="filesystem", risk=RiskLevel.DESTRUCTIVE)
    check = policy.evaluate(action, confidence=0.99)
    assert check.allowed is True
    assert check.requires_confirmation is True


def test_safety_permission_disabled():
    cfg = Config()
    cfg.permissions.browser = False
    policy = SafetyPolicy(cfg)

    action = AgentAction(id="search_web", description="Search web", category="browser", risk=RiskLevel.LOW)
    check = policy.evaluate(action, confidence=0.95)
    assert check.allowed is False
