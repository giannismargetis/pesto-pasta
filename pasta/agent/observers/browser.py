from ...logging_setup import get_logger
from ..schemas import BrowserState

log = get_logger("observer.browser")


class BrowserObserver:
    """Observer for web browser state and DOM structures via Playwright."""

    def __init__(self, browser_manager=None) -> None:
        self.browser_manager = browser_manager

    def observe(self) -> BrowserState:
        if not self.browser_manager:
            return BrowserState(is_active=False)

        try:
            return self.browser_manager.observe_state()
        except Exception as exc:
            log.debug("Browser observation failed: %s", exc)
            return BrowserState(is_active=False)
