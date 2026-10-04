"""Optional local-LLM parser (Ollama) for utterances the grammar cannot parse.

* Runs only after the deterministic grammar failed — never on the hot path.
* Output is constrained by a JSON schema derived from the action table and
  re-validated; anything outside the table is discarded.
* Intents from here carry ``source="llm"``; the safety policy always asks
  before running them. The model can widen what PASTA *understands*, not what
  it does without consent.
"""

from __future__ import annotations

import json
import time
import urllib.request

from pesto.log import get_logger

from ..intents import ACTIONS, Intent, validate

log = get_logger("pasta.llm")
LLM_CONFIDENCE = 0.7


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "understood": {"type": "boolean"},
            "steps": {
                "type": "array", "maxItems": 4,
                "items": {"type": "object", "properties": {
                    "action": {"type": "string", "enum": [a for a in ACTIONS if a != "stop"]},
                    "args": {"type": "object"}}, "required": ["action", "args"]},
            },
        },
        "required": ["understood", "steps"],
    }


def _system_prompt(windows: list[str]) -> str:
    lines = []
    for a in ACTIONS.values():
        if a.name == "stop":
            continue
        params = ", ".join(f"{k}: {v}" for k, v in a.params.items()) or "no arguments"
        lines.append(f"- {a.name}({params}): {a.summary}")
    return (
        "You convert a spoken Windows command (Greek or English) into steps for a desktop assistant.\n"
        "Use ONLY these actions and argument names (types: str, int, enum:a|b; '?' = optional):\n"
        + "\n".join(lines)
        + "\nRules: keep user-provided text (search queries, text to type) in the user's language and spelling. "
        "If the request is not one of these actions, return understood=false and no steps. "
        "Never invent shell commands. Respond with JSON only.\n"
        f"Currently open windows: {', '.join(windows[:12]) or 'none'}"
    )


def parse(text: str, url: str, model: str, timeout_s: float, windows: list[str] | None = None) -> tuple[list[Intent], dict]:
    """Returns (intents, diagnostics). Empty intents = not understood / unavailable."""
    body = {
        "model": model, "stream": False, "format": _schema(), "think": False,
        "options": {"temperature": 0, "num_predict": 256},
        "messages": [{"role": "system", "content": _system_prompt(windows or [])},
                     {"role": "user", "content": text}],
    }
    t0 = time.perf_counter()
    diag: dict = {"model": model}
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload.get("message", {}).get("content", "")
        data = json.loads(content)
    except Exception as exc:
        diag.update(error=str(exc), ms=(time.perf_counter() - t0) * 1000)
        log.warning("LLM parse failed: %s", exc)
        return [], diag
    diag["ms"] = (time.perf_counter() - t0) * 1000
    diag["raw"] = data
    if not data.get("understood"):
        return [], diag
    intents = []
    for step in data.get("steps", [])[:4]:
        intent = Intent(step.get("action", ""), dict(step.get("args") or {}), LLM_CONFIDENCE, "llm", text)
        intent.args = {k: v for k, v in intent.args.items() if v not in (None, "")}
        error = validate(intent)
        if error:
            diag.setdefault("rejected", []).append(error)
            continue
        intents.append(intent)
    return intents, diag


def available(url: str, model: str, timeout_s: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/tags", timeout=timeout_s) as resp:
            names = {m.get("name") for m in json.loads(resp.read().decode("utf-8")).get("models", [])}
        return model in names
    except Exception:
        return False
