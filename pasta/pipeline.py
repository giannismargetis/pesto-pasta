from collections import deque
import queue
import sys
import threading
import time

import numpy as np

from .agent.loop import AgentLoop
from .agent.models import create_decision_model
from .agent.router import CommandRouter, RouteType
from .audio import AudioCapture
from .config import Config
from .engines import create_engine, guess_language
from .history_db import get_history_db
from .hotkeys import HotkeyListener
from .injection import get_foreground_window, paste_text
from .logging_setup import get_logger
from .overlay import Overlay

log = get_logger("pipeline")

JOB_PARTIAL = "partial"
JOB_FINAL = "final"
CONTROL = "control"


class Pipeline:
    """PASTA audio, transcription, routing, and execution pipeline."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.jobs: queue.Queue = queue.Queue()
        self.shutdown = threading.Event()
        self.history: deque = deque(maxlen=100)
        self.history_db = get_history_db()
        self.session_words = 0
        self.session_duration = 0.0

        self._state_lock = threading.Lock()
        self._active_engine_name = cfg.engine
        self._language_mode = cfg.language if cfg.language in ("auto", "el", "en") else "auto"
        self._paused = False
        self._last_activity = time.monotonic()

        # Speech-to-Text Engines
        self.engines = {
            "whisper": create_engine("whisper", cfg),
            "parakeet": create_engine("parakeet", cfg),
        }

        # Overlay HUD
        self.overlay = Overlay(cfg)
        self.overlay.set_engine_and_language(self._active_engine_name, self._language_mode)

        # Agent & Router subsystem
        self.router = CommandRouter()
        self.decision_model = create_decision_model(cfg)
        self.agent_loop = AgentLoop(
            cfg=cfg,
            model=self.decision_model,
            overlay_callback=self._on_agent_overlay_update,
        )

        # Audio Capture
        self.capture = AudioCapture(
            cfg,
            on_partial=self._on_partial_audio,
            on_energy=self.overlay.set_energy,
            on_auto_finalize=self.on_ptt_up,
        )

        # Global Hotkey Listener
        self.hotkeys = HotkeyListener(
            cfg,
            on_ptt_down=self.on_ptt_down,
            on_ptt_up=self.on_ptt_up,
            on_toggle_language=self.cycle_language,
            on_toggle_engine=self.cycle_engine,
            on_cancel=self.on_cancel_agent,
        )

        self._target_hwnd = 0
        self._partials: list[str] = []
        self._agent_thread: threading.Thread | None = None

    @property
    def active_engine(self) -> str:
        with self._state_lock:
            return self._active_engine_name

    @property
    def language_mode(self) -> str:
        with self._state_lock:
            return self._language_mode

    @property
    def paused(self) -> bool:
        with self._state_lock:
            return self._paused

    def _on_agent_overlay_update(
        self,
        status: str,
        goal: str,
        confidence: float,
        step: int,
        max_steps: int,
    ) -> None:
        self.overlay.set_agent_status(status, goal, confidence, step, max_steps)

    def on_cancel_agent(self) -> None:
        """Invoked when user presses Esc."""
        log.info("Agent cancel hotkey (Esc) received")
        self.agent_loop.cancel()
        self._beep(400, 120)

    def _set_active_engine(self, name: str, force_reload: bool = False) -> None:
        with self._state_lock:
            self._active_engine_name = name
            if force_reload and name in self.engines:
                if self.engines[name].loaded:
                    self.engines[name].unload()
                self.engines[name] = create_engine(name, self.cfg)
        log.info("Engine set to '%s'", name)
        self.overlay.set_engine_and_language(name, self.language_mode)
        self.overlay.show_toast("⚡ Engine Switched", f"Active: {name.upper()}", duration=1.6)
        threading.Thread(target=self._ensure_loaded, name="preload", daemon=True).start()

    def _set_language_mode(self, mode: str) -> None:
        with self._state_lock:
            self._language_mode = mode
        labels = {"auto": "AUTO (Greek + English)", "el": "GREEK (locked)", "en": "ENGLISH (locked)"}
        log.info("Language mode: %s", labels[mode])
        self.overlay.set_engine_and_language(self.active_engine, mode)
        self.overlay.show_toast("🌐 Language Switched", f"{labels[mode]}", duration=1.6)

    def set_paused(self, paused: bool) -> None:
        with self._state_lock:
            self._paused = paused
        if paused:
            for engine in self.engines.values():
                if engine.loaded:
                    engine.unload()
            if self.decision_model.is_loaded():
                self.decision_model.unload()
            log.info("Models unloaded (paused)")
            self.overlay.show_toast("⏸️ PASTA Paused", "Models unloaded from memory", duration=1.6)
        else:
            log.info("Resumed - models will load on next use")
            self.overlay.show_toast("▶️ PASTA Resumed", "Ready for dictation & computer control", duration=1.6)
        self.jobs.put((CONTROL, None))

    def cycle_language(self) -> None:
        order = {"auto": "el", "el": "en", "en": "auto"}
        self._set_language_mode(order[self.language_mode])

    def cycle_engine(self) -> None:
        other = "parakeet" if self.active_engine == "whisper" else "whisper"
        self.set_engine(other)

    def set_engine(self, name: str, force_reload: bool = False) -> None:
        if name not in self.engines:
            return
        if name == self.active_engine and not force_reload:
            return
        self._set_active_engine(name, force_reload=force_reload)

    def switch_language(self, mode: str) -> None:
        if mode in ("auto", "el", "en"):
            self._set_language_mode(mode)

    def on_ptt_down(self) -> None:
        self._target_hwnd = get_foreground_window()
        self._partials.clear()
        self.overlay.set_partial("")
        self.overlay.set_engine_and_language(self.active_engine, self.language_mode)
        self.overlay.set_status("LISTENING")
        self.capture.begin_session()
        self.overlay.show()
        self._beep(750, 100)
        self._touch()
        self.jobs.put((CONTROL, None))

    def on_ptt_up(self, auto: bool = False) -> None:
        self.overlay.set_status("TRANSCRIBING...")
        audio = self.capture.end_session()
        if audio.size >= int(0.25 * self.cfg.sample_rate):
            self.jobs.put((JOB_FINAL, audio))
        else:
            self.overlay.hide()
        self._touch()

    def _on_partial_audio(self, audio: np.ndarray) -> None:
        self.jobs.put((JOB_PARTIAL, audio))
        self._touch()

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def _beep(self, freq: int, duration_ms: int) -> None:
        if not self.cfg.beep_enabled or sys.platform != "win32":
            return

        def _play():
            try:
                import winsound

                winsound.Beep(freq, duration_ms)
            except Exception:
                pass

        threading.Thread(target=_play, daemon=True).start()

    def _ensure_loaded(self):
        if self.paused:
            return None
        engine = self.engines[self.active_engine]
        if not engine.loaded:
            try:
                engine.load()
            except Exception as exc:
                log.error("Failed to load engine '%s': %s", engine.name, exc)
                fallback = "whisper" if engine.name == "parakeet" else "parakeet"
                try:
                    log.warning("Falling back to '%s'", fallback)
                    engine = self.engines[fallback]
                    if not engine.loaded:
                        engine.load()
                except Exception as exc2:
                    log.error("Fallback also failed: %s", exc2)
                    return None
        return engine

    def _transcribe(self, audio: np.ndarray, is_partial: bool):
        engine = self._ensure_loaded()
        if engine is None:
            return None
        language = None if self.language_mode == "auto" else self.language_mode
        started = time.perf_counter()
        try:
            result = engine.transcribe(audio, language=language, is_partial=is_partial)
        except Exception as exc:
            log.error("%s transcription failed: %s", engine.name, exc)
            return None
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        duration_s = max(audio.size / self.cfg.sample_rate, 1e-6)
        rtf = elapsed_ms / 1000.0 / duration_s
        label = "partial" if is_partial else "final"
        preview = result.text[:60].replace("\n", " ")
        lang = result.language or guess_language(result.text) or "?"
        log.info("[%s/%s/%s] %.0fms for %.1fs audio (rtf=%.2f) %s", engine.name, label, lang, elapsed_ms, duration_s, rtf, preview)
        return result

    def _process_final(self, audio: np.ndarray) -> None:
        self.overlay.set_status("TRANSCRIBING...")
        duration_s = max(audio.size / self.cfg.sample_rate, 1e-6)
        started = time.perf_counter()
        result = self._transcribe(audio, is_partial=False)
        latency_ms = (time.perf_counter() - started) * 1000.0

        text = (result.text or "").strip() if result else ""
        if not text:
            self.overlay.hide()
            log.warning("No speech detected")
            return

        # COMMAND ROUTING: Check if this is an Agent command or standard text dictation
        route_decision = self.router.route(text)
        log.info("Router decision: %s (confidence=%.2f, reason='%s')", route_decision.route.value, route_decision.confidence, route_decision.reason)

        if route_decision.route == RouteType.AGENT and getattr(self.cfg.agent, "enabled", True):
            # AGENT MODE: Run real-time computer control
            self._beep(880, 100)
            goal = route_decision.command or text
            log.info("Activating Agent Mode: '%s'", goal)

            # Non-blocking async execution of the agent loop
            self._agent_thread = threading.Thread(
                target=self.agent_loop.execute_goal,
                args=(goal, text),
                name="AgentLoopThread",
                daemon=True,
            )
            self._agent_thread.start()
            return

        # NORMAL MODE: Fast push-to-talk text insertion
        self.overlay.set_status("PASTED ✓")
        paste_ok = paste_text(text + " ", target_hwnd=self._target_hwnd)
        if paste_ok:
            self._beep(650, 100)
            log.info("Pasted: %s", text)
            detected_lang = getattr(result, "language", None) or self.language_mode

            words = len(text.split())
            self.session_words += words
            self.session_duration += duration_s
            wpm = round((words / max(duration_s, 0.4)) * 60.0, 1)

            # Record to persistent SQLite history database
            self.history_db.add_entry(
                text=text,
                duration_seconds=duration_s,
                latency_ms=latency_ms,
                engine=self.active_engine,
                language=detected_lang,
            )

            self.history.append({
                "text": text,
                "time": time.strftime("%H:%M:%S"),
                "engine": self.active_engine,
                "lang": detected_lang,
                "duration": duration_s,
                "wpm": wpm,
            })
        else:
            log.error("Paste failed")
        time.sleep(0.35)
        self.overlay.hide()

    def _process_partial(self, audio: np.ndarray) -> None:
        if audio.size < int(0.3 * self.cfg.sample_rate):
            return
        result = self._transcribe(audio, is_partial=True)
        text = (result.text or "").strip() if result else ""
        if text:
            self._partials.append(text)
            self.overlay.set_partial(text)

    def _worker_loop(self) -> None:
        idle_unload_seconds = self.cfg.idle_unload_minutes * 60.0
        while not self.shutdown.is_set():
            try:
                job_type, payload = self.jobs.get(timeout=0.5)
            except queue.Empty:
                if (
                    not self.paused
                    and idle_unload_seconds > 0
                    and (time.monotonic() - self._last_activity) >= idle_unload_seconds
                ):
                    for engine in self.engines.values():
                        if engine.loaded:
                            engine.unload()
                    if self.decision_model.is_loaded():
                        self.decision_model.unload()
                    log.info("Idle unload threshold reached: models unloaded from VRAM")
                continue

            try:
                if job_type == JOB_FINAL:
                    self._process_final(payload)
                elif job_type == JOB_PARTIAL:
                    self._process_partial(payload)
            except Exception as exc:
                log.error("Worker processing failed: %s", exc)
            finally:
                self.jobs.task_done()

    def wait_forever(self) -> None:
        try:
            while not self.shutdown.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
        finally:
            self.stop()

    def start(self) -> None:
        self.overlay.start()
        self.hotkeys.start()
        self.capture.start()

        threading.Thread(target=self._worker_loop, name="PipelineWorker", daemon=True).start()
        threading.Thread(target=self._ensure_loaded, name="Preload", daemon=True).start()

    def stop(self) -> None:
        self.shutdown.set()
        self.capture.shutdown.set()
        self.hotkeys.shutdown.set()
        self.agent_loop.cancel()
        for engine in self.engines.values():
            if engine.loaded:
                engine.unload()
        if self.decision_model.is_loaded():
            self.decision_model.unload()
