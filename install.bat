@echo off
setlocal enabledelayedexpansion

echo =====================================================================
echo           ARGUSTRAFFIC AI - ENTERPRISE ZERO-CLICK INSTALLER
echo      World Top-Tier Autonomous Incident & Traffic Vision Platform
echo =====================================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required but not found in PATH.
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%a in ('python --version 2^>^&1') do set PY_VER=%%a
echo [+] Detected Python version: %PY_VER%

:: 2. Check or Create Virtual Environment
if not exist ".venv" (
    echo [+] Creating production virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo [+] Activating virtual environment...
call .venv\Scripts\activate.bat

:: 3. Upgrade pip and install core dependencies
echo [+] Upgrading pip, setuptools, and wheel...
python -m pip install --quiet --upgrade pip setuptools wheel

echo [+] Installing production dependencies from requirements.txt...
pip install --quiet -r requirements.txt

echo [+] Installing ArgusTraffic AI in production mode...
pip install --quiet -e .

:: 4. Verify PyTorch and Hardware Acceleration
echo.
echo =====================================================================
echo [+] Hardware Accelerator Diagnostics:
python -c "import torch; print('    - PyTorch Version:', torch.__version__); print('    - CUDA Acceleration Available:', torch.cuda.is_available()); print('    - Active Accelerator Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'High-Performance CPU (Multi-Threaded)');"
echo =====================================================================
echo.

:: 5. Launch Enterprise Setup Wizard GUI
echo [+] Starting ArgusTraffic AI Enterprise Setup Wizard...
echo.
python setup_wizard.py
if errorlevel 1 (
    echo [INFO] Falling back to Web Command Center directly...
    start "" "http://localhost:8080"
    python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8080
)

