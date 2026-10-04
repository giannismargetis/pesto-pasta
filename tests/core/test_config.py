import json
from dataclasses import dataclass

from pesto import config as C

LEGACY_PASTA_V2 = {
    "engine": "parakeet", "language": "el", "hotkey": "right alt", "beep_enabled": False, "overlay_enabled": True,
    "whisper_compute_cuda": "float16", "max_recording_seconds": 90, "whisper_beam_size": 2,
    "agent": {"enabled": True, "model": "decider-2b", "confidence_threshold": 0.72, "max_steps": 30},
    "permissions": {"browser": True, "filesystem_read": True, "filesystem_write": False, "shell": "allowlist"},
}


def test_defaults_written_when_missing(tmp_path):
    path = tmp_path / "config.json"
    cfg = C.load_config(path)
    assert path.exists()
    assert cfg.asr.engine == "whisper" and cfg.input.ptt_key == "right ctrl"


def test_legacy_flat_config_is_migrated(tmp_path):
    import pasta.settings  # noqa: F401  (registers agent/permissions sections)

    path = tmp_path / "config.json"
    path.write_text(json.dumps(LEGACY_PASTA_V2), encoding="utf-8")
    cfg = C.load_config(path)
    assert cfg.asr.engine == "parakeet"
    assert cfg.asr.language == "el"
    assert cfg.input.ptt_key == "right alt"
    assert cfg.ui.sounds is False
    assert cfg.asr.whisper_compute_type == "float16"
    assert cfg.audio.max_utterance_s == 90
    assert cfg.agent.auto_threshold == 0.72  # renamed key
    assert cfg.agent.max_steps == 6  # clamped from 30
    assert cfg.permissions.files is True and cfg.permissions.shell == "allowlist"


def test_invalid_values_fall_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"asr": {"engine": "gpt", "language": "fr", "whisper_beam_size": "two"},
                                "input": {"mode": "telepathy", "hold_threshold_ms": 99999}}), encoding="utf-8")
    cfg = C.load_config(path)
    assert cfg.asr.engine == "whisper" and cfg.asr.language == "auto"
    assert cfg.asr.whisper_beam_size == C.AsrSettings().whisper_beam_size
    assert cfg.input.mode == "ptt" and cfg.input.hold_threshold_ms == 1000


def test_unknown_sections_survive_a_save(tmp_path):
    """Running plain PESTO must not delete PASTA's settings."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"asr": {"engine": "whisper"}, "someplugin": {"x": 1}}), encoding="utf-8")
    cfg = C.load_config(path)
    cfg.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["someplugin"] == {"x": 1}


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = C.load_config(path)
    cfg.experiment.added_latency_ms = 500
    cfg.ui.live_preview = False
    cfg.save()
    again = C.load_config(path)
    assert again.experiment.added_latency_ms == 500 and again.ui.live_preview is False


def test_late_registered_section_reads_raw_values(tmp_path):
    @dataclass
    class Demo:
        level: int = 1

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"demo_late": {"level": 7}}), encoding="utf-8")
    cfg = C.load_config(path)
    C.register_section("demo_late", Demo)
    try:
        assert cfg.demo_late.level == 7
    finally:
        C._EXTENSION_SECTIONS.pop("demo_late")
