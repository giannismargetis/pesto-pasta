from pathlib import Path
import pytest

from pasta.agent.actions.app import find_and_open_file
from pasta.agent.actions.keyboard import copy_selection, paste_clipboard
from pasta.agent.actions.shell import run_safe_terminal_command


def test_safe_terminal_command_python():
    res = run_safe_terminal_command("python --version")
    assert res.success is True
    assert "Python" in res.evidence.get("output", "")


def test_safe_terminal_command_git_status():
    res = run_safe_terminal_command("git status")
    assert res.success is True
    assert res.evidence.get("exit_code") == 0


def test_blocked_unsafe_terminal_command():
    res = run_safe_terminal_command("rm -rf C:\\")
    assert res.success is False
    assert "allowlist" in res.message


def test_find_file_nonexistent():
    res = find_and_open_file("nonexistent_random_file_xyz_123.bin")
    assert res.success is False
