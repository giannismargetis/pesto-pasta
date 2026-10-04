# Packaging (Windows installer)

```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

produces `dist\PASTA-Setup-<version>.exe`: a per-user installer (no administrator
rights) with Start-menu/desktop shortcuts, optional start with Windows, and an
uninstaller that offers to delete the downloaded model, settings and history.

## What is inside

* `pasta.spec` — PyInstaller one-folder build of `packaging/launcher.py`
  (→ `pasta.app_main`), windowed, no console. Bundles the CUDA 12 runtime from
  NVIDIA's pip wheels (cuBLAS, cuDNN 9, cudart, cuFFT, nvrtc) in the
  `nvidia/<pkg>/bin` layout that `pesto/cuda.py` looks for. PyTorch is excluded.
* `installer.iss` — Inno Setup script (Greek and English installer UI).
* The speech model (~1.6 GB) is **not** in the installer: the first-run window
  downloads it with a progress bar into `%LOCALAPPDATA%\PESTO`, then everything
  is offline.
* `PASTA.exe --selftest out.json` loads both engines, checks the keyboard hook and
  microphone without UI; the build script fails if Whisper does not load.

## Size notes

The CUDA libraries are most of the size (cuBLAS-Lt ~640 MB, cuDNN ~1.3 GB,
onnxruntime's CUDA provider ~350 MB, cuFFT ~270 MB). cuDNN's runtime-compiled
engines, nvrtc and nvjitlink look optional but are loaded for some convolution
shapes (verified with the frozen self-test), so they stay. Only `nvblas` and
`cufftw`, which nothing references, are dropped. LZMA2 compresses the folder
roughly by half.

## Machines without an NVIDIA GPU

Both engines fall back to the CPU automatically (Whisper int8, Parakeet int8);
slower (≈1–2 s per sentence) but fully functional.
