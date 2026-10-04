"""Allow-listed terminal commands.

Commands are matched *after* tokenisation into an argv list and executed
without a shell, so quoting tricks, pipes, redirections and ``&&`` chains
cannot smuggle anything past the list (the old implementation regex-matched
the raw string and then ran it with ``shell=True``).
"""

from __future__ import annotations

import re

# program -> regex the remaining arguments (joined by single spaces) must match
ALLOWED: dict[str, str] = {
    "git": r"(status|branch|log|log --oneline|log -n \d{1,3}|log --oneline -n \d{1,3}|diff --stat|remote -v|stash list)",
    "python": r"(--version|-V)",
    "py": r"(--version|-V)",
    "pip": r"(list|--version|freeze)",
    "node": r"(--version|-v)",
    "npm": r"(--version|-v)",
    "ipconfig": r"(/all)?",
    "hostname": r"",
    "whoami": r"",
    "nvidia-smi": r"",
    "systeminfo": r"",
    "tasklist": r"",
    "dir": r"",  # cmd built-in, run as `cmd /c dir`
    "ver": r"",
}
CMD_BUILTINS = {"dir", "ver"}
_SAFE_TOKEN = re.compile(r"^[\w.\-/:=]+$")


def to_argv(command: str) -> list[str] | None:
    """Return the argv to execute, or None if the command is not allowed."""
    tokens = command.strip().rstrip(".").split()
    if not tokens:
        return None
    program = tokens[0].lower()
    if program.endswith(".exe"):
        program = program[:-4]
    pattern = ALLOWED.get(program)
    if pattern is None:
        return None
    args = tokens[1:]
    if any(not _SAFE_TOKEN.match(t) for t in args):
        return None
    if not re.fullmatch(pattern, " ".join(args), re.IGNORECASE):
        return None
    if program in CMD_BUILTINS:
        return ["cmd", "/c", program, *args]
    return [program, *args]
