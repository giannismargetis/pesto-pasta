@echo off
setlocal enabledelayedexpansion
title PASTA V2 — Voice-to-Computer Control & Dictation
cd /d "%~dp0"

echo ======================================================================
echo    🍝 PASTA V2 — Local Voice-to-Computer Control ^& Dictation
echo ======================================================================
echo.

:: 1. Locate Python environment (check local venv first, then sibling voice-typer venv, then system)
set "PYTHON_EXE="
if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else if exist "..\voice-typer\venv\Scripts\python.exe" (
    set "PYTHON_EXE=..\voice-typer\venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python not found! Please install Python 3.10+ or create a venv.
    pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHON_EXE%

:: 2. Quick check for CUDA GPU
%PYTHON_EXE% -c "import torch; print('[INFO] CUDA Available:', torch.cuda.is_available(), '| Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')" 2>nul

:: 3. Launch PASTA
echo [INFO] Starting PASTA V2...
echo [INFO] Hold [Right Ctrl] to speak. Press [Esc] to cancel running actions.
echo.
%PYTHON_EXE% -m pasta run

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] PASTA exited with code %errorlevel%.
    pause
)
