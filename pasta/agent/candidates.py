from collections.abc import Callable
from pathlib import Path
import re
from typing import Any

from .schemas import AgentAction, ComputerState, RiskLevel
from .actions.app import find_and_open_file, launch_application, open_file_or_folder
from .actions.browser import get_browser_manager
from .actions.keyboard import copy_selection, paste_clipboard, press_hotkey, select_all, type_dictated_text
from .actions.mouse import scroll_active_window
from .actions.shell import run_safe_terminal_command, toggle_mute, volume_down, volume_up
from .actions.windows import close_window, focus_window, maximize_window, minimize_window, restore_window
from .verifier import ActionVerifier


class CandidateBuilder:
    """Builds a small, bounded, grounded list of 3-12 real executable candidate actions

    based on current OS/browser state and user intent.
    """

    def __init__(self) -> None:
        self.verifier = ActionVerifier()

    def build_candidates(self, state: ComputerState, intent: str) -> list[AgentAction]:
        clean_intent = intent.lower().strip()
        candidates: list[AgentAction] = []
        browser_mgr = get_browser_manager()

        # 1. Stop / Cancel action (always available)
        candidates.append(
            AgentAction(
                id="stop",
                description="Stop the current task safely",
                category="control",
                risk=RiskLevel.READ,
                execute=lambda: self.verifier.verify_stopped(),
                verify=lambda: self.verifier.verify_stopped(),
            )
        )

        is_closing = any(w in clean_intent for w in ("close", "κλείσε", "κλεισε", "κλείσιμο"))

        # 2. Window closing actions (prioritized if closing is requested)
        if is_closing:
            if any(w in clean_intent for w in ("notepad", "σημειωματάριο")):
                candidates.append(
                    AgentAction(
                        id="close_notepad",
                        description="Close Notepad window",
                        category="windows",
                        risk=RiskLevel.LOW,
                        execute=lambda: close_window("notepad"),
                        verify=lambda: self.verifier.verify_window_state_changed(),
                    )
                )
            if any(w in clean_intent for w in ("calc", "calculator", "κομπιουτεράκι", "αριθμομηχανή")):
                candidates.append(
                    AgentAction(
                        id="close_calculator",
                        description="Close Calculator window",
                        category="windows",
                        risk=RiskLevel.LOW,
                        execute=lambda: close_window("calc"),
                        verify=lambda: self.verifier.verify_window_state_changed(),
                    )
                )
            if any(w in clean_intent for w in ("chrome", "browser", "ιντερνετ")):
                candidates.append(
                    AgentAction(
                        id="close_chrome",
                        description="Close Chrome browser window",
                        category="windows",
                        risk=RiskLevel.LOW,
                        execute=lambda: close_window("chrome"),
                        verify=lambda: self.verifier.verify_window_state_changed(),
                    )
                )
            if any(w in clean_intent for w in ("all", "όλα", "ολα")):
                candidates.append(
                    AgentAction(
                        id="minimize_all_windows",
                        description="Minimize all open windows",
                        category="windows",
                        risk=RiskLevel.LOW,
                        execute=lambda: minimize_window(),
                        verify=lambda: self.verifier.verify_window_state_changed(),
                    )
                )
            candidates.append(
                AgentAction(
                    id="close_active_window",
                    description="Close the currently active window",
                    category="windows",
                    risk=RiskLevel.LOW,
                    execute=lambda: close_window(),
                    verify=lambda: self.verifier.verify_window_state_changed(),
                )
            )

        # 3. YouTube actions
        if any(w in clean_intent for w in ("youtube", "γιουτιουμπ", "γιουτιούμπ")):
            yt_query = ""
            m = re.search(r"(?:search|ψάξε|ψαξε|βρες)(?:\s+(?:for|για))?\s+(.*)", clean_intent)
            if m:
                raw_q = m.group(1).strip()
                yt_query = re.sub(r"\b(?:στο|στο\s+youtube|youtube|video|videos|βίντεο)\b", "", raw_q, flags=re.IGNORECASE).strip()

            if yt_query:
                import urllib.parse
                encoded = urllib.parse.quote_plus(yt_query)
                candidates.append(
                    AgentAction(
                        id="search_youtube",
                        description=f"Search YouTube for '{yt_query}'",
                        category="browser",
                        risk=RiskLevel.LOW,
                        execute=lambda q=encoded: browser_mgr.open_url(f"https://www.youtube.com/results?search_query={q}"),
                        verify=lambda: self.verifier.verify_browser_active(),
                    )
                )
            candidates.append(
                AgentAction(
                    id="open_youtube",
                    description="Open YouTube",
                    category="browser",
                    risk=RiskLevel.LOW,
                    execute=lambda: browser_mgr.open_url("https://www.youtube.com"),
                    verify=lambda: self.verifier.verify_browser_active(),
                )
            )

        # 4. Chrome / Browser actions (if not closing)
        if any(w in clean_intent for w in ("chrome", "browser", "browse", "web", "ιντερνετ", "χρωμ")):
            # Check if Chrome is already running or requested to switch/focus
            is_chrome_open = any("chrome" in w.process_name.lower() or "chrome" in w.title.lower() for w in state.windows)
            if is_chrome_open or "switch" in clean_intent or "focus" in clean_intent:
                candidates.append(
                    AgentAction(
                        id="focus_chrome",
                        description="Switch to existing Chrome window",
                        category="windows",
                        risk=RiskLevel.LOW,
                        execute=lambda: focus_window("chrome"),
                        verify=lambda: self.verifier.verify_window_focused("chrome"),
                    )
                )
            if not is_closing:
                candidates.append(
                    AgentAction(
                        id="launch_chrome",
                        description="Launch Google Chrome",
                        category="app",
                        risk=RiskLevel.LOW,
                        execute=lambda: launch_application("chrome"),
                        verify=lambda: self.verifier.verify_app_running("chrome"),
                    )
                )

        # 5. Search web action
        search_match = re.search(r"(?:search\s+(?:for\s+)?|ψάξε\s+(?:για\s+)?)(.*)", clean_intent)
        if (search_match or "search" in clean_intent or "ψάξε" in clean_intent) and "youtube" not in clean_intent:
            query = search_match.group(1).strip() if search_match else clean_intent
            query = re.sub(r"^(for|prices?|τιμές?)\s*", "", query, flags=re.IGNORECASE)
            candidates.append(
                AgentAction(
                    id="search_web",
                    description=f"Search web for '{query}'",
                    category="browser",
                    risk=RiskLevel.LOW,
                    execute=lambda q=query: browser_mgr.search_web(q),
                    verify=lambda: self.verifier.verify_browser_active(),
                    metadata={"query": query},
                )
            )

        # 6. Open URL action
        url_match = re.search(r"(?:open\s+|άνοιξε\s+)?([a-zA-Z0-9\-\.]+\.(?:com|org|io|net|edu|gr|dev|co|ai)(?:/\S*)?)", clean_intent)
        if url_match:
            raw_url = url_match.group(1)
            candidates.append(
                AgentAction(
                    id="open_url",
                    description=f"Open URL: {raw_url}",
                    category="browser",
                    risk=RiskLevel.LOW,
                    execute=lambda u=raw_url: browser_mgr.open_url(u),
                    verify=lambda: self.verifier.verify_browser_url(raw_url),
                    metadata={"url": raw_url},
                )
            )

        # 7. Calculator action (launch only if not closing)
        if any(w in clean_intent for w in ("calc", "calculator", "κομπιουτεράκι", "αριθμομηχανή")):
            if not is_closing:
                candidates.append(
                    AgentAction(
                        id="launch_calculator",
                        description="Open Windows Calculator",
                        category="app",
                        risk=RiskLevel.LOW,
                        execute=lambda: launch_application("calc"),
                        verify=lambda: self.verifier.verify_app_running("calc"),
                    )
                )

        # 8. Notepad action (launch only if not closing)
        if any(w in clean_intent for w in ("notepad", "σημειωματάριο", "notes")):
            if not is_closing:
                candidates.append(
                    AgentAction(
                        id="launch_notepad",
                        description="Open Notepad",
                        category="app",
                        risk=RiskLevel.LOW,
                        execute=lambda: launch_application("notepad"),
                        verify=lambda: self.verifier.verify_app_running("notepad"),
                    )
                )

        # 9. VS Code action
        if any(w in clean_intent for w in ("vs code", "vscode", "code", "βς κοντ")):
            if not is_closing:
                candidates.append(
                    AgentAction(
                        id="launch_vscode",
                        description="Open Visual Studio Code",
                        category="app",
                        risk=RiskLevel.LOW,
                        execute=lambda: launch_application("code"),
                        verify=lambda: self.verifier.verify_app_running("code"),
                    )
                )
            candidates.append(
                AgentAction(
                    id="focus_vscode",
                    description="Switch to Visual Studio Code",
                    category="windows",
                    risk=RiskLevel.LOW,
                    execute=lambda: focus_window("code"),
                    verify=lambda: self.verifier.verify_window_focused("code"),
                )
            )

        # 8. Downloads / Documents folder action
        if any(w in clean_intent for w in ("downloads", "λήψεις")):
            candidates.append(
                AgentAction(
                    id="open_downloads",
                    description="Open Downloads folder",
                    category="filesystem",
                    risk=RiskLevel.READ,
                    execute=lambda: open_file_or_folder(str(Path.home() / "Downloads")),
                    verify=lambda: self.verifier.verify_window_focused("Downloads"),
                )
            )

        # 9. Find file by name
        find_match = re.search(
            r"(?:find(?:\s+file)?|search\s+file|βρες(?:\s+μου)?|ψάξε(?:\s+μου)?(?:\s+για)?(?:\s+αρχείο)?)\s+(?:my\s+|the\s+|file\s+|named\s+|το\s+|τα\s+|ένα\s+|αρχείο\s+)*(.+)",
            clean_intent,
        )
        if find_match:
            file_q = find_match.group(1).strip()
            # Strip trailing Greek/English possessives and punctuation
            file_q = re.sub(r"\s+(?:μου|σου|του|μας|σας|my)$", "", file_q, flags=re.IGNORECASE).rstrip(". ").strip()
            if file_q:
                candidates.append(
                    AgentAction(
                        id="find_file",
                        description=f"Find and open file '{file_q}'",
                        category="filesystem",
                        risk=RiskLevel.READ,
                        execute=lambda fq=file_q: find_and_open_file(fq),
                        verify=lambda: self.verifier.verify_file_opened(file_q),
                    )
                )

        # 10. Browser tabs and navigation
        if any(w in clean_intent for w in ("tab", "καρτέλα")):
            if "new" in clean_intent or "καινούρια" in clean_intent or "νέα" in clean_intent:
                candidates.append(
                    AgentAction(
                        id="new_browser_tab",
                        description="Create a new browser tab",
                        category="browser",
                        risk=RiskLevel.LOW,
                        execute=lambda: browser_mgr.new_tab(),
                        verify=lambda: self.verifier.verify_browser_active(),
                    )
                )
            if "close" in clean_intent or "κλείσε" in clean_intent:
                candidates.append(
                    AgentAction(
                        id="close_browser_tab",
                        description="Close the current browser tab",
                        category="browser",
                        risk=RiskLevel.LOW,
                        execute=lambda: browser_mgr.close_tab(),
                        verify=lambda: self.verifier.verify_browser_active(),
                    )
                )

        if any(w in clean_intent for w in ("go back", "γύρνα πίσω", "back", "πίσω")):
            candidates.append(
                AgentAction(
                    id="browser_back",
                    description="Navigate back in browser history",
                    category="browser",
                    risk=RiskLevel.LOW,
                    execute=lambda: browser_mgr.navigate_back(),
                    verify=lambda: self.verifier.verify_browser_active(),
                )
            )

        # 11. Typing & Keyboard input
        type_match = re.search(r"(?:type|write|γράψε)\s+(.*)", clean_intent)
        if type_match:
            txt = type_match.group(1).strip()
            candidates.append(
                AgentAction(
                    id="type_text",
                    description=f"Type dictated text: '{txt}'",
                    category="keyboard",
                    risk=RiskLevel.LOW,
                    execute=lambda t=txt: type_dictated_text(t),
                    verify=lambda: self.verifier.verify_text_typed(txt),
                )
            )

        if any(w in clean_intent for w in ("enter", "πάτα enter", "press enter")):
            candidates.append(
                AgentAction(
                    id="press_enter",
                    description="Press Enter key",
                    category="keyboard",
                    risk=RiskLevel.LOW,
                    execute=lambda: press_hotkey("enter"),
                    verify=lambda: self.verifier.verify_hotkey_pressed("enter"),
                )
            )

        if any(w in clean_intent for w in ("copy", "αντιγραφή")):
            candidates.append(
                AgentAction(
                    id="copy_selection",
                    description="Copy current selection to clipboard",
                    category="keyboard",
                    risk=RiskLevel.LOW,
                    execute=lambda: copy_selection(),
                    verify=lambda: self.verifier.verify_clipboard_has_text(),
                )
            )

        if any(w in clean_intent for w in ("paste", "επικόλληση")):
            candidates.append(
                AgentAction(
                    id="paste_clipboard",
                    description="Paste text from clipboard",
                    category="keyboard",
                    risk=RiskLevel.LOW,
                    execute=lambda: paste_clipboard(),
                    verify=lambda: self.verifier.verify_clipboard_has_text(),
                )
            )

        # 12. Scrolling
        if any(w in clean_intent for w in ("scroll", "σκρολ")):
            direction = "up" if ("up" in clean_intent or "πάνω" in clean_intent) else "down"
            candidates.append(
                AgentAction(
                    id=f"scroll_{direction}",
                    description=f"Scroll active window {direction}",
                    category="mouse",
                    risk=RiskLevel.LOW,
                    execute=lambda d=direction: scroll_active_window(d),
                    verify=lambda: self.verifier.verify_scroll_executed(),
                )
            )

        # 13. Terminal commands
        if any(w in clean_intent for w in ("git", "terminal", "command", "τρέξε", "run", "τερματικό")):
            if "status" in clean_intent:
                candidates.append(
                    AgentAction(
                        id="run_git_status",
                        description="Run git status in terminal",
                        category="shell",
                        risk=RiskLevel.LOW,
                        execute=lambda: run_safe_terminal_command("git status"),
                        verify=lambda: self.verifier.verify_terminal_command_success(),
                    )
                )
            elif "python" in clean_intent:
                candidates.append(
                    AgentAction(
                        id="run_python_version",
                        description="Run python --version in terminal",
                        category="shell",
                        risk=RiskLevel.LOW,
                        execute=lambda: run_safe_terminal_command("python --version"),
                        verify=lambda: self.verifier.verify_terminal_command_success(),
                    )
                )
        elif clean_intent.startswith("python") or "python --version" in clean_intent or "python version" in clean_intent:
            candidates.append(
                AgentAction(
                    id="run_python_version",
                    description="Run python --version in terminal",
                    category="shell",
                    risk=RiskLevel.LOW,
                    execute=lambda: run_safe_terminal_command("python --version"),
                    verify=lambda: self.verifier.verify_terminal_command_success(),
                )
            )

        # 14. Volume / Mute
        if any(w in clean_intent for w in ("mute", "σίγαση", "μούγκα")):
            candidates.append(
                AgentAction(
                    id="toggle_mute",
                    description="Mute / unmute computer volume",
                    category="system",
                    risk=RiskLevel.LOW,
                    execute=lambda: toggle_mute(),
                    verify=lambda: self.verifier.verify_mute_toggled(),
                )
            )

        # 15. Window minimization / maximization / inspect
        if "minimize" in clean_intent or "ελαχιστοποίησε" in clean_intent:
            candidates.append(
                AgentAction(
                    id="minimize_active_window",
                    description="Minimize active window",
                    category="windows",
                    risk=RiskLevel.LOW,
                    execute=lambda: minimize_window(),
                    verify=lambda: self.verifier.verify_window_state_changed(),
                )
            )

        if "what is currently open" in clean_intent or "τι είναι ανοιχτό" in clean_intent:
            candidates.append(
                AgentAction(
                    id="inspect_open_windows",
                    description="Inspect all open application windows",
                    category="system",
                    risk=RiskLevel.READ,
                    execute=lambda: self.verifier.verify_inspected_windows(state),
                    verify=lambda: self.verifier.verify_inspected_windows(state),
                )
            )

        # Ensure we return between 3 and 12 candidates
        # If fewer than 3, add grounded contextual fallbacks
        if len(candidates) < 3:
            candidates.append(
                AgentAction(
                    id="open_browser",
                    description="Open web browser",
                    category="browser",
                    risk=RiskLevel.LOW,
                    execute=lambda: browser_mgr.open_url("https://www.google.com"),
                    verify=lambda: self.verifier.verify_browser_active(),
                )
            )
        if len(candidates) < 3:
            candidates.append(
                AgentAction(
                    id="focus_active_window",
                    description="Focus current active window",
                    category="windows",
                    risk=RiskLevel.LOW,
                    execute=lambda: focus_window(state.foreground_window.hwnd if state.foreground_window else 0),
                    verify=lambda: self.verifier.verify_window_focused(),
                )
            )

        return candidates[:12]
