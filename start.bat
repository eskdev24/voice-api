@echo off
echo ========================================
echo   Buyvia Voice Recognition Service
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt --quiet

REM Check if ffmpeg is available (needed for pydub)
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo.
    echo WARNING: ffmpeg not found. Audio conversion may fail.
    echo Install ffmpeg: https://ffmpeg.org/download.html
    echo Or: winget install ffmpeg
    echo.
)

echo.
echo Starting voice service...
echo.
python server.py

pause
