import json
from unittest.mock import patch
import pytest

from pesto.audio import Microphone, list_input_devices, resolve_input_device
from pesto.config import AudioSettings, load_config


MOCK_HOSTAPIS = (
    {"name": "MME"},
    {"name": "Windows DirectSound"},
    {"name": "Windows WASAPI"},
    {"name": "Windows WDM-KS"},
)

MOCK_DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100.0},
    {"name": "Microphone (Razer Barracuda X)", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100.0},
    {"name": "Microphone (Razer Barracuda X)", "hostapi": 2, "max_input_channels": 2, "default_samplerate": 48000.0},
    {"name": "Microphone (Razer Barracuda X)", "hostapi": 3, "max_input_channels": 2, "default_samplerate": 48000.0},
    {"name": "Stereo Mix (Realtek Audio)", "hostapi": 2, "max_input_channels": 2, "default_samplerate": 48000.0},
    {"name": "Speakers (Realtek Audio)", "hostapi": 2, "max_input_channels": 0, "default_samplerate": 48000.0},
]


def test_list_input_devices():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOSTAPIS), \
         patch("sounddevice.default.device", [1, 5]):
        devs = list_input_devices()
        assert len(devs) == 5  # Only input devices
        assert devs[0]["name"] == "Microsoft Sound Mapper - Input"
        assert devs[1]["name"] == "Microphone (Razer Barracuda X)"
        assert devs[1]["hostapi"] == "MME"
        assert devs[1]["default"] is True
        assert devs[2]["hostapi"] == "Windows WASAPI"
        assert devs[2]["full_name"] == "Microphone (Razer Barracuda X) [Windows WASAPI]"


def test_resolve_input_device_default():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOSTAPIS), \
         patch("sounddevice.default.device", [2, 5]):
        idx, info = resolve_input_device("")
        assert idx == 2
        assert info["hostapi"] == 2


def test_resolve_input_device_prefers_wasapi():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOSTAPIS):
        # Specifying just the device name without hostapi should rank WASAPI (hostapi 2) above MME (0) and WDM-KS (3)
        idx, info = resolve_input_device("Microphone (Razer Barracuda X)")
        assert idx == 2
        assert info["hostapi"] == 2


def test_resolve_input_device_exact_bracket():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOSTAPIS):
        idx, info = resolve_input_device("Microphone (Razer Barracuda X) [MME]")
        assert idx == 1
        assert info["hostapi"] == 0


def test_resolve_input_device_by_index():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOSTAPIS):
        idx, info = resolve_input_device("3")
        assert idx == 3
        assert info["hostapi"] == 3


def test_resolve_input_device_not_found():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOSTAPIS), \
         pytest.raises(RuntimeError, match="Selected microphone 'NonExistent' is not connected"):
        resolve_input_device("NonExistent")


def test_resolve_input_device_stereo_mix_rejected_as_default():
    devices = [
        {"name": "Stereo Mix (Realtek)", "hostapi": 2, "max_input_channels": 2, "default_samplerate": 48000.0}
    ]
    with patch("sounddevice.query_devices", return_value=devices), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOSTAPIS), \
         patch("sounddevice.default.device", [0, -1]), \
         pytest.raises(RuntimeError, match="Stereo Mix"):
        resolve_input_device("")


def test_microphone_switch_device():
    s = AudioSettings(device="old_mic")
    mic = Microphone(s)
    with patch.object(mic, "ensure_open", return_value=True) as mock_open:
        ok = mic.switch_device("new_mic")
        assert ok is True
        assert mic.s.device == "new_mic"
        mock_open.assert_called_once()


def test_audio_device_persists_across_sessions(tmp_path):
    path = tmp_path / "config.json"
    cfg = load_config(path)
    assert cfg.audio.device == ""

    cfg.audio.device = "Microphone (Razer Barracuda X) [Windows WASAPI]"
    cfg.save()

    cfg2 = load_config(path)
    assert cfg2.audio.device == "Microphone (Razer Barracuda X) [Windows WASAPI]"


def test_legacy_audio_device_migrated(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"input_device": "Razer Headset"}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.audio.device == "Razer Headset"


def test_microphone_is_open_safe_on_invalid_stream_pointer():
    s = AudioSettings()
    mic = Microphone(s)

    class BrokenStream:
        @property
        def active(self):
            import sounddevice as sd
            raise sd.PortAudioError("Invalid stream pointer", -9988)

    mic._stream = BrokenStream()
    # is_open must catch PortAudioError and return False rather than crashing
    assert mic.is_open is False

    # Also when error is already set, is_open must be False immediately
    mic.error = "microphone disconnected"
    assert mic.is_open is False

