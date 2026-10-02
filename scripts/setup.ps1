# PASTA V2 — Setup and Environment Validator for Windows
$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "         🍝 PASTA V2 — Setup & Environment Installation" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

$targetDir = $PSScriptRoot | Split-Path -Parent
Set-Location $targetDir

# 1. Locate or create Python virtual environment
$pythonExe = ""
if (Test-Path "$targetDir\venv\Scripts\python.exe") {
    $pythonExe = "$targetDir\venv\Scripts\python.exe"
    Write-Host "[OK] Using local virtual environment: $pythonExe" -ForegroundColor Green
} elseif (Test-Path "$targetDir\..\voice-typer\venv\Scripts\python.exe") {
    $pythonExe = "$targetDir\..\voice-typer\venv\Scripts\python.exe"
    Write-Host "[OK] Sibling Pesto virtual environment found: $pythonExe" -ForegroundColor Green
    Write-Host "     Reusing existing CUDA PyTorch environment to save disk space & time." -ForegroundColor Gray
} else {
    Write-Host "[INFO] Creating virtual environment at $targetDir\venv..." -ForegroundColor Yellow
    python -m venv "$targetDir\venv"
    $pythonExe = "$targetDir\venv\Scripts\python.exe"
}

# 2. Check Python version & CUDA GPU
Write-Host ""
Write-Host "--- Checking Hardware Acceleration ---" -ForegroundColor Cyan
& $pythonExe -c @"
import sys, torch
print(f'Python: {sys.version.split()[0]}')
cuda_ok = torch.cuda.is_available()
print(f'CUDA Acceleration: {\"ENABLED\" if cuda_ok else \"DISABLED\"}')
if cuda_ok:
    print(f'GPU Device: {torch.cuda.get_device_name(0)}')
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f'VRAM Total: {vram_gb:.1f} GB')
"@

# 3. Install Python Dependencies
Write-Host ""
Write-Host "--- Verifying / Installing Dependencies ---" -ForegroundColor Cyan
& $pythonExe -m pip install -r "$targetDir\requirements.txt"

# 4. Install Playwright Chromium
Write-Host ""
Write-Host "--- Ensuring Playwright Browser ---" -ForegroundColor Cyan
& $pythonExe -m playwright install chromium

# 5. Validate Decision Model
Write-Host ""
Write-Host "--- Validating Decision Model ---" -ForegroundColor Cyan
& $pythonExe -c @"
from pasta.config import load_config
from pasta.agent.models import create_decision_model
cfg = load_config()
dm = create_decision_model(cfg)
print(f'Decision Model: {type(dm).__name__}')
res = dm.decide({'task': 'open chrome'}, [{'question': 'what to do?', 'options': ['launch_chrome', 'stop']}])
print(f'Decision Engine check: {res[0].action_id} (conf={res[0].confidence:.2f})')
"@

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "  ✅ PASTA V2 is installed and ready to run!" -ForegroundColor Green
Write-Host "  Launch via PASTA.bat or run: $pythonExe -m pasta run" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
