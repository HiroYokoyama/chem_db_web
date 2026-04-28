@echo off
echo ============================================================
echo  Molibrary Setup
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

:: Install with the venv interpreter directly so pip upgrades itself in-place.
echo Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip -q
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip inside the virtual environment.
    pause
    exit /b 1
)

venv\Scripts\python.exe -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    echo If RDKit fails, confirm the virtual environment was created with a supported Python build.
    pause
    exit /b 1
)

echo.
echo Downloading offline assets (JSME editor)...
venv\Scripts\python.exe download_assets.py
if errorlevel 1 (
    echo WARNING: Asset download had errors. Molibrary will use CDN as fallback.
)

echo.
echo ============================================================
echo  Setup complete!  Run start.bat to launch Molibrary.
echo  The app now works fully offline.
echo ============================================================
pause
