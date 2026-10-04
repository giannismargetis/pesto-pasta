# PESTO / PASTA setup: creates venv\, installs dependencies, downloads models, runs checks.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "$root\venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment in venv\ ..."
    python -m venv "$root\venv"
}
$py = "$root\venv\Scripts\python.exe"

Write-Host "Installing PESTO + PASTA (CUDA 12 runtime wheels included) ..."
& $py -m pip install --upgrade pip
& $py -m pip install -e ".[pasta,research,dev]"

Write-Host "Downloading speech models (first run only, ~2.3 GB) ..."
& $py -c "import pesto.paths; from pesto.asr.models import resolve_snapshot as r; r('mobiuslabsgmbh/faster-whisper-large-v3-turbo'); r('istupakov/parakeet-tdt-0.6b-v3-onnx', ['encoder-model.onnx*', 'decoder_joint-model.onnx', '*.int8.onnx', 'config.json', 'vocab.txt'])"

Write-Host ""
& $py -m pesto doctor
Write-Host ""
Write-Host "Done. Start with PESTO.bat (dictation) or PASTA.bat (dictation + commands)."
