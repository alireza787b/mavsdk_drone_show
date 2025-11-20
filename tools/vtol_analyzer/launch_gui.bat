@echo off
REM ============================================================================
REM VTOL Performance Analyzer v4.0 - GUI Launcher (Windows)
REM ============================================================================

echo ==========================================
echo  VTOL Performance Analyzer v4.0
echo  Professional Edition - GUI
echo ==========================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.7 or higher from python.org
    pause
    exit /b 1
)

REM Check tkinter
python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo ERROR: tkinter not found!
    echo.
    echo Please reinstall Python with "tcl/tk and IDLE" option checked
    pause
    exit /b 1
)

REM Check dependencies
echo Checking dependencies...
python -c "import numpy, matplotlib" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Some dependencies missing
    echo Installing from requirements_gui.txt...
    pip install -r requirements_gui.txt
)

echo.
echo Launching GUI...
python vtol_analyzer_gui.py

echo.
echo GUI closed.
pause
