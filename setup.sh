#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo " Molibrary Setup"
echo "============================================================"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

PYTHON=$(command -v python3)
echo "Using Python: $($PYTHON --version)"

# Create virtualenv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv venv
fi

VENV_PY="venv/bin/python"

# Upgrade pip
echo "Upgrading pip..."
"$VENV_PY" -m pip install --upgrade pip -q

# Install dependencies
echo "Installing dependencies..."
if ! "$VENV_PY" -m pip install -r requirements.txt -q; then
    echo "ERROR: Dependency installation failed."
    echo "If RDKit fails, make sure you are using a supported Python version (3.9-3.12)."
    exit 1
fi

# Download offline assets
echo
echo "Downloading offline assets (JSME editor)..."
if ! "$VENV_PY" download_assets.py; then
    echo "WARNING: Asset download had errors. Molibrary will use CDN as fallback."
fi

echo
echo "============================================================"
echo " Setup complete!  Run ./start.sh to launch Molibrary."
echo " The app now works fully offline."
echo "============================================================"
