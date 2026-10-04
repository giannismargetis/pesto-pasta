"""Local-first model resolution.

The old code passed Hugging Face repo ids straight to the runtimes, which
issue network requests on every load (latency, and it leaks usage to a third
party for a product advertised as fully local). We resolve the snapshot from
the local cache first and only go online when the files are missing.
"""

from __future__ import annotations

from pathlib import Path

from .. import paths  # noqa: F401  (sets HF_* environment before hub import)
from ..log import get_logger

log = get_logger("asr.models")

WHISPER_REPOS = {
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
}
PARAKEET_REPOS = {"nemo-parakeet-tdt-0.6b-v3": "istupakov/parakeet-tdt-0.6b-v3-onnx"}


def resolve_snapshot(repo_id: str, allow_patterns: list[str] | None = None) -> Path:
    from huggingface_hub import snapshot_download

    try:
        return Path(snapshot_download(repo_id, local_files_only=True, allow_patterns=allow_patterns))
    except Exception:
        log.info("Model %s not cached locally; downloading once", repo_id)
        return Path(snapshot_download(repo_id, allow_patterns=allow_patterns))
