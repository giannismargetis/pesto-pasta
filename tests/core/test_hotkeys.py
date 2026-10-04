import time

import pytest

from pesto.hotkeys import Combo, KeyEvent, PushToTalk, key_vks

RCTRL, LCTRL, C_KEY, ESC, SHIFT = 0xA3, 0xA2, 0x43, 0x1B, 0xA0


def machine(hold=0.05):
    events = []
    ptt = PushToTalk({RCTRL}, {ESC}, hold, lambda name, t: events.append(name))
    return ptt, events


def key(vk, down=True):
    return KeyEvent(vk, down, time.perf_counter())


def test_key_names_are_layout_independent_vk_codes():
    assert key_vks("right ctrl") == {0xA3}
    assert key_vks("Right Control") == {0xA3}
    assert key_vks("ctrl") == {0xA2, 0xA3}
    assert key_vks("F9") == {0x78}
    assert key_vks("l") == {ord("L")}
    with pytest.raises(ValueError):
        key_vks("δεξί ctrl")


def test_combo_parse():
    c = Combo.parse("ctrl+alt+shift+l")
    assert c.modifiers == frozenset({"ctrl", "alt", "shift"}) and c.key == frozenset({ord("L")})
    with pytest.raises(ValueError):
        Combo.parse("hyper+x")


def test_hold_then_release_is_dictation():
    ptt, ev = machine()
    ptt.on_key(key(RCTRL))
    time.sleep(0.09)
    ptt.on_key(key(RCTRL, False))
    assert ev == ["press", "confirm", "release"]


def test_short_tap_is_discarded_without_feedback():
    ptt, ev = machine(hold=0.2)
    ptt.on_key(key(RCTRL))
    ptt.on_key(key(RCTRL, False))
    time.sleep(0.25)  # the confirm timer must not fire after release
    assert ev == ["press", "tap"]


def test_shortcut_chord_cancels_recording():
    """Right Ctrl + C is a copy shortcut, not dictation."""
    ptt, ev = machine(hold=0.01)
    ptt.on_key(key(RCTRL))
    time.sleep(0.03)
    ptt.on_key(key(C_KEY))
    ptt.on_key(key(C_KEY, False))
    ptt.on_key(key(RCTRL, False))
    assert ev == ["press", "confirm", "chord"]


def test_extra_modifier_is_also_a_chord():
    ptt, ev = machine(hold=0.2)
    ptt.on_key(key(RCTRL))
    ptt.on_key(key(SHIFT))
    ptt.on_key(key(RCTRL, False))
    assert ev == ["press", "chord"]


def test_autorepeat_does_not_restart():
    ptt, ev = machine(hold=0.01)
    for _ in range(5):
        ptt.on_key(key(RCTRL))
    time.sleep(0.03)
    ptt.on_key(key(RCTRL, False))
    assert ev == ["press", "confirm", "release"]


def test_escape_cancels_recording_and_is_reported_when_idle():
    ptt, ev = machine(hold=0.01)
    ptt.on_key(key(ESC))
    assert ev == ["escape"]
    ptt.on_key(key(RCTRL))
    time.sleep(0.03)
    ptt.on_key(key(ESC))
    ptt.on_key(key(RCTRL, False))
    assert ev == ["escape", "press", "confirm", "cancel"]


def test_other_keys_while_idle_are_ignored():
    ptt, ev = machine()
    for vk in (C_KEY, LCTRL, SHIFT):
        ptt.on_key(key(vk))
        ptt.on_key(key(vk, False))
    assert ev == []
