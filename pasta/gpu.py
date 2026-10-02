from typing import Any
from .logging_setup import get_logger

log = get_logger("gpu")


def get_gpu_memory_info() -> dict[str, Any]:
    """Returns GPU VRAM metrics for NVIDIA / PyTorch.

    Returns dict with keys:
    - available: bool
    - name: str
    - used_gb: float
    - total_gb: float
    - free_gb: float
    - percent_used: float
    """
    try:
        import torch

        if torch.cuda.is_available():
            free_bytes, total_bytes = torch.cuda.mem_get_info(0)
            used_bytes = total_bytes - free_bytes
            used_gb = used_bytes / (1024 ** 3)
            total_gb = total_bytes / (1024 ** 3)
            free_gb = free_bytes / (1024 ** 3)
            pct = (used_bytes / total_bytes) * 100.0 if total_bytes > 0 else 0.0
            device_name = torch.cuda.get_device_name(0)
            return {
                "available": True,
                "name": device_name,
                "used_gb": round(used_gb, 2),
                "total_gb": round(total_gb, 2),
                "free_gb": round(free_gb, 2),
                "percent_used": round(pct, 1),
            }
    except Exception as exc:
        log.debug("GPU probe exception: %s", exc)

    return {
        "available": False,
        "name": "CPU",
        "used_gb": 0.0,
        "total_gb": 0.0,
        "free_gb": 0.0,
        "percent_used": 0.0,
    }
