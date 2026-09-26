#!/usr/bin/env bash
set -e

echo "====================================================================="
echo "          ARGUSTRAFFIC AI - ENTERPRISE ZERO-CLICK INSTALLER"
echo "     World Top-Tier Autonomous Incident & Traffic Vision Platform"
echo "====================================================================="
echo ""

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3.10+ is required but not found."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[+] Detected Python version: $PY_VER"

# 2. Virtual Environment
if [ ! -d ".venv" ]; then
    echo "[+] Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

echo "[+] Activating virtual environment..."
source .venv/bin/activate

# 3. Dependencies
echo "[+] Installing and updating dependencies..."
pip install --quiet --upgrade pip setuptools wheel
pip install --quiet -r requirements.txt
pip install --quiet -e .

# 4. Hardware Diagnostics
echo ""
echo "====================================================================="
echo "[+] Hardware Diagnostics:"
python3 -c "import torch; print('    - PyTorch:', torch.__version__); print('    - CUDA Available:', torch.cuda.is_available()); print('    - Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'High-Performance CPU');"
echo "====================================================================="
echo ""

# 5. Launch
echo "[+] Starting ArgusTraffic AI at http://localhost:8080 ..."
python3 -m uvicorn src.api.app:app --host 0.0.0.0 --port 8080
