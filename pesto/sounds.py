"""Short, soft earcons rendered once to WAV and played asynchronously.

The old ``winsound.Beep`` drives the legacy PC-speaker path: harsh square
tones, and it blocks a thread for the tone's duration. These are 40-90 ms
sine tones with smooth envelopes, mixed by the normal audio stack.
"""

from __future__ import annotations

import sys
import wave

import numpy as np

from . import paths

SR = 22050
_TONES = {
    "start": [(660, 0.045), (880, 0.055)],
    "done": [(988, 0.06)],
    "command": [(740, 0.045), (988, 0.06)],
    "error": [(330, 0.09), (262, 0.11)],
    "cancel": [(587, 0.05), (440, 0.07)],
    "confirm": [(880, 0.05), (880, 0.05)],
}


def _render(path, notes) -> None:
    parts = []
    for freq, dur in notes:
        n = int(SR * dur)
        t = np.arange(n) / SR
        env = np.sin(np.pi * np.minimum(1.0, t / dur)) ** 2  # raised-cosine envelope, no clicks
        parts.append(0.22 * env * np.sin(2 * np.pi * freq * t))
        parts.append(np.zeros(int(SR * 0.012)))
    pcm = (np.concatenate(parts) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


class Sounds:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and sys.platform == "win32"
        self._dir = paths.CACHE_DIR / "sounds"
        if self.enabled:
            self._dir.mkdir(parents=True, exist_ok=True)
            for name, notes in _TONES.items():
                p = self._dir / f"{name}.wav"
                if not p.exists():
                    _render(p, notes)

    def play(self, name: str) -> None:
        if not self.enabled or name not in _TONES:
            return
        import winsound

        try:
            winsound.PlaySound(str(self._dir / f"{name}.wav"),
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except RuntimeError:
            pass
