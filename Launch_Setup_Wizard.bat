@echo off
setlocal enabledelayedexpansion
title ArgusTraffic AI - Enterprise Setup Wizard
cd /d "%~dp0"

echo =====================================================================
echo           ARGUSTRAFFIC AI - ENTERPRISE SETUP WIZARD
echo =====================================================================

:: 1. Detect Python Executable (prefer virtual environment)
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "C:\Python314\python.exe" (
    set "PYTHON_EXE=C:\Python314\python.exe"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('where python') do (
            if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
        )
    )
)

if not defined PYTHON_EXE (
    echo [ERROR] No Python installation found on system.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

echo [+] Using Python Runtime: "!PYTHON_EXE!"
echo [+] Starting Setup Wizard...
echo.

"!PYTHON_EXE!" "%~dp0setup_wizard.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Setup Wizard exited with error code %errorlevel%.
    echo Please check the error messages above.
    pause
)
