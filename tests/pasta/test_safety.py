import pytest

from pasta.intents import Intent, Risk
from pasta.planner import Step
from pasta.safety import AUTO, CONFIRM, DENY, decide
from pasta.settings import AgentSettings, PermissionSettings
from pasta.shell import to_argv


def step(action="open", risk=Risk.LOW, conf=1.0, source="grammar", perm="apps"):
    return Step(Intent(action, {}, 1.0, source), "label", lambda c: None, risk, perm, conf)


S, P = AgentSettings(), PermissionSettings()


@pytest.mark.parametrize("st,expected", [
    (step(conf=0.99), AUTO),
    (step(conf=0.7), CONFIRM),
    (step(conf=0.3), DENY),
    (step("type_text", Risk.MEDIUM, 0.99, perm="keyboard"), AUTO),
    (step("type_text", Risk.MEDIUM, 0.9, perm="keyboard"), CONFIRM),
    (step("run_command", Risk.HIGH, 1.0, perm="shell"), CONFIRM),
    (step("close", Risk.MEDIUM, 1.0, perm="windows"), CONFIRM),  # close_windows = confirm by default
    (step(conf=1.0, source="llm"), CONFIRM),  # model proposals are never auto-run
])
def test_gate(st, expected):
    assert decide(st, S, P).kind == expected


def test_permissions_are_absolute():
    perm = PermissionSettings(browser=False, shell="none", close_windows="never")
    assert decide(step("open_url", perm="browser"), S, perm).kind == DENY
    assert decide(step("run_command", Risk.HIGH, perm="shell"), S, perm).kind == DENY
    assert decide(step("close", Risk.MEDIUM, perm="windows"), S, perm).kind == DENY


@pytest.mark.parametrize("cmd,argv", [
    ("git status", ["git", "status"]),
    ("git log --oneline -n 5", ["git", "log", "--oneline", "-n", "5"]),
    ("python --version", ["python", "--version"]),
    ("Python.exe -V", ["python", "-V"]),
    ("dir", ["cmd", "/c", "dir"]),
    ("ipconfig /all", ["ipconfig", "/all"]),
])
def test_shell_allowed(cmd, argv):
    assert to_argv(cmd) == argv


@pytest.mark.parametrize("cmd", [
    "git status && del /s /q c:\\", "git status; rm -rf ~", "python --version | evil", "git push", "git reset --hard",
    "del /s c:", "powershell -enc AAAA", "cmd /c whoami", "pip install requests", "dir c:\\windows", "",
    "git status > out.txt", "nvidia-smi -r",
])
def test_shell_rejected(cmd):
    assert to_argv(cmd) is None
