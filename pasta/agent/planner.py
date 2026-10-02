from typing import Any

from .schemas import ActionResult, AgentAction, ComputerState, TaskState


class TaskPlanner:
    """Manages task lifecycle, progression, step boundaries, and termination checks."""

    def __init__(self, max_steps: int = 30) -> None:
        self.max_steps = max_steps

    def create_task(self, goal: str) -> TaskState:
        return TaskState(
            goal=goal,
            current_step=0,
            max_steps=self.max_steps,
            step_history=[],
            is_complete=False,
            is_cancelled=False,
            failure_count=0,
        )

    def is_task_complete(self, task: TaskState, action: AgentAction, result: ActionResult) -> bool:
        if task.is_cancelled:
            return True

        if action.id == "stop":
            return True

        # Single-intent actions usually complete upon successful execution and verification
        # e.g. launch application, open URL, mute, press enter, copy/paste, run git status
        single_step_actions = {
            "launch_chrome",
            "launch_calculator",
            "launch_notepad",
            "launch_vscode",
            "focus_chrome",
            "focus_vscode",
            "open_downloads",
            "find_file",
            "search_web",
            "open_url",
            "type_text",
            "press_enter",
            "copy_selection",
            "paste_clipboard",
            "run_git_status",
            "run_python_version",
            "toggle_mute",
            "minimize_active_window",
            "inspect_open_windows",
            "scroll_down",
            "scroll_up",
            "new_browser_tab",
            "close_browser_tab",
            "browser_back",
        }

        if action.id in single_step_actions and result.success:
            return True

        if task.current_step >= task.max_steps:
            return True

        return False
