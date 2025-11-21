@echo off
REM VTOL Analyzer - Quick Launcher (Windows)
REM Double-click to launch GUI

cd /d "%~dp0"

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed
    echo Please install Python 3.7 or later from python.org
    pause
    exit /b 1
)

REM Check dependencies
python -c "import matplotlib" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Launch GUI
echo Starting VTOL Analyzer...
python run.py

REM Keep window open on error
if errorlevel 1 pause
