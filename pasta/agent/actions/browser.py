import queue
import threading
import time
from typing import Any
import urllib.parse
import webbrowser

from ...logging_setup import get_logger
from ..schemas import ActionResult, BrowserState
from .base import failure_result, success_result

log = get_logger("action.browser")


class BrowserManager:
    """Manages active Playwright browser sessions on a dedicated worker thread
    to guarantee 100% thread safety across async/threaded agent operations."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._task_queue = queue.Queue()
        self._playwright = None
        self._browser = None
        self._context = None
        self._active_page = None
        self._pages = []
        self._headless = False
        self._worker = threading.Thread(target=self._worker_loop, name="PlaywrightWorker", daemon=True)
        self._worker.start()

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = BrowserManager()
            return cls._instance

    def _worker_loop(self):
        while True:
            item = self._task_queue.get()
            if item is None:
                break
            fn, ret_queue = item
            try:
                res = fn()
                ret_queue.put((True, res))
            except Exception as exc:
                ret_queue.put((False, exc))

    def _run_sync(self, fn, timeout: float = 15.0):
        ret_queue = queue.Queue(maxsize=1)
        self._task_queue.put((fn, ret_queue))
        try:
            ok, val = ret_queue.get(timeout=timeout)
            if ok:
                return val
            log.warning("Playwright worker error: %s", val)
            return None
        except Exception as exc:
            log.debug("Playwright worker timeout or error: %s", exc)
            return None

    def _ensure_browser_internal(self):
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

    def is_active(self) -> bool:
        res = self._run_sync(lambda: self._active_page is not None and not self._active_page.is_closed(), timeout=1.0)
        return bool(res)

    def observe_state(self) -> BrowserState:
        def _do_observe():
            if not self._active_page or self._active_page.is_closed():
                return BrowserState(is_active=False)

            title = self._active_page.title() or ""
            url = self._active_page.url or ""
            headings = []
            try:
                h_elements = self._active_page.locator("h1, h2, h3").all_inner_texts()
                headings = [h.strip() for h in h_elements if h.strip()][:5]
            except Exception:
                pass

            snippet = ""
            try:
                body_text = self._active_page.locator("body").inner_text()
                snippet = " ".join(body_text.split()[:40])
            except Exception:
                pass

            interactive = []
            try:
                inputs = self._active_page.locator("input, button, a[href]").all()
                for el in inputs[:10]:
                    try:
                        tag = el.evaluate("e => e.tagName.toLowerCase()")
                        text = el.inner_text().strip() or el.get_attribute("placeholder") or el.get_attribute("aria-label") or ""
                        interactive.append({"tag": tag, "text": text})
                    except Exception:
                        pass
            except Exception:
                pass

            return BrowserState(
                is_active=True,
                active_url=url,
                active_title=title,
                headings=headings,
                visible_text_snippet=snippet,
                interactive_elements=interactive,
                tab_count=len(self._pages),
            )

        res = self._run_sync(_do_observe, timeout=3.0)
        return res if isinstance(res, BrowserState) else BrowserState(is_active=False)

    def open_url(self, url: str) -> ActionResult:
        """Capability 6: Open URL in browser."""
        target_url = url.strip()
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "https://" + target_url

        def _do_open():
            page = self._ensure_browser_internal()
            if page:
                page.goto(target_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(0.5)
                return success_result(
                    f"Navigated to {target_url}",
                    evidence={"url": page.url, "title": page.title()},
                )
            return None

        res = self._run_sync(_do_open, timeout=16.0)
        if isinstance(res, ActionResult):
            return res

        # Fallback to system default browser
        webbrowser.open(target_url)
        return success_result(f"Opened {target_url} in default browser", evidence={"url": target_url})

    def search_web(self, query: str) -> ActionResult:
        """Capability 9: Search the web."""
        clean_q = query.strip()
        encoded = urllib.parse.quote_plus(clean_q)
        search_url = f"https://www.google.com/search?q={encoded}"

        def _do_search():
            page = self._ensure_browser_internal()
            if page:
                page.goto(search_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(0.5)
                return success_result(
                    f"Searched web for: '{clean_q}'",
                    evidence={"query": clean_q, "url": page.url, "title": page.title()},
                )
            return None

        res = self._run_sync(_do_search, timeout=16.0)
        if isinstance(res, ActionResult):
            return res

        webbrowser.open(search_url)
        return success_result(f"Opened web search for '{clean_q}'", evidence={"query": clean_q})

    def new_tab(self, url: str = "about:blank") -> ActionResult:
        """Capability 7: Create a new browser tab."""
        def _do_new():
            self._ensure_browser_internal()
            if self._context:
                page = self._context.new_page()
                self._active_page = page
                self._pages = self._context.pages
                if url and url != "about:blank":
                    target = url if url.startswith("http") else "https://" + url
                    page.goto(target, timeout=15000, wait_until="domcontentloaded")
                return success_result("Created new browser tab", evidence={"tab_count": len(self._pages)})
            return failure_result("Browser not active")

        res = self._run_sync(_do_new, timeout=16.0)
        return res if isinstance(res, ActionResult) else failure_result("Failed to create tab")

    def close_tab(self) -> ActionResult:
        """Capability 8: Close current browser tab."""
        def _do_close():
            if self._active_page:
                self._active_page.close()
                pages = self._context.pages if self._context else []
                self._active_page = pages[-1] if pages else None
                self._pages = pages
                return success_result("Closed browser tab", evidence={"remaining_tabs": len(pages)})
            return failure_result("No active browser tab to close")

        res = self._run_sync(_do_close, timeout=5.0)
        return res if isinstance(res, ActionResult) else failure_result("Failed to close tab")

    def navigate_back(self) -> ActionResult:
        """Capability 10a: Go back."""
        def _do_back():
            if self._active_page:
                self._active_page.go_back(timeout=5000)
                return success_result("Navigated back", evidence={"url": self._active_page.url})
            return failure_result("No active browser page")

        res = self._run_sync(_do_back, timeout=6.0)
        return res if isinstance(res, ActionResult) else failure_result("Failed to go back")

    def navigate_forward(self) -> ActionResult:
        """Capability 10b: Go forward."""
        def _do_fwd():
            if self._active_page:
                self._active_page.go_forward(timeout=5000)
                return success_result("Navigated forward", evidence={"url": self._active_page.url})
            return failure_result("No active browser page")

        res = self._run_sync(_do_fwd, timeout=6.0)
        return res if isinstance(res, ActionResult) else failure_result("Failed to go forward")

    def reload(self) -> ActionResult:
        """Capability 10c: Reload page."""
        def _do_reload():
            if self._active_page:
                self._active_page.reload(timeout=10000)
                return success_result("Reloaded page", evidence={"url": self._active_page.url})
            return failure_result("No active browser page")

        res = self._run_sync(_do_reload, timeout=11.0)
        return res if isinstance(res, ActionResult) else failure_result("Failed to reload page")

    def scroll(self, direction: str = "down", amount: int = 500) -> ActionResult:
        """Capability 10d: Scroll page."""
        def _do_scroll():
            if self._active_page:
                delta = amount if direction == "down" else -amount
                self._active_page.evaluate(f"window.scrollBy(0, {delta})")
                return success_result(f"Scrolled {direction} by {amount}px")
            return failure_result("No active browser page")

        res = self._run_sync(_do_scroll, timeout=3.0)
        return res if isinstance(res, ActionResult) else failure_result("Failed to scroll")

    def click_element(self, target: str) -> ActionResult:
        """Capability 11: Click a web element using DOM locators."""
        def _do_click():
            if not self._active_page:
                return failure_result("No active browser page to click element")

            clean = target.strip()
            locators = [
                f"text={clean}",
                f"button:has-text('{clean}')",
                f"a:has-text('{clean}')",
                clean,
            ]
            for loc in locators:
                try:
                    el = self._active_page.locator(loc).first
                    if el.is_visible(timeout=1500):
                        el.click(timeout=3000)
                        return success_result(f"Clicked element matching '{target}'", evidence={"locator": loc})
                except Exception:
                    continue
            return failure_result(f"Could not find or click element '{target}'")

        res = self._run_sync(_do_click, timeout=6.0)
        return res if isinstance(res, ActionResult) else failure_result("Click operation failed")

    def type_and_submit(self, text: str, selector: str | None = None, press_enter: bool = True) -> ActionResult:
        """Capability 12: Type into a web field and optionally submit."""
        def _do_type():
            if not self._active_page:
                return failure_result("No active browser page to type into")

            try:
                if selector:
                    field = self._active_page.locator(selector).first
                else:
                    field = self._active_page.locator("input[type='text'], input[type='search'], input:not([type]), textarea").first

                if field.is_visible(timeout=2000):
                    field.fill(text)
                    if press_enter:
                        field.press("Enter")
                    return success_result(f"Typed '{text}' and submitted", evidence={"text": text})
            except Exception as exc:
                return failure_result(f"Failed to type and submit: {exc}")

            return failure_result("No suitable input field found on page")

        res = self._run_sync(_do_type, timeout=6.0)
        return res if isinstance(res, ActionResult) else failure_result("Type operation failed")

    def read_structured_info(self) -> ActionResult:
        """Capability 13: Read structured browser information."""
        def _do_read():
            if not self._active_page:
                return failure_result("No active browser page")

            title = self._active_page.title()
            url = self._active_page.url
            headings = [h.strip() for h in self._active_page.locator("h1, h2, h3").all_inner_texts() if h.strip()][:5]
            snippet = " ".join((self._active_page.locator("body").inner_text() or "").split()[:60])
            return success_result(
                f"Page title: {title}",
                evidence={"title": title, "url": url, "headings": headings, "snippet": snippet},
            )

        res = self._run_sync(_do_read, timeout=5.0)
        return res if isinstance(res, ActionResult) else failure_result("Failed to read browser info")


def get_browser_manager() -> BrowserManager:
    return BrowserManager.get_instance()
