"""Whisper (faster-whisper / CTranslate2) with a single encoder pass.

Why not just call ``WhisperModel.transcribe(language=None)``? Because in
faster-whisper 1.2 that runs the 30-second encoder **twice** — once inside
``detect_language`` and again inside ``generate_segments`` (the encoder output
is not passed on). The encoder is by far the most expensive part of
large-v3-turbo (32 layers vs 4 decoder layers), so automatic language mode
paid roughly double. Here we:

1. compute log-mel features once,
2. run the encoder once on the first window,
3. read language probabilities from that encoder output and choose among the
   *configured* languages only (default el/en) — a bilingual Greek/English
   user should never get Portuguese for a 0.6 s mumble (observed in the old
   logs),
4. decode, reusing the same encoder output.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from ..config import AsrSettings
from ..log import get_logger
from .base import Engine, Transcript
from .models import WHISPER_REPOS, resolve_snapshot

log = get_logger("asr.whisper")

PROMPTS = {
    "el": "Ελληνικά, με σωστούς τόνους και σημεία στίξης.",
    "en": "English, with correct punctuation and capitalization.",
}
# Whole-utterance outputs Whisper is known to produce on non-speech audio
# (subtitle credits from its training data). Only exact whole-output matches on
# short clips are dropped; plausible dictation such as "thank you" never is.
# The primary protection is the VAD speech gate in the session.
HALLUCINATIONS = {
    "thanks for watching", "thank you for watching", "subtitles by the amara org community",
    "υπότιτλοι authorwave", "ευχαριστώ που παρακολουθήσατε",
}


def _cuda_device_count() -> int:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


class WhisperEngine(Engine):
    name = "whisper"

    def __init__(self, settings: AsrSettings) -> None:
        super().__init__()
        self.s = settings
        self._model = None
        self._lock = threading.Lock()  # one decode at a time; CT2 model is not re-entrant per stream
        self.compute_type = ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            from ..cuda import register_cuda_libraries

            register_cuda_libraries()
            repo = WHISPER_REPOS.get(self.s.whisper_model, self.s.whisper_model)
            path = str(resolve_snapshot(repo))
            want_cuda = self.s.device in ("auto", "cuda") and _cuda_device_count() > 0
            attempts = [("cuda", self.s.whisper_compute_type)] if want_cuda else []
            attempts.append(("cpu", self.s.whisper_cpu_compute_type))
            last_exc: Exception | None = None
            for device, compute in attempts:
                try:
                    self._model = WhisperModel(
                        path, device=device, compute_type=compute, cpu_threads=0 if device == "cuda" else 4, num_workers=1
                    )
                    self.device, self.compute_type = device, compute
                    # A CUDA model can construct fine and only fail at the first
                    # encode (e.g. cuBLAS missing), so the warm-up is part of the
                    # attempt. It also primes kernels for the first real utterance.
                    self._decode_locked(np.zeros(16000, dtype=np.float32), "en", True)
                    break
                except Exception as exc:  # e.g. missing CUDA libs -> CPU
                    self._model = None
                    last_exc = exc
                    log.warning("Whisper on %s/%s unavailable (%s)%s", device, compute, exc,
                                "; falling back to CPU" if device == "cuda" else "")
            if self._model is None:
                raise RuntimeError(f"Whisper could not be loaded: {last_exc}")
        log.info("Whisper %s ready on %s (%s)", self.s.whisper_model, self.device, self.compute_type)

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self.device = "unloaded"

    # -- decoding -------------------------------------------------------------------
    def _options(self, tokenizer, preview: bool, prompt: str | None):
        from faster_whisper.transcribe import TranscriptionOptions, get_suppressed_tokens

        beam = 1 if preview else max(1, self.s.whisper_beam_size)
        temps = [0.0, 0.2, 0.4] if (self.s.whisper_temperature_fallback and not preview) else [0.0]
        return TranscriptionOptions(
            beam_size=beam, best_of=beam, patience=1.0, length_penalty=1.0, repetition_penalty=1.0,
            no_repeat_ngram_size=0, log_prob_threshold=-1.0, no_speech_threshold=0.6,
            compression_ratio_threshold=2.4, condition_on_previous_text=False, prompt_reset_on_temperature=0.5,
            temperatures=temps, initial_prompt=prompt, prefix=None, suppress_blank=True,
            suppress_tokens=get_suppressed_tokens(tokenizer, [-1]), without_timestamps=True,
            max_initial_timestamp=1.0, word_timestamps=False, prepend_punctuations="\"'“¿([{-",
            append_punctuations="\"'.。,，!！?？:：”)]}、", multilingual=False, max_new_tokens=None,
            clip_timestamps="0", hallucination_silence_threshold=None, hotwords=None,
        )

    def _choose_language(self, model, encoder_output) -> tuple[str, float]:
        probs = dict(model.model.detect_language(encoder_output)[0])
        candidates = [lang for lang in self.s.languages if f"<|{lang}|>" in probs] or ["en"]
        scored = {lang: probs.get(f"<|{lang}|>", 0.0) for lang in candidates}
        best = max(scored, key=scored.get)
        total = sum(scored.values()) or 1.0
        return best, scored[best] / total

    def transcribe(self, audio, language=None, *, preview=False) -> Transcript:
        with self._lock:
            return self._decode_locked(audio, language, preview)

    def _decode_locked(self, audio, language, preview) -> Transcript:
        from faster_whisper.audio import pad_or_trim
        from faster_whisper.tokenizer import Tokenizer

        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        # Caller holds self._lock.
        model = self._model
        if model is None or audio.size == 0:
            return Transcript("", no_speech=True)
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if self.s.whisper_vad and not preview:
            from faster_whisper.vad import VadOptions, collect_chunks, get_speech_timestamps

            chunks = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400, speech_pad_ms=200))
            if not chunks:
                return Transcript("", no_speech=True, timings_ms={"vad": (time.perf_counter() - t0) * 1e3})
            audio = np.concatenate(collect_chunks(audio, chunks)[0])
            timings["vad"] = (time.perf_counter() - t0) * 1e3

        t = time.perf_counter()
        features = model.feature_extractor(audio)
        content_frames = features.shape[-1] - 1
        first = pad_or_trim(features[:, : min(model.feature_extractor.nb_max_frames, content_frames)])
        timings["features"] = (time.perf_counter() - t) * 1e3

        t = time.perf_counter()
        encoder_output = model.encode(first)
        timings["encode"] = (time.perf_counter() - t) * 1e3

        t = time.perf_counter()
        if language:
            lang, lang_prob = language, 1.0
        else:
            lang, lang_prob = self._choose_language(model, encoder_output)
        timings["langid"] = (time.perf_counter() - t) * 1e3

        t = time.perf_counter()
        tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=lang)
        prompt = PROMPTS.get(lang) if self.s.whisper_prompt else None
        options = self._options(tokenizer, preview, prompt)
        parts = []
        for seg in model.generate_segments(features, tokenizer, options, False, encoder_output):
            text = seg.text.strip()
            if text:
                parts.append(text)
        timings["decode"] = (time.perf_counter() - t) * 1e3

        text = " ".join(parts).strip()
        if text and _normalized(text) in HALLUCINATIONS and audio.size < 16000 * 3:
            log.debug("Dropped probable hallucination: %r", text)
            text = ""
        timings["total"] = (time.perf_counter() - t0) * 1e3
        return Transcript(text, lang, lang_prob, timings, no_speech=not text)


def _normalized(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").strip()
