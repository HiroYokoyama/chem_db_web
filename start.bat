@echo off
echo Starting ChemDBWeb...

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo Virtual env not found. Run setup.bat first.
    pause
    exit /b 1
)

echo Open http://127.0.0.1:5000 in your browser
echo Press Ctrl+C to stop.
echo.
python app.py
pause
