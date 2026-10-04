@echo off
setlocal
title PESTO - push-to-talk dictation
cd /d "%~dp0"

set "PY="
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY if exist "..\voice-typer\venv\Scripts\python.exe" set "PY=..\voice-typer\venv\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3.11+ not found. Run scripts\setup.ps1 first.
    pause
    exit /b 1
)

rem Dictation only (no voice commands). Hold Right Ctrl, speak, release.
"%PY%" -m pesto %*
if errorlevel 1 (
    echo.
    echo PESTO exited with an error. Run "%PY% -m pesto doctor" to check the setup.
    pause
)
