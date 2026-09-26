@echo off
setlocal

title ArgusTraffic AI Desktop Platform

:: Check Virtualenv
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

:: Launch Desktop Application
echo [+] Launching ArgusTraffic AI Desktop Window...
python desktop_app.py

if errorlevel 1 (
    echo [ERROR] An error occurred while running the desktop application.
    pause
)
