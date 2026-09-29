"""
ArgusTraffic AI - Native Desktop Command Center Application
Launches an integrated, hardware-accelerated desktop window with embedded
vision backend, auto-start supervisor, and zero-configuration runtime.
"""

import ctypes
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

# Ensure project root in sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Register Windows AppUserModelID for taskbar icon
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ArgusTraffic.AutonomousSystems.CommandCenter.2.0")
    except Exception:
        pass

# In GUI mode (console=False on Windows), sys.stdout and sys.stderr are None.
class SafeStream:
    def write(self, s):
        pass
    def flush(self):
        pass
    def isatty(self):
        return False

if sys.stdout is None:
    sys.stdout = SafeStream()
if sys.stderr is None:
    sys.stderr = SafeStream()

# Configure persistent file logging
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArgusTraffic"
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE = LOG_DIR / "argustraffic.log"
except Exception:
    LOG_FILE = BASE_DIR / "argustraffic.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="a"),
    ],
)
logger = logging.getLogger("argustraffic.desktop")

# Configure isolated WebView2 profile to avoid COM lock conflicts
WEBVIEW2_PROFILE_DIR = LOG_DIR / "webview2_profile"
try:
    WEBVIEW2_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(WEBVIEW2_PROFILE_DIR)
except Exception:
    pass

PORT = 8080
SERVER_URL = f"http://127.0.0.1:{PORT}"
server_error_detail = None
_mutex_handle = None


def enforce_single_instance() -> bool:
    """Enforces single application instance using a Windows Named Mutex."""
    global _mutex_handle
    if sys.platform != "win32":
        return True

    try:
        MUTEX_NAME = "Global\\ArgusTraffic_AI_SingleInstance_Mutex_v2"
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            logger.info("Active ArgusTraffic AI instance detected. Redirecting to active session...")
            webbrowser.open(SERVER_URL)
            return False
    except Exception as e:
        logger.warning(f"Single-instance check warning: {e}")
    return True


def show_error_dialog(title: str, message: str):
    """Displays a native Windows error dialog if GUI or server fails."""
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:
        print(f"[{title}] {message}", file=sys.stderr)


def is_server_running(url: str = None) -> bool:
    target = url or SERVER_URL
    try:
        req = urllib.request.Request(f"{target}/api/v1/health", headers={"User-Agent": "ArgusTraffic-Watchdog"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_server_port() -> int:
    """Checks if server is already running on 8080 or finds the next available port."""
    global PORT, SERVER_URL

    if is_server_running(f"http://127.0.0.1:8080"):
        PORT = 8080
        SERVER_URL = f"http://127.0.0.1:{PORT}"
        return PORT

    for p in [8080, 8081, 8082, 8085]:
        if is_server_running(f"http://127.0.0.1:{p}"):
            PORT = p
            SERVER_URL = f"http://127.0.0.1:{PORT}"
            return PORT
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                PORT = p
                SERVER_URL = f"http://127.0.0.1:{PORT}"
                return PORT

    PORT = 8080
    SERVER_URL = f"http://127.0.0.1:{PORT}"
    return PORT


def run_backend_server(port: int):
    """Runs uvicorn in an embedded background thread."""
    global server_error_detail
    try:
        import uvicorn
        from src.api.app import app
        logger.info(f"Starting embedded vision server on port {port}...")
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", log_config=None)
    except Exception as e:
        server_error_detail = traceback.format_exc()
        logger.error(f"Backend vision server error: {e}", exc_info=True)


def main():
    logger.info("=" * 65)
    logger.info("   ARGUSTRAFFIC AI - ENTERPRISE DESKTOP PLATFORM   ")
    logger.info("=" * 65)

    # 1. Enforce single application instance
    if not enforce_single_instance():
        sys.exit(0)

    # 2. Resolve server port
    target_port = resolve_server_port()
    logger.info(f"Resolved target backend URL: {SERVER_URL}")

    # 3. Start backend server if not already running
    if not is_server_running():
        server_thread = threading.Thread(target=run_backend_server, args=(target_port,), daemon=True)
        server_thread.start()

        # Wait for backend to be online (up to 60 seconds for neural network warm-up)
        logger.info("Waiting for local vision engine and neural network to initialize...")
        server_ready = False
        for i in range(120):  # 120 * 0.5s = 60s max
            if is_server_running():
                server_ready = True
                logger.info("[READY] Backend vision engine is online.")
                break
            if not server_thread.is_alive():
                logger.error("Backend server thread terminated unexpectedly.")
                break
            time.sleep(0.5)

        if not server_ready:
            err_msg = (
                "ArgusTraffic AI local vision engine failed to start.\n\n"
                f"Details: {server_error_detail or 'Server did not respond in time.'}\n\n"
                f"Log file: {LOG_FILE}"
            )
            logger.error(err_msg)
            show_error_dialog("ArgusTraffic AI - Startup Error", err_msg)
            return

    # 4. Launch Native Desktop Window using pywebview with safe browser fallback
    try:
        import webview

        logger.info("Launching native desktop command center window...")
        window = webview.create_window(
            title="ArgusTraffic AI - Enterprise Autonomous Vision Command Center",
            url=SERVER_URL,
            width=1440,
            height=900,
            min_size=(1024, 700),
            confirm_close=True,
            text_select=True,
            resizable=True,
        )
        webview.start(debug=False)
        logger.info("Desktop window closed by user. Exiting cleanly.")
    except Exception as e:
        logger.warning(f"Native desktop window unavailable ({e}). Opening in default web browser...")
        webbrowser.open(SERVER_URL)
        print("=" * 70)
        print("   ARGUSTRAFFIC AI - RUNNING IN YOUR DEFAULT BROWSER   ")
        print(f"   URL: {SERVER_URL}")
        print("   Press Ctrl+C to stop the application.")
        print("=" * 70)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Exiting...")


if __name__ == "__main__":
    main()
