"""The voice interaction pipeline: input -> audio -> ASR -> (handlers) -> text.

Threads
-------
* hook / dispatch threads deliver PTT events (``pesto.hotkeys``)
* the PortAudio thread fills the current :class:`~pesto.audio.Recording`
* **one ASR worker thread** owns the model: loads, unloads and transcribes.
  Jobs are prioritised: a final transcription is always taken before any
  pending live preview, and previews are dropped once stale. A preview that is
  already running when the key is released can still delay the final by up to
  one preview's duration; that wait is recorded as ``queue_ms``.

Every interaction carries a timeline of ``perf_counter`` marks (press,
confirm, release, asr_start, asr_end, inject_start, inject_end, ...). The
derived latencies are stored per interaction in telemetry — this is the
instrument behind the thesis' latency measurements.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from . import paths
from .asr import Transcript, vad
from .audio import Microphone, Recording
from .config import Config
from .engines import EngineManager
from .events import EventBus, Phase, Preview, Status
from .inject import InjectResult, TextInjector, foreground_window, window_process_name
from .log import get_logger
from .telemetry import Telemetry, now_iso

log = get_logger("session")

PRIO_CONTROL, PRIO_FINAL, PRIO_PREVIEW = 0, 1, 2


@dataclass
class Interaction:
    id: str
    input_mode: str  # ptt | vad
    started_at: str
    t_press: float
    marks: dict[str, float] = field(default_factory=dict)
    target_hwnd: int = 0
    target_app: str = ""
    recording: Recording | None = None
    feedback_shown: bool = False
    previews: int = 0
    first_preview_t: float | None = None
    speech_end_t: float | None = None
    kind: str = "dictation"
    outcome: str = ""
    text: str = ""
    error: str = ""
    transcript: Transcript | None = None
    inject: InjectResult | None = None
    speech_ms: float = 0.0

    def mark(self, name: str, t: float | None = None) -> float:
        self.marks[name] = time.perf_counter() if t is None else t
        return self.marks[name]

    def span(self, a: str, b: str) -> float | None:
        if a in self.marks and b in self.marks:
            return (self.marks[b] - self.marks[a]) * 1000.0
        return None


class TranscriptHandler(Protocol):
    """Extension hook (PASTA): claim a transcript before it is typed."""

    def claim(self, interaction: Interaction, transcript: Transcript) -> bool: ...


class VoiceSession:
    def __init__(self, cfg: Config, bus: EventBus, telemetry: Telemetry | None,
                 engines: EngineManager, injector: TextInjector) -> None:
        self.cfg = cfg
        self.bus = bus
        self.telemetry = telemetry
        self.engines = engines
        self.injector = injector
        self.handlers: list[TranscriptHandler] = []
        self.on_escape: list[Callable[[], bool]] = []  # extensions; return True if they handled it
        self.session_id = uuid.uuid4().hex[:8]
        self.mic = Microphone(cfg.audio, on_level=self._on_level, on_limit=self._on_limit,
                              on_frames=self._on_frames)
        self._jobs: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._current: Interaction | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._preview_busy = threading.Event()
        self._paused = False
        self._vad = VadSegmenter(self)
        self.vad_listening = cfg.input.mode == "vad"
        self.enabled = True  # False: ignore all speech input (e.g. keyboard condition of a study)
        self.engines.on_state = lambda m: self._publish_settings()
        self.last_completed: Interaction | None = None

    # -- lifecycle --------------------------------------------------------------------
    def start(self, preload: bool = True) -> None:
        threading.Thread(target=self._worker, name="AsrWorker", daemon=True).start()
        threading.Thread(target=self._preview_ticker, name="PreviewTicker", daemon=True).start()
        if not self.mic.ensure_open():
            self.bus.publish(Status(Phase.FAILED, message="No microphone found",
                                    detail="connect or switch on your microphone — PESTO will pick it up"))
        threading.Thread(target=self._mic_watchdog, name="MicWatchdog", daemon=True).start()
        if preload:
            self.submit_control(self.engines.ensure_loaded)
        self._publish_settings()

    def _mic_watchdog(self) -> None:
        """Recover automatically when a microphone appears or comes back."""
        was_open = self.mic.is_open
        while not self._stop.wait(3.0):
            if self._current is not None:
                continue
            ok = self.mic.ensure_open()
            if ok != was_open:
                was_open = ok
                if ok:
                    self.bus.publish(Status(Phase.DONE, message="Microphone connected", detail=self.mic.device_name))
                self._publish_settings()

    def stop(self) -> None:
        self._stop.set()
        self.mic.close()
        self.submit_control(self.engines.unload_all)
        self._jobs.put((PRIO_CONTROL, next(self._seq), None))

    def submit_control(self, fn: Callable[[], object]) -> None:
        self._jobs.put((PRIO_CONTROL, next(self._seq), ("control", fn)))

    # -- settings ---------------------------------------------------------------------
    def set_engine(self, name: str) -> None:
        def do() -> None:
            self.engines.switch(name)
            self.engines.ensure_loaded()
        self.submit_control(do)

    def cycle_engine(self) -> None:
        self.set_engine("parakeet" if self.engines.active_name == "whisper" else "whisper")

    def set_language(self, mode: str) -> None:
        self.cfg.asr.language = mode
        self._publish_settings()

    def cycle_language(self) -> None:
        order = ["auto", "el", "en"]
        self.set_language(order[(order.index(self.cfg.asr.language) + 1) % 3])

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self.submit_control(self.engines.unload_all)
        self._publish_settings()

    @property
    def paused(self) -> bool:
        return self._paused

    def toggle_vad_listening(self) -> None:
        if self.cfg.input.mode != "vad":
            return
        self.vad_listening = not self.vad_listening
        self._vad.reset()
        self._publish_settings()

    def set_input_mode(self, mode: str) -> None:
        """Switch between push-to-talk and hands-free at runtime."""
        if mode not in ("ptt", "vad"):
            raise ValueError(mode)
        self.cfg.input.mode = mode
        self._vad.reset()
        self.vad_listening = mode == "vad"
        self._publish_settings()

    def publish_settings(self) -> None:
        self._publish_settings()

    def _publish_settings(self) -> None:
        from .events import Settings

        extra_mode = getattr(self, "mode_label", "dictation")
        self.bus.publish(Settings(self.engines.active_name, self.cfg.asr.language, extra_mode,
                                  self.cfg.input.mode if not self._paused else "paused",
                                  self.engines.state, self.engines.device))

    # -- input events -----------------------------------------------------------------
    def on_ptt(self, name: str, t: float) -> None:
        if name == "press":
            self._begin("ptt", t)
        elif name == "confirm":
            self._confirm(t)
        elif name == "release":
            self._release(t)
        elif name in ("tap", "chord", "cancel"):
            self._discard(name, t)
        elif name == "escape":
            for handler in self.on_escape:
                if handler():
                    return

    def _begin(self, input_mode: str, t: float, recording: Recording | None = None) -> Interaction | None:
        if self._paused or not self.enabled:
            return None
        if not self.mic.ensure_open():
            # Never pretend to listen with a dead microphone.
            self.bus.publish(Status(Phase.FAILED, message="No microphone",
                                    detail="connect or switch on your microphone"))
            return None
        hwnd = foreground_window()
        it = Interaction(uuid.uuid4().hex[:12], input_mode, now_iso(), t, target_hwnd=hwnd)
        it.mark("press", t)
        it.recording = recording if recording is not None else self.mic.begin(t)
        with self._lock:
            self._current = it
        return it

    def _confirm(self, t: float) -> None:
        it = self._current
        if it is None:
            return
        it.mark("confirm", t)
        it.feedback_shown = True
        self.bus.publish(Status(Phase.LISTENING, it.id, message=self._listening_label()))

    def _listening_label(self) -> str:
        lang = {"auto": "Ελληνικά · English", "el": "Ελληνικά", "en": "English"}[self.cfg.asr.language]
        return lang

    def _release(self, t: float) -> None:
        with self._lock:
            it, self._current = self._current, None
        if it is None:
            return
        it.mark("release", t)
        rec = self.mic.end() or it.recording
        it.recording = rec
        if rec is None or rec.seconds * 1000 < self.cfg.audio.min_utterance_ms:
            self._finish(it, "empty", Phase.EMPTY, "Too short")
            return
        self.bus.publish(Status(Phase.TRANSCRIBING, it.id, message="Transcribing"))
        self._jobs.put((PRIO_FINAL, next(self._seq), ("final", it)))

    def _discard(self, reason: str, t: float) -> None:
        with self._lock:
            it, self._current = self._current, None
        if it is None:
            return
        self.mic.end()
        it.mark(reason, t)
        if it.feedback_shown or reason == "cancel":
            self.bus.publish(Status(Phase.CANCELLED, it.id, message="Cancelled"))
        it.outcome = "cancelled"
        log.debug("Recording discarded (%s)", reason)

    def _on_limit(self) -> None:
        it = self._current
        if it is not None and it.input_mode == "ptt":
            self._release(time.perf_counter())

    def _on_level(self, rms: float) -> None:
        if self._current is not None and self._current.feedback_shown:
            from .events import Level

            self.bus.publish(Level(min(1.0, rms * 12.0)))

    def _on_frames(self, chunk: np.ndarray) -> None:
        if self.cfg.input.mode == "vad" and self.vad_listening and self.enabled and not self._paused:
            self._vad.feed(chunk)

    # -- worker -----------------------------------------------------------------------
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                _, _, job = self._jobs.get(timeout=5.0)
            except queue.Empty:
                if self.engines.idle_unload_due():
                    log.info("Idle for %d min: unloading model", self.cfg.asr.idle_unload_minutes)
                    self.engines.unload_all()
                continue
            if job is None:
                break
            kind, payload = job
            try:
                if kind == "control":
                    payload()
                elif kind == "final":
                    self._process_final(payload)
                elif kind == "preview":
                    self._process_preview(payload)
            except Exception as exc:
                log.exception("ASR worker job failed")
                if kind == "final":
                    payload.error = str(exc)
                    self._finish(payload, "failed", Phase.FAILED, "Transcription failed", detail=str(exc))
            finally:
                if kind == "preview":
                    self._preview_busy.clear()

    def _process_final(self, it: Interaction) -> None:
        it.mark("asr_queue_end")
        audio = it.recording.audio()
        # Speech gate: decide quickly whether there is speech at all, and find
        # where it ended (user-perceived latency is measured from there).
        t = it.mark("gate_start")
        probs = vad.speech_probabilities(audio)
        speech = probs >= 0.5
        it.speech_ms = float(speech.sum()) * vad.FRAME / 16.0
        if speech.any():
            last = int(np.nonzero(speech)[0][-1])
            it.speech_end_t = it.recording.time_of((last + 1) * vad.FRAME)
        it.mark("gate_end")
        if it.speech_ms < 120:
            it.text = ""
            self._finish(it, "empty", Phase.EMPTY, "No speech detected")
            return
        del t
        engine = self.engines.ensure_loaded()
        language = None if self.cfg.asr.language == "auto" else self.cfg.asr.language
        it.mark("asr_start")
        tr = engine.transcribe(audio, language)
        it.mark("asr_end")
        it.transcript = tr
        text = tr.text.strip()
        if not text:
            self._finish(it, "empty", Phase.EMPTY, "Nothing recognised")
            return
        it.text = text
        it.mark("route_start")
        for handler in self.handlers:
            if handler.claim(it, tr):
                it.kind = "command"
                it.mark("route_end")
                self._finish(it, "command", None)
                return
        it.mark("route_end")
        self._save_audio(it, audio)
        delay = self.cfg.experiment.added_latency_ms
        if delay > 0:
            it.mark("delay_start")
            time.sleep(delay / 1000.0)
            it.mark("delay_end")
        self.bus.publish(Status(Phase.INJECTING, it.id, message=text))
        payload = text + (" " if self.cfg.inject.trailing_space else "")
        it.mark("inject_start")
        res = self.injector.inject(payload, it.target_hwnd)
        it.mark("inject_end")
        it.inject = res
        it.target_app = res.target_app
        if res.ok:
            ms = it.span("release", "inject_end") or 0.0
            self._finish(it, "inserted", Phase.DONE, text, detail=f"{ms:.0f} ms",
                         data={"latency_ms": ms, "words": len(text.split())})
        else:
            it.error = res.error
            self._finish(it, "failed", Phase.FAILED, "Could not type into the active window", detail=res.error)

    def _process_preview(self, it: Interaction) -> None:
        if self._current is not it or not self.cfg.ui.live_preview:
            return  # stale
        audio = self.mic.snapshot()
        if audio is None or audio.size < 16000 * 0.6:
            return
        engine = self.engines.active
        if not engine.loaded:
            return
        language = None if self.cfg.asr.language == "auto" else self.cfg.asr.language
        tr = engine.transcribe(audio, language, preview=True)
        if self._current is it and tr.text:
            it.previews += 1
            if it.first_preview_t is None:
                it.first_preview_t = time.perf_counter()
            self.bus.publish(Preview(it.id, tr.text))

    def _preview_ticker(self) -> None:
        while not self._stop.wait(0.15):
            it = self._current
            if it is None or not it.feedback_shown or not self.cfg.ui.live_preview:
                continue
            if self._preview_busy.is_set() or not self._jobs.empty():
                continue
            interval = 0.6 if self.engines.active_name == "parakeet" else 1.2
            last = it.marks.get("preview_sched", it.marks.get("confirm", it.t_press))
            if time.perf_counter() - last >= interval:
                it.mark("preview_sched")
                self._preview_busy.set()
                self._jobs.put((PRIO_PREVIEW, next(self._seq), ("preview", it)))

    # -- completion -------------------------------------------------------------------
    def _finish(self, it: Interaction, outcome: str, phase: Phase | None, message: str = "",
                detail: str = "", data: dict | None = None) -> None:
        it.outcome = outcome
        it.mark("done")
        if phase is not None:
            self.bus.publish(Status(phase, it.id, message=message, detail=detail, data=data or {}))
        self.last_completed = it
        self._record(it)

    def _record(self, it: Interaction) -> None:
        if self.telemetry is None:
            return
        tr, inj = it.transcript, it.inject
        rec = it.recording
        end_text = it.marks.get("inject_end")
        row = {
            "id": it.id, "started_at": it.started_at, "session_id": self.session_id,
            "participant": self.cfg.experiment.participant, "condition": self.cfg.experiment.condition,
            "input_mode": it.input_mode, "kind": it.kind, "outcome": it.outcome,
            "engine": self.engines.active_name,
            "model": self.cfg.asr.whisper_model if self.engines.active_name == "whisper" else self.cfg.asr.parakeet_model,
            "device": self.engines.device, "language_mode": self.cfg.asr.language,
            "language": tr.language if tr else None, "language_prob": tr.language_prob if tr else None,
            "audio_ms": rec.seconds * 1000 if rec else None, "speech_ms": it.speech_ms,
            "text": it.text, "words": len(it.text.split()), "chars": len(it.text),
            "target_app": it.target_app or window_process_name(it.target_hwnd),
            "inject_method": inj.method if inj else None,
            "hold_ms": it.span("press", "release"), "queue_ms": it.span("release", "asr_queue_end"),
            "gate_ms": it.span("gate_start", "gate_end"), "asr_ms": it.span("asr_start", "asr_end"),
            "route_ms": it.span("route_start", "route_end"), "added_delay_ms": it.span("delay_start", "delay_end") or 0.0,
            "inject_ms": it.span("inject_start", "inject_end"),
            "release_to_text_ms": it.span("release", "inject_end"),
            "speech_end_to_text_ms": (end_text - it.speech_end_t) * 1000 if end_text and it.speech_end_t else None,
            "preview_count": it.previews,
            "first_preview_ms": (it.first_preview_t - it.t_press) * 1000 if it.first_preview_t else None,
            "error": it.error,
            "marks_json": _marks_json(it),
        }
        self.telemetry.record_interaction(row)

    def _save_audio(self, it: Interaction, audio: np.ndarray) -> None:
        if not self.cfg.experiment.save_audio:
            return
        out = paths.DATA_DIR / "audio" / f"{it.id}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.cfg.audio.sample_rate)
            w.writeframes(pcm.tobytes())


def _marks_json(it: Interaction) -> str:
    import json

    base = it.t_press
    marks = {k: round((v - base) * 1000.0, 2) for k, v in sorted(it.marks.items(), key=lambda kv: kv[1])}
    if it.speech_end_t:
        marks["speech_end"] = round((it.speech_end_t - base) * 1000.0, 2)
    if it.transcript:
        marks["engine_breakdown"] = {k: round(v, 2) for k, v in it.transcript.timings_ms.items()}
    return json.dumps(marks)


class VadSegmenter:
    """Hands-free endpointing: speech onset opens a recording, ``end_silence``
    of non-speech closes it. Onset includes pre-roll so the first phoneme is
    kept; the endpoint is the moment the silence timeout expires (that
    timeout is *part of* the user-perceived latency and is reported)."""

    def __init__(self, session: VoiceSession) -> None:
        self.session = session
        s = session.cfg.input
        self.vad = vad.StreamingVad(s.vad_threshold)
        self.end_frames = max(1, s.vad_end_silence_ms // 32)
        self.min_frames = max(1, s.vad_min_speech_ms // 32)
        self.reset()

    def reset(self) -> None:
        self.vad.reset()
        self.speech_frames = 0
        self.silence_frames = 0
        self.active: Interaction | None = None
        self.onset_pending = 0

    def feed(self, chunk_int16: np.ndarray) -> None:
        sess = self.session
        for _, is_speech in self.vad.process(chunk_int16.astype(np.float32) / 32768.0):
            now = time.perf_counter()
            if self.active is None:
                if is_speech:
                    self.onset_pending += 1
                    if self.onset_pending >= 2 and sess._current is None:  # 64 ms of speech
                        it = sess._begin("vad", now - 0.064)
                        if it is not None:
                            self.active = it
                            sess._confirm(now)
                            self.speech_frames, self.silence_frames = self.onset_pending, 0
                else:
                    self.onset_pending = 0
                continue
            if is_speech:
                self.speech_frames += 1
                self.silence_frames = 0
            else:
                self.silence_frames += 1
                if self.silence_frames >= self.end_frames:
                    it, self.active, self.onset_pending = self.active, None, 0
                    if self.speech_frames < self.min_frames:
                        sess._discard("too_short", now)
                    else:
                        sess._release(now)
