"""GPU telemetry through NVML (ships with the NVIDIA driver).

The previous implementation imported PyTorch only to call
``torch.cuda.mem_get_info``: ~1.9 s of import time plus a second CUDA context
(hundreds of MB of VRAM) on a machine where neither ASR runtime needs torch.
NVML is a ~1 ms ctypes call with no CUDA context at all.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from dataclasses import dataclass

_lock = threading.Lock()
_nvml = None
_handle = None
_failed = False


class _Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class _Utilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


@dataclass(frozen=True)
class GpuSnapshot:
    available: bool
    name: str = "CPU"
    used_mb: float = 0.0
    total_mb: float = 0.0
    util_pct: float = 0.0
    clock_mhz: int = 0

    @property
    def used_pct(self) -> float:
        return 100.0 * self.used_mb / self.total_mb if self.total_mb else 0.0


def _init() -> bool:
    global _nvml, _handle, _failed
    if _nvml is not None:
        return True
    if _failed or sys.platform != "win32" and not sys.platform.startswith("linux"):
        return False
    try:
        lib = ctypes.CDLL("nvml.dll" if sys.platform == "win32" else "libnvidia-ml.so.1")
        if lib.nvmlInit_v2() != 0:
            raise OSError("nvmlInit failed")
        handle = ctypes.c_void_p()
        if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
            raise OSError("no NVIDIA device")
        _nvml, _handle = lib, handle
        return True
    except OSError:
        _failed = True
        return False


def snapshot() -> GpuSnapshot:
    with _lock:
        if not _init():
            return GpuSnapshot(available=False)
        mem = _Memory()
        util = _Utilization()
        name = ctypes.create_string_buffer(96)
        _nvml.nvmlDeviceGetMemoryInfo(_handle, ctypes.byref(mem))
        _nvml.nvmlDeviceGetUtilizationRates(_handle, ctypes.byref(util))
        _nvml.nvmlDeviceGetName(_handle, name, 96)
        clock = ctypes.c_uint()
        _nvml.nvmlDeviceGetClockInfo(_handle, 0, ctypes.byref(clock))  # NVML_CLOCK_GRAPHICS
    return GpuSnapshot(
        available=True,
        name=name.value.decode(errors="replace"),
        used_mb=mem.used / 2**20,
        total_mb=mem.total / 2**20,
        util_pct=float(util.gpu),
        clock_mhz=int(clock.value),
    )
