"""Filesystem locations. Imported first so model-hub environment is set before
any Hugging Face library reads it.

Resolution order for the data home:
  1. ``PESTO_HOME`` (or legacy ``PASTA_HOME`` / ``VOICETYPER_HOME``)
  2. the source checkout, when running from a git clone (developer mode)
  3. ``%LOCALAPPDATA%/PESTO`` for an installed package
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# CTranslate2 (and onnx-asr) import PyTorch *opportunistically* when it is
# installed — only model-conversion code uses it. In a shared environment that
# costs ~2 s of start-up and hundreds of MB of RAM for nothing; neither runtime
# needs it for inference. Marking the module absent makes those optional
# imports fail fast. Set PESTO_ALLOW_TORCH=1 to opt out. (A meta-path finder,
# not a ``sys.modules["torch"] = None`` placeholder: SciPy inspects
# sys.modules for array libraries and would crash on the placeholder.)
class _BlockTorch:
    @staticmethod
    def find_spec(name, path=None, target=None):
        if name == "torch" or name.startswith("torch."):
            raise ModuleNotFoundError("torch is intentionally not loaded by PESTO", name=name)
        return None


if not os.environ.get("PESTO_ALLOW_TORCH") and "torch" not in sys.modules:
    sys.meta_path.insert(0, _BlockTorch())

SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _home() -> Path:
    for var in ("PESTO_HOME", "PASTA_HOME", "VOICETYPER_HOME"):
        if os.environ.get(var):
            return Path(os.environ[var]).expanduser().resolve()
    if (SOURCE_ROOT / "pyproject.toml").exists():
        return SOURCE_ROOT
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "PESTO"


HOME = _home()
CONFIG_PATH = HOME / "config.json"
CACHE_DIR = HOME / "cache"
MODELS_DIR = Path(os.environ.get("PESTO_MODELS_DIR", CACHE_DIR / "huggingface"))
LOG_DIR = HOME / "logs"
DATA_DIR = HOME / "data"
DB_PATH = DATA_DIR / "pesto.db"
LEGACY_DB_PATHS = (CACHE_DIR / "pasta_history.db", CACHE_DIR / "pesto_history.db")
ASSETS_DIR = SOURCE_ROOT / "assets"

# Model hub: local cache, no telemetry. Online access is only attempted when a
# model is missing locally (see pesto.asr.models.resolve_snapshot).
os.environ.setdefault("HF_HOME", str(MODELS_DIR))
os.environ.setdefault("HF_HUB_CACHE", str(MODELS_DIR))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(MODELS_DIR))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def ensure_dirs() -> None:
    for d in (CACHE_DIR, MODELS_DIR, LOG_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
