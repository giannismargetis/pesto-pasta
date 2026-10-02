import threading

from .config import Config
from .logging_setup import get_logger

log = get_logger("hotkeys")

_SIDE_KEYS = {
    "ctrl": {
        "left": {"left ctrl", "left control", "ctrl", "control"},
        "right": {"right ctrl", "right control"},
        "all": {"ctrl", "control", "left ctrl", "left control", "right ctrl", "right control"},
    },
    "shift": {
        "left": {"left shift", "shift"},
        "right": {"right shift"},
        "all": {"shift", "left shift", "right shift"},
    },
    "alt": {
        "left": {"left alt", "alt"},
        "right": {"right alt", "alt gr"},
        "all": {"alt", "left alt", "right alt", "alt gr"},
    },
}


def _matching_names(hotkey: str) -> set[str]:
    target = hotkey.strip().lower()
    for base, variants in _SIDE_KEYS.items():
        alt_base = "control" if base == "ctrl" else base
        if target in (f"right {base}", f"right {alt_base}", f"r{base}", f"r_{base}"):
            return set(variants["right"])
        if target in (f"left {base}", f"left {alt_base}", f"l{base}", f"l_{base}"):
            return set(variants["left"])
        if target in (base, alt_base):
            return set(variants["all"])
    return {target}


class HotkeyListener(threading.Thread):
    def __init__(
        self,
        cfg: Config,
        on_ptt_down,
        on_ptt_up,
        on_toggle_language,
        on_toggle_engine,
        on_cancel=None,
        on_toggle_mode=None,
    ) -> None:
        super().__init__(name="Hotkeys", daemon=True)
        self.cfg = cfg
        self.callbacks = (on_ptt_down, on_ptt_up, on_toggle_language, on_toggle_engine, on_cancel, on_toggle_mode)
        self.shutdown = threading.Event()

    def run(self) -> None:
        import time as _time

        import keyboard

        ptt_down, ptt_up, toggle_lang, toggle_engine, cancel_cb, toggle_mode_cb = self.callbacks
        ptt_names = _matching_names(self.cfg.hotkey)
        raw_key = self.cfg.hotkey.strip().lower()

        try:
            target_scan_codes = set(keyboard.key_to_scan_codes(raw_key))
        except Exception:
            target_scan_codes = set()

        pressed = False
        pressed_lock = threading.Lock()

        def do_press(event=None):
            nonlocal pressed
            with pressed_lock:
                if not pressed:
                    pressed = True
                    ptt_down()

        def do_release(event=None):
            nonlocal pressed
            with pressed_lock:
                if pressed:
                    pressed = False
                    ptt_up()

        def is_ptt(event) -> bool:
            if not event:
                return False
            name = (event.name or "").lower()
            if name in ptt_names:
                return True
            if event.scan_code in target_scan_codes:
                if "right" in raw_key and event.scan_code == 29:
                    return False
                return True
            return False

        def handle_event(event):
            if is_ptt(event):
                if event.event_type == keyboard.KEY_DOWN:
                    do_press(event)
                elif event.event_type == keyboard.KEY_UP:
                    do_release(event)

        for name in sorted(ptt_names):
            try:
                keyboard.on_press_key(name, do_press, suppress=False)
                keyboard.on_release_key(name, do_release, suppress=False)
            except Exception:
                pass

        try:
            keyboard.hook(handle_event, suppress=False)
        except Exception as exc:
            log.warning("Keyboard hook failed: %s", exc)

        if self.cfg.toggle_lang_key:
            try:
                keyboard.add_hotkey(self.cfg.toggle_lang_key, toggle_lang, suppress=False)
            except Exception:
                pass

        if self.cfg.toggle_engine_key:
            try:
                keyboard.add_hotkey(self.cfg.toggle_engine_key, toggle_engine, suppress=False)
            except Exception:
                pass

        # Mode toggle hotkey (Dictation vs Agent vs Auto)
        toggle_mode_key = getattr(self.cfg, "toggle_mode_key", "f10") or "f10"
        if toggle_mode_key and toggle_mode_cb:
            try:
                keyboard.add_hotkey(toggle_mode_key, toggle_mode_cb, suppress=False)
                log.info("Registered mode toggle hotkey: %s", toggle_mode_key)
            except Exception as exc:
                log.warning("Failed to register mode toggle hotkey: %s", exc)

        # Esc hotkey for cancelling running agent actions
        cancel_key = getattr(self.cfg, "cancel_key", "esc") or "esc"
        if cancel_key and cancel_cb:
            try:
                keyboard.add_hotkey(cancel_key, cancel_cb, suppress=False)
                log.info("Registered agent cancellation hotkey: %s", cancel_key)
            except Exception as exc:
                log.warning("Failed to register cancel hotkey: %s", exc)

        log.info(
            "Hotkeys initialized (PTT='%s', Mode='%s', Lang='%s', Engine='%s', Cancel='%s')",
            self.cfg.hotkey,
            toggle_mode_key,
            self.cfg.toggle_lang_key,
            self.cfg.toggle_engine_key,
            cancel_key,
        )

        while not self.shutdown.is_set():
            _time.sleep(0.2)

        try:
            keyboard.unhook_all()
        except Exception:
            pass
