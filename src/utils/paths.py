"""
ArgusTraffic AI - Enterprise Storage & Runtime Path Manager
Resolves robust, cross-platform, privilege-safe directories for application
databases, configuration caches, and forensic evidence stores.
"""

import logging
import os
from pathlib import Path
import sys

logger = logging.getLogger("argustraffic.paths")


def get_data_dir() -> Path:
    """
    Returns a privilege-safe, writable directory for SQLite databases and runtime artifacts.
    - When installed in 'C:\\Program Files' as a frozen PyInstaller executable, uses
      '%LOCALAPPDATA%\\ArgusTraffic\\data' to guarantee standard user write access without UAC elevation.
    - In local dev environments, defaults to repository root '/data' if writable.
    - Automatically falls back to user profile if repository directory is read-only.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")

    if getattr(sys, "frozen", False) and local_app_data:
        target_dir = Path(local_app_data) / "ArgusTraffic" / "data"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    # Try local repository 'data' folder for development/testing
    repo_data = Path(__file__).resolve().parent.parent.parent / "data"
    try:
        repo_data.mkdir(parents=True, exist_ok=True)
        test_file = repo_data / ".write_test"
        test_file.touch()
        test_file.unlink()
        return repo_data
    except (PermissionError, OSError):
        if local_app_data:
            target_dir = Path(local_app_data) / "ArgusTraffic" / "data"
        else:
            target_dir = Path.home() / ".argustraffic" / "data"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir
