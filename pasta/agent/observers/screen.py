import ctypes
import time
from pathlib import Path
from typing import Any

from PIL import ImageGrab

from ...config import CACHE_DIR
from ...logging_setup import get_logger

log = get_logger("observer.screen")


class ScreenObserver:
    """Fallback visual observer for window screenshots and desktop bounds."""

    def __init__(self) -> None:
        self.shots_dir = CACHE_DIR / "screenshots"
        self.shots_dir.mkdir(parents=True, exist_ok=True)

    def get_screen_resolution(self) -> tuple[int, int]:
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return (w, h)

    def capture_fullscreen(self) -> Path | None:
        try:
            img = ImageGrab.grab()
            filename = f"screen_{int(time.time() * 1000)}.png"
            path = self.shots_dir / filename
            img.save(path)
            log.debug("Captured screen: %s", path)
            return path
        except Exception as exc:
            log.warning("Screen capture failed: %s", exc)
            return None

    def capture_window(self, bbox: tuple[int, int, int, int]) -> Path | None:
        try:
            # bbox: (left, top, right, bottom)
            img = ImageGrab.grab(bbox=bbox)
            filename = f"win_{int(time.time() * 1000)}.png"
            path = self.shots_dir / filename
            img.save(path)
            return path
        except Exception as exc:
            log.warning("Window capture failed: %s", exc)
            return None
