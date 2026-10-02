from dataclasses import dataclass
from typing import Any


@dataclass
class BenchmarkTask:
    id: str
    category: str
    transcript: str
    expected_route: str  # "AGENT" or "TEXT"
    expected_top_action: str
    is_safe: bool = True
    metadata: dict[str, Any] = None


BENCHMARK_TASKS: list[BenchmarkTask] = [
    # --- 1. Windows Application Control (10 tasks) ---
    BenchmarkTask("win-01", "windows", "Pasta, open Calculator.", "AGENT", "launch_calculator"),
    BenchmarkTask("win-02", "windows", "Pasta, open Notepad.", "AGENT", "launch_notepad"),
    BenchmarkTask("win-03", "windows", "Pasta, open VS Code.", "AGENT", "launch_vscode"),
    BenchmarkTask("win-04", "windows", "Pasta, switch to VS Code.", "AGENT", "focus_vscode"),
    BenchmarkTask("win-05", "windows", "Pasta, minimize active window.", "AGENT", "minimize_active_window"),
    BenchmarkTask("win-06", "windows", "Pasta, what is currently open?", "AGENT", "inspect_open_windows"),
    BenchmarkTask("win-07", "windows", "Pasta, open Chrome.", "AGENT", "launch_chrome"),
    BenchmarkTask("win-08", "windows", "Computer, switch to Chrome.", "AGENT", "focus_chrome"),
    BenchmarkTask("win-09", "windows", "Pasta, open calc.", "AGENT", "launch_calculator"),
    BenchmarkTask("win-10", "windows", "Pasta, launch notepad.", "AGENT", "launch_notepad"),

    # --- 2. Browser Automation (12 tasks) ---
    BenchmarkTask("browser-01", "browser", "Pasta, search for RTX 5090 prices.", "AGENT", "search_web"),
    BenchmarkTask("browser-02", "browser", "Pasta, open github.com.", "AGENT", "open_url"),
    BenchmarkTask("browser-03", "browser", "Pasta, open python.org.", "AGENT", "open_url"),
    BenchmarkTask("browser-04", "browser", "Pasta, create a new browser tab.", "AGENT", "new_browser_tab"),
    BenchmarkTask("browser-05", "browser", "Pasta, close this tab.", "AGENT", "close_browser_tab"),
    BenchmarkTask("browser-06", "browser", "Pasta, go back.", "AGENT", "browser_back"),
    BenchmarkTask("browser-07", "browser", "Pasta, search for Python documentation.", "AGENT", "search_web"),
    BenchmarkTask("browser-08", "browser", "Pasta, open google.com.", "AGENT", "open_url"),
    BenchmarkTask("browser-09", "browser", "Pasta, search for local weather.", "AGENT", "search_web"),
    BenchmarkTask("browser-10", "browser", "Pasta, new tab.", "AGENT", "new_browser_tab"),
    BenchmarkTask("browser-11", "browser", "Pasta, open huggingface.co.", "AGENT", "open_url"),
    BenchmarkTask("browser-12", "browser", "Pasta, search for PyTorch installation.", "AGENT", "search_web"),

    # --- 3. Keyboard & Input (10 tasks) ---
    BenchmarkTask("kb-01", "keyboard", "Pasta, press Enter.", "AGENT", "press_enter"),
    BenchmarkTask("kb-02", "keyboard", "Pasta, copy this.", "AGENT", "copy_selection"),
    BenchmarkTask("kb-03", "keyboard", "Pasta, paste it here.", "AGENT", "paste_clipboard"),
    BenchmarkTask("kb-04", "keyboard", "Pasta, type hello world.", "AGENT", "type_text"),
    BenchmarkTask("kb-05", "keyboard", "Pasta, scroll down.", "AGENT", "scroll_down"),
    BenchmarkTask("kb-06", "keyboard", "Pasta, scroll up.", "AGENT", "scroll_up"),
    BenchmarkTask("kb-07", "keyboard", "Pasta, type good morning.", "AGENT", "type_text"),
    BenchmarkTask("kb-08", "keyboard", "Pasta, copy selection.", "AGENT", "copy_selection"),
    BenchmarkTask("kb-09", "keyboard", "Pasta, paste.", "AGENT", "paste_clipboard"),
    BenchmarkTask("kb-10", "keyboard", "Pasta, press enter key.", "AGENT", "press_enter"),

    # --- 4. Filesystem (6 tasks) ---
    BenchmarkTask("fs-01", "filesystem", "Pasta, open Downloads.", "AGENT", "open_downloads"),
    BenchmarkTask("fs-02", "filesystem", "Pasta, find my PDF named diploma.", "AGENT", "find_file"),
    BenchmarkTask("fs-03", "filesystem", "Pasta, open my Downloads folder.", "AGENT", "open_downloads"),
    BenchmarkTask("fs-04", "filesystem", "Pasta, find file thesis.", "AGENT", "find_file"),
    BenchmarkTask("fs-05", "filesystem", "Pasta, open Downloads directory.", "AGENT", "open_downloads"),
    BenchmarkTask("fs-06", "filesystem", "Pasta, find notes.txt.", "AGENT", "find_file"),

    # --- 5. Terminal & System Tools (6 tasks) ---
    BenchmarkTask("sys-01", "system", "Pasta, run git status in the terminal.", "AGENT", "run_git_status"),
    BenchmarkTask("sys-02", "system", "Pasta, mute my computer.", "AGENT", "toggle_mute"),
    BenchmarkTask("sys-03", "system", "Pasta, mute sound.", "AGENT", "toggle_mute"),
    BenchmarkTask("sys-04", "system", "Pasta, run python --version.", "AGENT", "run_python_version"),
    BenchmarkTask("sys-05", "system", "Pasta, run git status.", "AGENT", "run_git_status"),
    BenchmarkTask("sys-06", "system", "Pasta, stop.", "AGENT", "stop"),

    # --- 6. Greek Natural Language Commands (8 tasks) ---
    BenchmarkTask("el-01", "greek", "Πάστα, άνοιξε το Chrome.", "AGENT", "launch_chrome"),
    BenchmarkTask("el-02", "greek", "Πάστα, ψάξε RTX 5090 τιμές.", "AGENT", "search_web"),
    BenchmarkTask("el-03", "greek", "Πάστα, άνοιξε το Calculator.", "AGENT", "launch_calculator"),
    BenchmarkTask("el-04", "greek", "Πάστα, πήγαινε στα Downloads.", "AGENT", "open_downloads"),
    BenchmarkTask("el-05", "greek", "Πάστα, βρες το PDF μου.", "AGENT", "find_file"),
    BenchmarkTask("el-06", "greek", "Πάστα, γύρνα πίσω.", "AGENT", "browser_back"),
    BenchmarkTask("el-07", "greek", "Πάστα, πάτα Enter.", "AGENT", "press_enter"),
    BenchmarkTask("el-08", "greek", "Πάστα, κάνε paste.", "AGENT", "paste_clipboard"),

    # --- 7. Normal Dictation Contrast (4 tasks) ---
    BenchmarkTask("dict-01", "dictation", "Καλησπέρα, αύριο θα σου στείλω το αρχείο με την παρουσίαση.", "TEXT", "text_dictation"),
    BenchmarkTask("dict-02", "dictation", "The project deadline has been moved to next Tuesday afternoon.", "TEXT", "text_dictation"),
    BenchmarkTask("dict-03", "dictation", "Please review the attached invoice and let me know if everything is accurate.", "TEXT", "text_dictation"),
    BenchmarkTask("dict-04", "dictation", "Ευχαριστώ πολύ για τη βοήθεια, τα λέμε αύριο στο γραφείο.", "TEXT", "text_dictation"),
]
