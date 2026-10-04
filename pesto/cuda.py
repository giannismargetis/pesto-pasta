"""Make CUDA 12 / cuDNN 9 runtime DLLs findable by CTranslate2 and onnxruntime.

Neither runtime ships cuBLAS. In the original setup, GPU inference worked
only because CTranslate2 opportunistically imported PyTorch, whose ``lib``
directory happens to contain ``cublas64_12.dll``. We register the candidate
directories explicitly instead (without importing torch), in this order:

1. ``nvidia-*-cu12`` pip wheels (the documented, torch-free install path)
2. an installed PyTorch's ``lib`` directory (shared environments)
3. ``CUDA_PATH`` (CUDA toolkit)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .log import get_logger

log = get_logger("cuda")
_done = False
REQUIRED = ("cublas64_12.dll", "cublasLt64_12.dll")


def candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    for entry in sys.path:
        nvidia = Path(entry) / "nvidia"
        if nvidia.is_dir():
            dirs += [p for p in nvidia.glob("*/bin") if p.is_dir()]
    # Located on disk, never imported (pesto.paths blocks the torch import).
    for entry in sys.path:
        if (Path(entry) / "torch" / "lib").is_dir():
            dirs.append(Path(entry) / "torch" / "lib")
            break
    if os.environ.get("CUDA_PATH"):
        dirs.append(Path(os.environ["CUDA_PATH"]) / "bin")
    return [d for d in dict.fromkeys(dirs) if d.is_dir()]


def register_cuda_libraries() -> list[str]:
    """Idempotent. Returns the directories that were added."""
    global _done
    if _done or sys.platform != "win32":
        return []
    _done = True
    added = []
    for d in candidate_dirs():
        try:
            os.add_dll_directory(str(d))
        except OSError:
            continue
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        added.append(str(d))
    found = {name: any((Path(d) / name).exists() for d in added) for name in REQUIRED}
    if not all(found.values()):
        log.warning("CUDA libraries not found (%s); GPU inference will fall back to CPU. "
                    "Install them with: pip install nvidia-cublas-cu12 nvidia-cudnn-cu12",
                    ", ".join(n for n, ok in found.items() if not ok))
    else:
        log.info("CUDA libraries registered from %s", "; ".join(added))
    return added
