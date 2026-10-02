from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RouteType(str, Enum):
    TEXT = "TEXT"
    AGENT = "AGENT"
    AMBIGUOUS = "AMBIGUOUS"


class RiskLevel(str, Enum):
    READ = "READ"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    DESTRUCTIVE = "DESTRUCTIVE"


@dataclass
class WindowState:
    hwnd: int
    title: str
    process_name: str = ""
    pid: int = 0
    is_minimized: bool = False
    is_maximized: bool = False
    is_foreground: bool = False
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom


@dataclass
class ApplicationState:
    name: str
    is_running: bool = False
    pids: list[int] = field(default_factory=list)
    exe_path: str = ""
    main_hwnd: int = 0


@dataclass
class BrowserState:
    is_active: bool = False
    title: str = ""
    url: str = ""
    tab_count: int = 1
    active_tab_index: int = 0
    visible_text_snippet: str = ""
    headings: list[str] = field(default_factory=list)
    interactive_elements: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ClipboardState:
    text: str = ""
    has_text: bool = False


@dataclass
class TaskState:
    goal: str
    current_step: int = 0
    max_steps: int = 30
    step_history: list[str] = field(default_factory=list)
    is_complete: bool = False
    is_cancelled: bool = False
    failure_count: int = 0


@dataclass
class ComputerState:
    timestamp: float
    foreground_window: WindowState | None = None
    windows: list[WindowState] = field(default_factory=list)
    applications: list[ApplicationState] = field(default_factory=list)
    browser: BrowserState | None = None
    clipboard: ClipboardState | None = None
    task: TaskState | None = None

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "foreground_app": self.foreground_window.process_name if self.foreground_window else "Unknown",
            "foreground_title": self.foreground_window.title if self.foreground_window else "",
            "browser_url": self.browser.url if (self.browser and self.browser.is_active) else "",
            "browser_title": self.browser.title if (self.browser and self.browser.is_active) else "",
            "open_windows_count": len(self.windows),
            "goal": self.task.goal if self.task else "",
            "current_step": self.task.current_step if self.task else 0,
        }


@dataclass
class ActionResult:
    success: bool
    changed_state: bool
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True


@dataclass
class AgentAction:
    id: str
    description: str
    category: str
    risk: RiskLevel = RiskLevel.LOW
    execute: Callable[[], ActionResult] = field(default=lambda: ActionResult(True, True, "Executed"))
    verify: Callable[[], ActionResult] = field(default=lambda: ActionResult(True, True, "Verified"))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    action_id: str
    probability: float
    confidence: float
    raw_scores: dict[str, float] = field(default_factory=dict)
    question: str = ""
