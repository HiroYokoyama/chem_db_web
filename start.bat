@echo off
echo Starting Molibrary...

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo Virtual env not found. Run setup.bat first.
    pause
    exit /b 1
)

echo.
echo Molibrary is starting...
echo Use --localhost flag to restrict access to this PC only.
echo.
python molibrary/app.py %*
pause
