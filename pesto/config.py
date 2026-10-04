"""Typed, validated configuration persisted as JSON.

The file is organised in sections. The core (PESTO) owns ``asr``, ``audio``,
``input``, ``inject``, ``ui`` and ``experiment``; extensions (PASTA) register
additional sections with :func:`register_section`. Sections that are present
in the file but not registered in the running process are preserved verbatim,
so running plain PESTO never deletes PASTA's settings.

Old flat config files (PESTO v5 / PASTA v2) are migrated on load.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .log import get_logger

log = get_logger("config")

ENGINES = ("whisper", "parakeet")
LANGUAGE_MODES = ("auto", "el", "en")


@dataclass
class AsrSettings:
    engine: str = "whisper"
    language: str = "auto"  # auto = choose among `languages`; or force one
    languages: list[str] = field(default_factory=lambda: ["el", "en"])
    device: str = "auto"  # auto | cuda | cpu
    whisper_model: str = "large-v3-turbo"
    whisper_compute_type: str = "int8_float16"
    whisper_cpu_compute_type: str = "int8"
    whisper_beam_size: int = 2  # beam 2: -0.8 pp Greek WER vs beam 1 for +11-24 ms (docs/ENGINEERING_LOG.md)
    whisper_vad: bool = False
    whisper_prompt: bool = True
    whisper_temperature_fallback: bool = True
    parakeet_model: str = "nemo-parakeet-tdt-0.6b-v3"
    # auto = fp32 on CUDA (int8 kernels are slow on the CUDA provider), int8 on CPU; or "int8" / "fp32"
    parakeet_quantization: str = "auto"
    idle_unload_minutes: int = 20


@dataclass
class AudioSettings:
    sample_rate: int = 16000
    device: str = ""  # sounddevice name/index; "" = system default
    preroll_ms: int = 300
    min_utterance_ms: int = 250
    max_utterance_s: int = 120


@dataclass
class InputSettings:
    mode: str = "ptt"  # ptt | vad (hands-free)
    ptt_key: str = "right ctrl"
    hold_threshold_ms: int = 150  # shorter presses are taps, not dictation
    cancel_key: str = "esc"
    vad_toggle_key: str = "ctrl+alt+shift+v"
    language_key: str = "ctrl+alt+shift+l"
    engine_key: str = "ctrl+alt+shift+e"
    mode_key: str = "ctrl+alt+shift+m"
    vad_threshold: float = 0.5
    vad_end_silence_ms: int = 700
    vad_min_speech_ms: int = 250


@dataclass
class InjectSettings:
    method: str = "auto"  # auto | unicode | clipboard
    clipboard_threshold_chars: int = 600
    clipboard_apps: list[str] = field(default_factory=lambda: ["mstsc.exe", "vmconnect.exe"])
    restore_clipboard: bool = True
    trailing_space: bool = True


@dataclass
class UiSettings:
    hud: bool = True
    live_preview: bool = True
    sounds: bool = True
    hud_position: str = "bottom"  # bottom | top
    start_dashboard: bool = False


@dataclass
class ExperimentSettings:
    """Controls used by the HCI study platform (docs/STUDY_PROTOCOL.md)."""

    participant: str = ""
    condition: str = ""
    added_latency_ms: int = 0  # artificial delay before text appears
    save_audio: bool = False  # keep utterance WAVs for later WER scoring


@dataclass
class GeneralSettings:
    run_on_startup: bool = False
    log_level: str = "INFO"


_CORE_SECTIONS: dict[str, type] = {
    "general": GeneralSettings,
    "asr": AsrSettings,
    "audio": AudioSettings,
    "input": InputSettings,
    "inject": InjectSettings,
    "ui": UiSettings,
    "experiment": ExperimentSettings,
}
_EXTENSION_SECTIONS: dict[str, type] = {}
_MIGRATIONS: dict[str, Any] = {}


def register_section(name: str, cls: type, migrate=None) -> None:
    """Register an extension-owned config section (e.g. PASTA's ``agent``).

    ``migrate`` optionally rewrites a raw (possibly legacy) dict before it is
    applied to the dataclass.
    """
    if name in _CORE_SECTIONS:
        raise ValueError(f"'{name}' is a core section")
    _EXTENSION_SECTIONS[name] = cls
    if migrate is not None:
        _MIGRATIONS[name] = migrate


class Config:
    """Container of section dataclasses: ``cfg.asr.engine``, ``cfg.agent...``"""

    def __init__(self, path: Path = paths.CONFIG_PATH) -> None:
        self.path = path
        self._sections: dict[str, Any] = {n: c() for n, c in {**_CORE_SECTIONS, **_EXTENSION_SECTIONS}.items()}
        self._unknown: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        sections = self.__dict__.get("_sections", {})
        if name in sections:
            return sections[name]
        cls = _EXTENSION_SECTIONS.get(name)
        if cls is not None:  # registered after this Config was created
            raw = self.__dict__.get("_unknown", {}).pop(name, {})
            sections[name] = _apply(cls(), raw, name)
            return sections[name]
        raise AttributeError(name)

    def to_dict(self) -> dict[str, Any]:
        data = {name: dataclasses.asdict(obj) for name, obj in self._sections.items()}
        data.update(self._unknown)
        return data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=self.path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)


def _coerce(value: Any, annotation: Any, where: str) -> Any:
    origin = typing.get_origin(annotation)
    target = origin or annotation
    if target is list:
        if not isinstance(value, list):
            raise TypeError(f"{where}: expected list")
        return list(value)
    if target is bool:
        if not isinstance(value, bool):
            raise TypeError(f"{where}: expected true/false")
        return value
    if target is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{where}: expected integer")
        return int(value)
    if target is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{where}: expected number")
        return float(value)
    if target is str:
        if not isinstance(value, str):
            raise TypeError(f"{where}: expected string")
        return value
    return value


def _apply(obj: Any, raw: dict, section: str) -> Any:
    if section in _MIGRATIONS:
        raw = _MIGRATIONS[section](dict(raw))
    hints = typing.get_type_hints(type(obj))
    for key, value in raw.items():
        if key not in hints:
            log.warning("config: ignoring unknown key %s.%s", section, key)
            continue
        try:
            setattr(obj, key, _coerce(value, hints[key], f"{section}.{key}"))
        except TypeError as exc:
            log.warning("config: %s (keeping default %r)", exc, getattr(obj, key))
    return obj


# Flat keys of PESTO v5 / PASTA v2 config files -> (section, key[, transform])
_LEGACY: dict[str, tuple] = {
    "engine": ("asr", "engine"),
    "language": ("asr", "language"),
    "whisper_model": ("asr", "whisper_model"),
    "whisper_compute_cuda": ("asr", "whisper_compute_type"),
    "whisper_compute_cpu": ("asr", "whisper_cpu_compute_type"),
    "parakeet_model": ("asr", "parakeet_model"),
    "parakeet_quantization": ("asr", "parakeet_quantization"),
    "idle_unload_minutes": ("asr", "idle_unload_minutes"),
    "hotkey": ("input", "ptt_key"),
    "cancel_key": ("input", "cancel_key"),
    "sample_rate": ("audio", "sample_rate"),
    "max_recording_seconds": ("audio", "max_utterance_s"),
    "device": ("audio", "device"),
    "audio_device": ("audio", "device"),
    "input_device": ("audio", "device"),
    "mic_device": ("audio", "device"),
    "beep_enabled": ("ui", "sounds"),
    "overlay_enabled": ("ui", "hud"),
    "run_on_startup": ("general", "run_on_startup"),
}


def _migrate(raw: dict) -> dict:
    if any(isinstance(v, dict) for k, v in raw.items() if k in _CORE_SECTIONS):
        return raw
    migrated: dict[str, dict] = {}
    for key, value in raw.items():
        if key in _LEGACY:
            section, new_key = _LEGACY[key]
            migrated.setdefault(section, {})[new_key] = value
        elif isinstance(value, dict):
            migrated[key] = value  # e.g. legacy "agent"/"permissions" blocks
    log.info("config: migrated legacy flat configuration")
    return migrated


def validate(cfg: Config) -> None:
    if cfg.asr.engine not in ENGINES:
        log.warning("config: unknown engine %r, using whisper", cfg.asr.engine)
        cfg.asr.engine = "whisper"
    if cfg.asr.language not in LANGUAGE_MODES:
        cfg.asr.language = "auto"
    if cfg.input.mode not in ("ptt", "vad"):
        cfg.input.mode = "ptt"
    if cfg.inject.method not in ("auto", "unicode", "clipboard"):
        cfg.inject.method = "auto"
    cfg.input.hold_threshold_ms = max(0, min(cfg.input.hold_threshold_ms, 1000))
    cfg.experiment.added_latency_ms = max(0, min(cfg.experiment.added_latency_ms, 10_000))


def load_config(path: Path = paths.CONFIG_PATH) -> Config:
    cfg = Config(path)
    if not path.exists():
        cfg.save()
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("config: cannot read %s (%s); using defaults", path, exc)
        return cfg
    raw = _migrate(raw)
    for name, value in raw.items():
        if name in cfg._sections and isinstance(value, dict):
            _apply(cfg._sections[name], value, name)
        else:
            cfg._unknown[name] = value
    validate(cfg)
    return cfg
