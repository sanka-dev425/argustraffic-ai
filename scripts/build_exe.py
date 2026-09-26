"""
ArgusTraffic AI - Enterprise Executable (.exe) & Installer Builder
Automates PyInstaller bundling of the desktop application, neural weights,
static web assets, and runtime dependencies.
Usage:
    python scripts/build_exe.py
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent.parent


def build_executable():
    print("=" * 65)
    print("   ARGUSTRAFFIC AI - WINDOWS EXECUTABLE COMPILER (.EXE)   ")
    print("=" * 65)

    dist_dir = BASE_DIR / "dist"
    build_dir = BASE_DIR / "build"

    # PyInstaller command
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        "ArgusTraffic",
        "--add-data",
        f"{BASE_DIR / 'src' / 'web'}{os.pathsep}src/web",
        "--add-data",
        f"{BASE_DIR / 'configs'}{os.pathsep}configs",
        "--add-data",
        f"{BASE_DIR / 'yolov8n.pt'}{os.pathsep}.",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols",
        "--hidden-import",
        "uvicorn.protocols.http",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespans",
        "--hidden-import",
        "uvicorn.lifespans.on",
        str(BASE_DIR / "desktop_app.py"),
    ]

    print(f"[+] Compiling standalone desktop binary with PyInstaller...")
    print(f"[+] Output will be generated at: {dist_dir / 'ArgusTraffic' / 'ArgusTraffic.exe'}")
    print("\nExecuting build command...")

    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode == 0:
        print("\n" + "=" * 65)
        print("✓ COMPILATION SUCCESSFUL!")
        print(f"✓ Standalone Desktop App generated: {dist_dir / 'ArgusTraffic' / 'ArgusTraffic.exe'}")
        print("=" * 65)
    else:
        print("\n[!] Build completed with return code:", res.returncode)


if __name__ == "__main__":
    build_executable()
