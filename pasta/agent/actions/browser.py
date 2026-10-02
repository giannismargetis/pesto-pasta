import threading
import time
from typing import Any
import urllib.parse
import webbrowser

from ...logging_setup import get_logger
from ..schemas import ActionResult
from .base import failure_result, success_result

log = get_logger("action.browser")


class BrowserManager:
    """Manages active Playwright browser sessions for real-time web automation."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._active_page = None
        self._pages = []
        self._headless = False

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = BrowserManager()
            return cls._instance

    def is_active(self) -> bool:
        return self._active_page is not None and not self._active_page.is_closed()

    def get_active_page(self):
        return self._active_page

    def get_all_pages(self):
        return self._pages

    def _ensure_browser(self):
        if self._browser and self._context and self._active_page and not self._active_page.is_closed():
            return self._active_page

        try:
            from playwright.sync_api import sync_playwright

            if not self._playwright:
                self._playwright = sync_playwright().start()

            if not self._browser:
                self._browser = self._playwright.chromium.launch(
                    headless=self._headless,
                    args=["--start-maximized"],
                )

            if not self._context:
                self._context = self._browser.new_context(no_viewport=True)

            pages = self._context.pages
            if pages:
                self._active_page = pages[-1]
            else:
                self._active_page = self._context.new_page()

            self._pages = self._context.pages
            return self._active_page
        except Exception as exc:
            log.warning("Playwright initialization failed: %s", exc)
            return None

    def open_url(self, url: str) -> ActionResult:
        """Capability 6: Open URL in browser."""
        target_url = url.strip()
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "https://" + target_url

        page = self._ensure_browser()
        if page:
            try:
                page.goto(target_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(0.5)
                return success_result(
                    f"Navigated to {target_url}",
                    evidence={"url": page.url, "title": page.title()},
                )
            except Exception as exc:
                log.warning("Playwright navigation failed (%s), opening via system default browser", exc)

        # Fallback to system default browser
        webbrowser.open(target_url)
        return success_result(f"Opened {target_url} in default browser", evidence={"url": target_url})

    def search_web(self, query: str) -> ActionResult:
        """Capability 9: Search the web."""
        clean_q = query.strip()
        encoded = urllib.parse.quote_plus(clean_q)
        search_url = f"https://www.google.com/search?q={encoded}"
        page = self._ensure_browser()
        if page:
            try:
                page.goto(search_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(0.5)
                return success_result(
                    f"Searched web for: '{clean_q}'",
                    evidence={"query": clean_q, "url": page.url, "title": page.title()},
                )
            except Exception as exc:
                log.warning("Playwright search navigation failed: %s", exc)

        webbrowser.open(search_url)
        return success_result(f"Opened web search for '{clean_q}'", evidence={"query": clean_q})

    def new_tab(self, url: str = "about:blank") -> ActionResult:
        """Capability 7: Create a new browser tab."""
        self._ensure_browser()
        if self._context:
            try:
                page = self._context.new_page()
                self._active_page = page
                self._pages = self._context.pages
                if url and url != "about:blank":
                    if not url.startswith("http"):
                        url = "https://" + url
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                return success_result("Created new browser tab", evidence={"tab_count": len(self._pages)})
            except Exception as exc:
                return failure_result(f"Failed to create new tab: {exc}")
        return failure_result("Browser not active")

    def close_tab(self) -> ActionResult:
        """Capability 8: Close current browser tab."""
        if self._active_page:
            try:
                self._active_page.close()
                pages = self._context.pages if self._context else []
                self._active_page = pages[-1] if pages else None
                self._pages = pages
                return success_result("Closed browser tab", evidence={"remaining_tabs": len(pages)})
            except Exception as exc:
                return failure_result(f"Failed to close tab: {exc}")
        return failure_result("No active browser tab to close")

    def navigate_back(self) -> ActionResult:
        """Capability 10a: Go back."""
        if self._active_page:
            try:
                self._active_page.go_back(timeout=5000)
                return success_result("Navigated back", evidence={"url": self._active_page.url})
            except Exception as exc:
                return failure_result(f"Failed to go back: {exc}")
        return failure_result("No active browser page")

    def navigate_forward(self) -> ActionResult:
        """Capability 10b: Go forward."""
        if self._active_page:
            try:
                self._active_page.go_forward(timeout=5000)
                return success_result("Navigated forward", evidence={"url": self._active_page.url})
            except Exception as exc:
                return failure_result(f"Failed to go forward: {exc}")
        return failure_result("No active browser page")

    def reload(self) -> ActionResult:
        """Capability 10c: Reload page."""
        if self._active_page:
            try:
                self._active_page.reload(timeout=10000)
                return success_result("Reloaded page", evidence={"url": self._active_page.url})
            except Exception as exc:
                return failure_result(f"Failed to reload page: {exc}")
        return failure_result("No active browser page")

    def scroll(self, direction: str = "down", amount: int = 500) -> ActionResult:
        """Capability 10d: Scroll page."""
        if self._active_page:
            try:
                delta = amount if direction == "down" else -amount
                self._active_page.evaluate(f"window.scrollBy(0, {delta})")
                return success_result(f"Scrolled {direction} by {amount}px")
            except Exception as exc:
                return failure_result(f"Failed to scroll: {exc}")
        return failure_result("No active browser page")

    def click_element(self, target: str) -> ActionResult:
        """Capability 11: Click a web element using DOM locators."""
        if not self._active_page:
            return failure_result("No active browser page to click element")

        clean = target.strip()
        locators_to_try = [
            f"text={clean}",
            f"button:has-text('{clean}')",
            f"a:has-text('{clean}')",
            clean,  # in case it's a CSS selector
        ]

        for loc in locators_to_try:
            try:
                el = self._active_page.locator(loc).first
                if el.is_visible(timeout=1500):
                    el.click(timeout=3000)
                    return success_result(f"Clicked element matching '{target}'", evidence={"locator": loc})
            except Exception:
                continue

        return failure_result(f"Could not find or click element '{target}'")

    def type_and_submit(self, text: str, selector: str | None = None, press_enter: bool = True) -> ActionResult:
        """Capability 12: Type into a web field and optionally submit."""
        if not self._active_page:
            return failure_result("No active browser page to type into")

        try:
            if selector:
                field = self._active_page.locator(selector).first
            else:
                # Find the first visible text input or focused input
                field = self._active_page.locator("input[type='text'], input[type='search'], input:not([type]), textarea").first

            if field.is_visible(timeout=2000):
                field.fill(text)
                if press_enter:
                    field.press("Enter")
                return success_result(f"Typed '{text}' and submitted", evidence={"text": text})
        except Exception as exc:
            return failure_result(f"Failed to type and submit: {exc}")

        return failure_result("No suitable input field found on page")

    def read_structured_info(self) -> ActionResult:
        """Capability 13: Read structured browser information."""
        if not self._active_page:
            return failure_result("No active browser page")

        try:
            title = self._active_page.title()
            url = self._active_page.url
            headings = [h.strip() for h in self._active_page.locator("h1, h2, h3").all_inner_texts() if h.strip()][:5]
            snippet = " ".join((self._active_page.locator("body").inner_text() or "").split()[:60])

            return success_result(
                f"Page title: {title}",
                evidence={
                    "title": title,
                    "url": url,
                    "headings": headings,
                    "snippet": snippet,
                },
            )
        except Exception as exc:
            return failure_result(f"Failed to read browser info: {exc}")


def get_browser_manager() -> BrowserManager:
    return BrowserManager.get_instance()
