@echo off
echo ============================================================
echo  ChemDB Setup
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Create virtualenv
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate and install
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install flask rdkit-pypi werkzeug -q

echo.
echo ============================================================
echo  Setup complete!  Run start.bat to launch ChemDBWeb.
echo ============================================================
pause
