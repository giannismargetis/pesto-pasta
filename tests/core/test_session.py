"""VoiceSession behaviour with fake microphone / engine / injector (no hardware)."""

import threading
import time

import numpy as np
import pytest

from pesto import session as S
from pesto.asr.base import Engine, Transcript
from pesto.audio import Recording
from pesto.config import Config
from pesto.engines import EngineManager
from pesto.events import EventBus, Phase, Preview, Status
from pesto.inject import InjectResult


class FakeMic:
    def __init__(self, seconds=1.5):
        self.seconds = seconds
        self.rec = None
        self.device_name = "fake"
        self.available = True
        self.error = None

    @property
    def is_open(self):
        return self.available

    def ensure_open(self):
        return self.available

    def start(self):
        pass

    def close(self):
        pass

    def begin(self, t=None):
        pcm = (np.random.default_rng(0).standard_normal(int(self.seconds * 16000)) * 3000).astype(np.int16)
        self.rec = Recording([], 16000, t or time.perf_counter())
        self.rec.append(pcm)
        return self.rec

    def end(self):
        rec, self.rec = self.rec, None
        return rec

    def snapshot(self):
        return None if self.rec is None else self.rec.audio()


class FakeEngine(Engine):
    name = "whisper"

    def __init__(self, text="Καλημέρα σας.", delay=0.02):
        super().__init__()
        self.text, self.delay = text, delay
        self.calls = []
        self._loaded = False

    @property
    def loaded(self):
        return self._loaded

    def load(self):
        self._loaded = True
        self.device = "fake"

    def unload(self):
        self._loaded = False

    def transcribe(self, audio, language=None, *, preview=False):
        self.calls.append("preview" if preview else "final")
        time.sleep(self.delay)
        return Transcript(self.text, "el", 0.99, {"total": self.delay * 1000})


class FakeInjector:
    def __init__(self):
        self.typed = []

    def inject(self, text, target_hwnd=0):
        self.typed.append(text)
        return InjectResult(True, "unicode", 1.0, target_app="notepad.exe")


class FakeTelemetry:
    def __init__(self):
        self.rows = []

    def record_interaction(self, row):
        self.rows.append(row)


@pytest.fixture
def rig(monkeypatch, tmp_path):
    cfg = Config(tmp_path / "c.json")
    cfg.ui.live_preview = False
    bus = EventBus()
    statuses = []
    bus.subscribe(lambda s: statuses.append(s), Status)
    engine = FakeEngine()
    mgr = EngineManager(cfg.asr, bus)
    mgr._engines["whisper"] = engine
    inj, tel = FakeInjector(), FakeTelemetry()
    sess = S.VoiceSession(cfg, bus, tel, mgr, inj)
    sess.mic = FakeMic()
    speech = {"value": True}
    monkeypatch.setattr(S.vad, "speech_probabilities",
                        lambda a: np.full(max(1, a.size // 512), 0.9 if speech["value"] else 0.05, dtype=np.float32))
    monkeypatch.setattr(S, "foreground_window", lambda: 1234)
    sess.start(preload=False)
    yield {"s": sess, "cfg": cfg, "engine": engine, "inj": inj, "tel": tel, "st": statuses, "speech": speech, "bus": bus}
    sess.stop()


def wait_until(pred, timeout=3.0):
    t = time.time()
    while time.time() - t < timeout:
        if pred():
            return True
        time.sleep(0.01)
    return False


def dictate(s, hold=0.05):
    t = time.perf_counter()
    s.on_ptt("press", t)
    s.on_ptt("confirm", t + 0.01)
    time.sleep(hold)
    s.on_ptt("release", time.perf_counter())


def test_dictation_inserts_text_and_records_latency(rig):
    dictate(rig["s"])
    assert wait_until(lambda: rig["tel"].rows)
    assert rig["inj"].typed == ["Καλημέρα σας. "]
    row = rig["tel"].rows[0]
    assert row["outcome"] == "inserted" and row["kind"] == "dictation"
    assert row["release_to_text_ms"] >= row["asr_ms"] >= 15
    assert row["speech_end_to_text_ms"] is not None
    phases = [s.phase for s in rig["st"]]
    assert phases[:2] == [Phase.LISTENING, Phase.TRANSCRIBING] and phases[-1] == Phase.DONE


def test_silence_is_gated_before_asr(rig):
    rig["speech"]["value"] = False
    dictate(rig["s"])
    assert wait_until(lambda: rig["tel"].rows)
    assert rig["engine"].calls == []  # the expensive model never ran
    assert rig["tel"].rows[0]["outcome"] == "empty"
    assert rig["inj"].typed == []


def test_handler_can_claim_a_transcript(rig):
    class Claim:
        def claim(self, it, tr):
            return True

    rig["s"].handlers.append(Claim())
    dictate(rig["s"])
    assert wait_until(lambda: rig["tel"].rows)
    assert rig["inj"].typed == []
    assert rig["tel"].rows[0]["kind"] == "command"


def test_tap_and_chord_never_reach_asr(rig):
    s = rig["s"]
    s.on_ptt("press", time.perf_counter())
    s.on_ptt("tap", time.perf_counter())
    s.on_ptt("press", time.perf_counter())
    s.on_ptt("confirm", time.perf_counter())
    s.on_ptt("chord", time.perf_counter())
    time.sleep(0.2)
    assert rig["engine"].calls == [] and rig["tel"].rows == []
    assert [st.phase for st in rig["st"]] == [Phase.LISTENING, Phase.CANCELLED]


def test_added_latency_is_applied_and_reported_separately(rig):
    rig["cfg"].experiment.added_latency_ms = 150
    dictate(rig["s"])
    assert wait_until(lambda: rig["tel"].rows)
    row = rig["tel"].rows[0]
    assert 140 <= row["added_delay_ms"] <= 260
    assert row["release_to_text_ms"] >= row["added_delay_ms"] + row["asr_ms"]


def test_final_jobs_preempt_queued_previews(rig):
    s, engine = rig["s"], rig["engine"]
    engine.delay = 0.1
    gate = threading.Event()
    s.submit_control(gate.wait)  # block the worker so jobs queue up
    it = s._begin("ptt", time.perf_counter())
    it.feedback_shown = True
    s._jobs.put((S.PRIO_PREVIEW, next(s._seq), ("preview", it)))
    s._jobs.put((S.PRIO_PREVIEW, next(s._seq), ("preview", it)))
    s._release(time.perf_counter())
    gate.set()
    assert wait_until(lambda: rig["tel"].rows)
    assert engine.calls[0] == "final"


def test_live_preview_publishes_text(rig):
    rig["cfg"].ui.live_preview = True
    previews = []
    rig["bus"].subscribe(previews.append, Preview)
    rig["engine"].load()
    s = rig["s"]
    s.on_ptt("press", time.perf_counter())
    s.on_ptt("confirm", time.perf_counter())
    assert wait_until(lambda: previews, timeout=4.0)
    s.on_ptt("release", time.perf_counter())
    assert wait_until(lambda: rig["tel"].rows)
    assert rig["tel"].rows[0]["preview_count"] >= 1


def test_missing_microphone_is_reported_not_faked(rig):
    """With no microphone a press must say so, never show 'listening' then 'too short'."""
    rig["s"].mic.available = False
    dictate(rig["s"])
    time.sleep(0.2)
    phases = [st.phase for st in rig["st"]]
    assert Phase.LISTENING not in phases and Phase.EMPTY not in phases
    assert phases and phases[-1] == Phase.FAILED and "microphone" in rig["st"][-1].message.lower()
    assert rig["tel"].rows == []
