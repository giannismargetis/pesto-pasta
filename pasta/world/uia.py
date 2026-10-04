"""Click a named control in a window through UI Automation.

Works for native apps and for Chromium/Firefox page content (they expose
their accessibility tree to UIA), so "click Sign in" or "πάτα Αποθήκευση"
operates the real UI rather than guessing screen coordinates. The tree walk
is bounded in both node count and time.
"""

from __future__ import annotations

import time
from collections import deque

from ..nlu.text import norm, similarity

CLICKABLE = {"ButtonControl", "HyperlinkControl", "MenuItemControl", "TabItemControl", "ListItemControl",
             "CheckBoxControl", "RadioButtonControl", "SplitButtonControl", "TreeItemControl", "ImageControl",
             "TextControl"}
PREFERRED = {"ButtonControl": 0.06, "HyperlinkControl": 0.05, "MenuItemControl": 0.05, "TabItemControl": 0.04}


def click_named(hwnd: int, label: str, budget_s: float = 2.5, max_nodes: int = 4000, cancel=None):
    """Returns (name, control_type, method) of the clicked control, or None."""
    import uiautomation as auto

    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return None
        deadline = time.perf_counter() + budget_s
        target = norm(label)
        best, best_score = None, 0.0
        queue = deque([(root, 0)])
        seen = 0
        while queue and seen < max_nodes and time.perf_counter() < deadline:
            if cancel is not None and cancel.is_set():
                return None
            ctrl, depth = queue.popleft()
            seen += 1
            try:
                ctype = ctrl.ControlTypeName
                name = ctrl.Name or ""
            except Exception:
                continue
            if name and ctype in CLICKABLE:
                n = norm(name)
                s = 1.0 if n == target else similarity(label, name)
                if target and target in n.split():
                    s = max(s, 0.85)
                s += PREFERRED.get(ctype, 0.0) if s >= 0.75 else 0.0
                try:
                    if s > best_score and not ctrl.IsOffscreen:
                        best, best_score = ctrl, s
                except Exception:
                    pass
                if best_score >= 1.05:
                    break
            if depth < 30:
                try:
                    child = ctrl.GetFirstChildControl()
                    while child is not None:
                        queue.append((child, depth + 1))
                        child = child.GetNextSiblingControl()
                except Exception:
                    pass
        if best is None or best_score < 0.78:
            return None
        name, ctype = best.Name, best.ControlTypeName
        for pattern, method in (("GetInvokePattern", "Invoke"), ("GetSelectionItemPattern", "Select"),
                                ("GetTogglePattern", "Toggle")):
            try:
                pat = getattr(best, pattern)()
                if pat is not None:
                    getattr(pat, method)()
                    return name, ctype, method.lower()
            except Exception:
                continue
        best.Click(simulateMove=False)
        return name, ctype, "click"
