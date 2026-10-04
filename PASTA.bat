@echo off
setlocal
title PASTA - voice commands + dictation
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

rem Hold Right Ctrl to dictate; say "Pasta, ..." for commands. Esc cancels.
"%PY%" -m pasta %*
if errorlevel 1 (
    echo.
    echo PASTA exited with an error. Run "%PY% -m pasta doctor" to check the setup.
    pause
)
