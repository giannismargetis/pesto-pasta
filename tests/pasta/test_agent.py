"""Planner grounding and agent run flow against a fake desktop (nothing is executed)."""

import threading
import time

import pytest

from pasta import planner as P
from pasta.agent import Agent
from pasta.executors import FAILED, UNVERIFIED, VERIFIED, Outcome
from pasta.intents import Intent, Risk
from pasta.settings import AgentSettings, PermissionSettings
from pasta.world.apps import App
from pasta.world.windows import Window
from pesto.events import EventBus, Phase, Status

WINDOWS = [
    Window(10, "Thesis.docx - Word", "WINWORD.EXE", 1, False, False, True),
    Window(11, "GitHub - Google Chrome", "chrome.exe", 2, False, False, False),
    Window(12, "Inbox - Google Chrome", "chrome.exe", 2, False, False, False),
    Window(13, "@friend - Discord", "Discord.exe", 3, False, False, False),
]


def fake_index():
    """The real AppIndex matching logic over a fixed app list."""
    from pasta.world.apps import AppIndex

    idx = AppIndex()
    idx._set([App("Visual Studio Code", "Microsoft.VisualStudioCode"), App("Steam", "Valve.Steam"),
              App("Steam Support Center", "x"), App("Support by e-mail", "y"), App("Uninstall Steam", "z")])
    return idx


class FakeExec:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args[:-1]))
            return Outcome(VERIFIED, f"{name} ok")
        return call


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(P.W, "list_windows", lambda: list(WINDOWS))
    monkeypatch.setattr(P.W, "foreground_hwnd", lambda: 10)
    monkeypatch.setattr(P.W, "window_info", lambda h, fg=None: next((w for w in WINDOWS if w.hwnd == h), None))
    monkeypatch.setattr(P.W, "class_name", lambda h: "OpusApp")
    ex = FakeExec()
    return P.Planner(ex, fake_index(), AgentSettings(), PermissionSettings()), ex


def test_open_existing_window_focuses_it(world):
    planner, ex = world
    step = planner.ground(Intent("open", {"target": "Discord"}))
    assert step.label.startswith("Switch to") and step.confidence >= 0.9
    step.run(None)
    assert ex.calls[0][0] == "focus"


def test_open_installed_app_launches_it(world):
    planner, ex = world
    step = planner.ground(Intent("open", {"target": "vs code"}))
    step.run(None)
    assert ex.calls[0][0] == "launch" and ex.calls[0][1][0].name == "Visual Studio Code"


def test_weak_fuzzy_app_match_is_not_found(world):
    planner, _ = world
    with pytest.raises(P.GroundingError):
        planner.ground(Intent("open", {"target": "spotify"}))  # 'Support by e-mail' is not Spotify


def test_known_site_becomes_url(world):
    planner, ex = world
    planner.ground(Intent("open", {"target": "YouTube"})).run(None)
    assert ex.calls[0][0] == "open_url" and "youtube.com" in ex.calls[0][1][0]


def test_close_app_with_several_windows_is_high_risk(world):
    planner, ex = world
    step = planner.ground(Intent("close", {"target": "chrome"}))
    assert step.risk == Risk.HIGH and "2" in step.label
    step.run(None)
    assert len(ex.calls[0][1][0]) == 2


def test_close_without_target_uses_active_window(world):
    planner, _ = world
    assert planner.ground(Intent("close", {})).label == "Close Thesis.docx - Word"


def test_disallowed_command_cannot_be_grounded(world):
    planner, _ = world
    with pytest.raises(P.GroundingError):
        planner.ground(Intent("run_command", {"command": "del /s c:"}))


# --------------------------------------------------------------------------- agent flow
class ScriptedPlanner:
    """Planner double: each intent maps to a predetermined outcome."""

    def __init__(self, outcomes, risk=Risk.LOW, conf=1.0, delay=0.0):
        self.outcomes, self.risk, self.conf, self.delay = outcomes, risk, conf, delay
        self.ran = []

    def describe(self, intent):
        return intent.action

    def ground(self, intent):
        def run(cancel):
            self.ran.append(intent.action)
            t = time.time()
            while time.time() - t < self.delay:
                if cancel.is_set():
                    return Outcome(UNVERIFIED, "interrupted")
                time.sleep(0.01)
            return self.outcomes.get(intent.action, Outcome(VERIFIED, intent.action))
        return P.Step(intent, intent.action, run, self.risk, "apps", self.conf)


class Cfg:
    agent = AgentSettings(confirm_timeout_s=1.0)
    permissions = PermissionSettings()


def run_agent(planner, text, on_confirm=None, cancel_after=None):
    bus, seen = EventBus(), []
    agent = Agent(Cfg, bus, None, planner)
    done = threading.Event()

    def watch(st: Status):
        seen.append(st)
        if st.phase == Phase.CONFIRM and on_confirm is not None:
            threading.Timer(0.05, lambda: agent.answer(on_confirm)).start()
        if st.phase in (Phase.DONE, Phase.FAILED, Phase.CANCELLED):
            done.set()

    bus.subscribe(watch, Status)
    agent.submit(text)
    if cancel_after is not None:
        time.sleep(cancel_after)
        agent.cancel()
    done.wait(5)
    t = time.time()
    while agent.busy and time.time() - t < 5:
        time.sleep(0.01)
    return seen


def test_multi_step_run_completes(world):
    pl = ScriptedPlanner({})
    seen = run_agent(pl, "open notepad and type hello")
    assert pl.ran == ["open", "type_text"] and seen[-1].phase == Phase.DONE


def test_failed_step_stops_the_plan(world):
    pl = ScriptedPlanner({"open": Outcome(FAILED, "nope")})
    seen = run_agent(pl, "open notepad and type hello")
    assert pl.ran == ["open"] and seen[-1].phase == Phase.FAILED
    assert seen[-1].data["steps"][1]["state"] == "skipped"


def test_confirmation_declined_runs_nothing(world):
    pl = ScriptedPlanner({}, risk=Risk.HIGH)
    seen = run_agent(pl, "run git status", on_confirm=False)
    assert pl.ran == [] and Phase.CONFIRM in [s.phase for s in seen] and seen[-1].phase == Phase.CANCELLED


def test_confirmation_accepted_runs(world):
    pl = ScriptedPlanner({}, risk=Risk.HIGH)
    seen = run_agent(pl, "run git status", on_confirm=True)
    assert pl.ran == ["run_command"] and seen[-1].phase == Phase.DONE


def test_confirmation_times_out_safely(world):
    pl = ScriptedPlanner({}, risk=Risk.HIGH)
    seen = run_agent(pl, "run git status")  # nobody answers
    assert pl.ran == [] and seen[-1].phase == Phase.CANCELLED


def test_cancel_interrupts_a_running_step(world):
    pl = ScriptedPlanner({}, delay=2.0)
    t = time.time()
    run_agent(pl, "open notepad and type hello", cancel_after=0.2)
    assert time.time() - t < 1.5 and pl.ran == ["open"]


def test_not_understood_does_nothing(world):
    pl = ScriptedPlanner({})
    seen = run_agent(pl, "fly me to the moon")
    assert pl.ran == [] and seen[-1].phase == Phase.FAILED and "understand" in seen[-1].message
