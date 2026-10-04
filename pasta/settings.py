"""PASTA configuration sections (registered into PESTO's config)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pesto.config import register_section


@dataclass
class AgentSettings:
    # dictation: never run commands · hybrid: commands need the wake word ·
    # command: every utterance is a command (dictation via "type ...")
    mode: str = "hybrid"
    mode_key: str = "ctrl+alt+shift+m"
    wake_words: list[str] = field(default_factory=lambda: ["pasta", "jarvis", "πάστα", "τζάρβις"])
    # Confidence gate (see docs/PASTA.md#safety): >= auto -> run; >= confirm -> ask; else refuse
    auto_threshold: float = 0.80
    confirm_threshold: float = 0.50
    confirm_timeout_s: float = 10.0
    max_steps: int = 6
    step_timeout_s: float = 8.0
    # Optional local LLM for utterances the grammar cannot parse. Its proposals
    # are never auto-executed: they always require confirmation.
    llm_enabled: bool = False
    llm_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3.5:9b-q4_K_M"
    llm_timeout_s: float = 20.0
    preferred_browser: str = ""  # "" = system default


@dataclass
class PermissionSettings:
    apps: bool = True
    windows: bool = True
    browser: bool = True
    keyboard: bool = True
    system: bool = True  # volume, media keys
    files: bool = True  # open folders / find and open files (read-only)
    ui_click: bool = True  # click named controls via UI Automation
    shell: str = "allowlist"  # none | allowlist
    close_windows: str = "confirm"  # auto | confirm | never


# PASTA v2 "agent"/"permissions" blocks: translate what still means something,
# drop settings of the decision model that never actually loaded.
_LEGACY_AGENT = {"confidence_threshold": "auto_threshold", "confirmation_threshold": "confirm_threshold",
                 "wake_names": "wake_words", "max_steps": "max_steps"}
_DROPPED_AGENT = {"enabled", "model", "model_runtime", "model_revision", "model_quantization", "loop_timeout_seconds",
                  "max_retries", "max_same_state_repeats", "allow_shell_commands", "headless_browser"}


def _migrate_agent(raw: dict) -> dict:
    out = {}
    for k, v in raw.items():
        if k in _DROPPED_AGENT:
            continue
        out[_LEGACY_AGENT.get(k, k)] = v
    if raw.get("enabled") is False:
        out["mode"] = "dictation"
    if "max_steps" in out:
        out["max_steps"] = min(int(out["max_steps"]), 6)
    return out


def _migrate_permissions(raw: dict) -> dict:
    legacy = {"browser", "filesystem_read", "filesystem_write", "shell", "process_termination", "email_send",
              "destructive_actions"}
    if not (set(raw) & (legacy - {"browser", "shell"})):
        return raw
    return {"browser": bool(raw.get("browser", True)), "files": bool(raw.get("filesystem_read", True)),
            "shell": raw.get("shell", "allowlist") if raw.get("shell") in ("none", "allowlist") else "allowlist"}


register_section("agent", AgentSettings, _migrate_agent)
register_section("permissions", PermissionSettings, _migrate_permissions)
