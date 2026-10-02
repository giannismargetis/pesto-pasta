from typing import Any

from ...logging_setup import get_logger
from ..schemas import BrowserState

log = get_logger("observer.browser")


class BrowserObserver:
    """Observer for web browser state and DOM structures via Playwright."""

    def __init__(self, browser_manager=None) -> None:
        self.browser_manager = browser_manager

    def observe(self) -> BrowserState:
        if not self.browser_manager or not self.browser_manager.is_active():
            return BrowserState(is_active=False)

        try:
            page = self.browser_manager.get_active_page()
            if not page:
                return BrowserState(is_active=False)

            title = page.title() or ""
            url = page.url or ""

            # Extract headings and snippet
            headings = []
            try:
                h_elements = page.locator("h1, h2, h3").all_inner_texts()
                headings = [h.strip() for h in h_elements if h.strip()][:5]
            except Exception:
                pass

            # Extract snippet
            snippet = ""
            try:
                body_text = page.locator("body").inner_text()
                snippet = " ".join(body_text.split()[:40])
            except Exception:
                pass

            # Extract interactive elements (buttons, inputs)
            interactive: list[dict[str, Any]] = []
            try:
                inputs = page.locator("input, button, a[href]").all()
                for el in inputs[:10]:
                    try:
                        tag = el.evaluate("e => e.tagName.toLowerCase()")
                        text = el.inner_text().strip() or el.get_attribute("placeholder") or el.get_attribute("aria-label") or ""
                        interactive.append({"tag": tag, "text": text})
                    except Exception:
                        pass
            except Exception:
                pass

            tab_count = len(self.browser_manager.get_all_pages())

            return BrowserState(
                is_active=True,
                title=title,
                url=url,
                tab_count=tab_count,
                active_tab_index=0,
                visible_text_snippet=snippet,
                headings=headings,
                interactive_elements=interactive,
            )
        except Exception as exc:
            log.warning("Browser observation failed: %s", exc)
            return BrowserState(is_active=False)
