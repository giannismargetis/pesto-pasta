from .app import find_and_open_file, launch_application, open_file_or_folder
from .browser import BrowserManager, get_browser_manager
from .keyboard import copy_selection, paste_clipboard, press_hotkey, select_all, type_dictated_text
from .mouse import scroll_active_window
from .shell import run_safe_terminal_command, toggle_mute, volume_down, volume_up
from .windows import close_window, focus_window, maximize_window, minimize_window, restore_window

__all__ = [
    "launch_application",
    "focus_window",
    "minimize_window",
    "maximize_window",
    "restore_window",
    "close_window",
    "open_file_or_folder",
    "find_and_open_file",
    "BrowserManager",
    "get_browser_manager",
    "type_dictated_text",
    "press_hotkey",
    "copy_selection",
    "paste_clipboard",
    "select_all",
    "scroll_active_window",
    "run_safe_terminal_command",
    "toggle_mute",
    "volume_up",
    "volume_down",
]
