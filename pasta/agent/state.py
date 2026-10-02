import time

import pyperclip

from .schemas import ClipboardState, ComputerState, TaskState
from .observers.browser import BrowserObserver
from .observers.screen import ScreenObserver
from .observers.windows import WindowsObserver


class StateObserver:
    """Unified state observer aggregating structured Windows OS, browser,

    and system state.
    """

    def __init__(self, browser_manager=None) -> None:
        self.windows_obs = WindowsObserver()
        self.browser_obs = BrowserObserver(browser_manager)
        self.screen_obs = ScreenObserver()

    def observe(self, task: TaskState | None = None) -> ComputerState:
        now = time.time()

        # 1. Foreground window
        fg_window = self.windows_obs.get_foreground_window()

        # 2. Visible top-level windows
        visible_windows = self.windows_obs.get_visible_windows()

        # 3. Running processes
        apps = self.windows_obs.get_running_applications()

        # 4. Browser DOM state
        browser_state = self.browser_obs.observe()

        # 5. Clipboard state
        clip_text = ""
        try:
            clip_text = pyperclip.paste() or ""
        except Exception:
            pass
        clip_state = ClipboardState(text=clip_text[:500], has_text=bool(clip_text.strip()))

        return ComputerState(
            timestamp=now,
            foreground_window=fg_window,
            windows=visible_windows,
            applications=apps,
            browser=browser_state,
            clipboard=clip_state,
            task=task,
        )
