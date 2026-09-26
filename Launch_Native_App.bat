@echo off
title ArgusTraffic AI - Desktop Application
cd /d "%~dp0"

if exist "C:\Python314\pythonw.exe" (
    start "" "C:\Python314\pythonw.exe" "%~dp0desktop_app.py"
    exit /b 0
)

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0desktop_app.py"
    exit /b 0
)

start "" pythonw "%~dp0desktop_app.py"
