@echo off
setlocal enabledelayedexpansion
title ArgusTraffic AI - Automated Installer Build Pipeline
cd /d "%~dp0"

echo =====================================================================
echo       ARGUSTRAFFIC AI - WINDOWS INSTALLER BUILD PIPELINE
echo =====================================================================
echo.

:: 1. Detect Python Runtime
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
    echo [ERROR] Python not found. Please install Python 3.10+.
    pause
    exit /b 1
)

echo [+] Using Python: "!PYTHON_EXE!"

:: 2. Ensure PyInstaller is installed
"!PYTHON_EXE!" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [+] Installing PyInstaller...
    "!PYTHON_EXE!" -m pip install --quiet pyinstaller
)

:: 3. Build standalone application bundle with PyInstaller
echo.
echo =====================================================================
echo [STAGE 1/2] Compiling Application Bundle via PyInstaller...
echo =====================================================================
echo [*] Packaging desktop_app.py and neural weights into dist\ArgusTraffic...
"!PYTHON_EXE!" -m PyInstaller --noconfirm argustraffic.spec

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller compilation failed! Check error messages above.
    pause
    exit /b 1
)

echo [OK] Application bundle successfully generated at:
echo      "%~dp0dist\ArgusTraffic\ArgusTraffic.exe"

:: 4. Detect Inno Setup or NSIS compiler
echo.
echo =====================================================================
echo [STAGE 2/2] Generating Windows Setup Installer (.exe)...
echo =====================================================================

if not exist "%~dp0Output" mkdir "%~dp0Output"

set "ISCC_EXE="
if exist "C:\Program Files\Inno Setup 7\ISCC.exe" set "ISCC_EXE=C:\Program Files\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_EXE=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE (
    where iscc >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('where iscc') do if not defined ISCC_EXE set "ISCC_EXE=%%i"
    )
)

set "MAKENSIS_EXE="
if exist "C:\Program Files (x86)\NSIS\makensis.exe" set "MAKENSIS_EXE=C:\Program Files (x86)\NSIS\makensis.exe"
if exist "C:\Program Files\NSIS\makensis.exe" set "MAKENSIS_EXE=C:\Program Files\NSIS\makensis.exe"
if not defined MAKENSIS_EXE (
    where makensis >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('where makensis') do if not defined MAKENSIS_EXE set "MAKENSIS_EXE=%%i"
    )
)

if defined ISCC_EXE (
    echo [+] Detected Inno Setup Compiler: "!ISCC_EXE!"
    echo [*] Compiling installer_inno.iss...
    "!ISCC_EXE!" "%~dp0installer_inno.iss"
    if !errorlevel! equ 0 (
        echo.
        echo =====================================================================
        echo [SUCCESS] Windows Setup Installer successfully created!
        echo Location: "%~dp0Output\ArgusTraffic_Setup.exe"
        echo =====================================================================
        goto :END
    )
)

if defined MAKENSIS_EXE (
    echo [+] Detected NSIS Compiler: "!MAKENSIS_EXE!"
    echo [*] Compiling installer_nsis.nsi...
    "!MAKENSIS_EXE!" "%~dp0installer_nsis.nsi"
    if !errorlevel! equ 0 (
        echo.
        echo =====================================================================
        echo [SUCCESS] Windows Setup Installer successfully created!
        echo Location: "%~dp0Output\ArgusTraffic_Setup.exe"
        echo =====================================================================
        goto :END
    )
)

echo.
echo [!] NOTICE:
echo Neither Inno Setup nor NSIS compiler was detected on this machine.
echo However, your standalone application bundle is 100%% COMPILED and ready at:
echo   "%~dp0dist\ArgusTraffic\"
echo.
echo To build the single "ArgusTraffic_Setup.exe" installer wizard:
echo 1. Download Inno Setup (Free) from: https://jrsoftware.org/isdl.php
echo 2. Run this script again: build_installer.bat
echo    (It will automatically compile Output\ArgusTraffic_Setup.exe)
echo.

:END
pause
