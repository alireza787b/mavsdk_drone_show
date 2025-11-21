@echo off
REM ============================================================================
REM VTOL Analyzer - Quick Launcher (Windows)
REM
REM This script:
REM - Checks for Python 3.7+
REM - Creates and manages virtual environment
REM - Installs dependencies automatically
REM - Launches the GUI application
REM
REM Double-click to launch or run: run_gui.bat
REM ============================================================================

setlocal enabledelayedexpansion

REM Change to script directory
cd /d "%~dp0"

echo.
echo ================================================================================
echo   VTOL Performance Analyzer v4.1.2 - Quick Launcher
echo ================================================================================
echo.

REM ============================================================================
REM 1. CHECK PYTHON INSTALLATION
REM ============================================================================

echo [1/5] Checking Python installation...

REM Try to find Python 3
set PYTHON_CMD=
set PYTHON_VERSION=

REM Try common Python commands
for %%P in (python python3 py) do (
    %%P --version >nul 2>&1
    if !errorlevel! equ 0 (
        REM Get version
        for /f "tokens=2" %%v in ('%%P --version 2^>^&1') do (
            set PYTHON_VERSION=%%v
            REM Extract major.minor version
            for /f "tokens=1,2 delims=." %%a in ("!PYTHON_VERSION!") do (
                set MAJOR=%%a
                set MINOR=%%b
                REM Check if version is 3.7+
                if !MAJOR! geq 3 (
                    if !MINOR! geq 7 (
                        set PYTHON_CMD=%%P
                        goto :python_found
                    )
                )
            )
        )
    )
)

:python_found
if "!PYTHON_CMD!"=="" (
    echo [ERROR] Python 3.7+ not found
    echo.
    echo Please install Python 3.7 or later:
    echo   1. Download from: https://www.python.org/downloads/
    echo   2. During installation, CHECK "Add Python to PATH"
    echo   3. Restart this script after installation
    echo.
    pause
    exit /b 1
)

echo [OK] Found Python !PYTHON_VERSION! at !PYTHON_CMD!

REM ============================================================================
REM 2. CHECK/CREATE VIRTUAL ENVIRONMENT
REM ============================================================================

echo.
echo [2/5] Setting up virtual environment...

set VENV_DIR=%~dp0venv

if exist "%VENV_DIR%" (
    echo [OK] Virtual environment already exists
) else (
    echo Creating virtual environment...

    REM Create venv
    !PYTHON_CMD! -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment
        echo.
        echo Make sure you have the full Python installation including venv
        echo.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

REM ============================================================================
REM 3. ACTIVATE VIRTUAL ENVIRONMENT
REM ============================================================================

echo.
echo [3/5] Activating virtual environment...

REM Activate venv
call "%VENV_DIR%\Scripts\activate.bat"
if !errorlevel! neq 0 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)

echo [OK] Virtual environment activated

REM ============================================================================
REM 4. INSTALL/UPDATE DEPENDENCIES
REM ============================================================================

echo.
echo [4/5] Checking dependencies...

REM Check if requirements.txt exists
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found
    pause
    exit /b 1
)

REM Check if packages are already installed
set NEEDS_INSTALL=0

REM Check for matplotlib (key dependency)
python -c "import matplotlib" >nul 2>&1
if !errorlevel! neq 0 (
    set NEEDS_INSTALL=1
)

REM Check for numpy
python -c "import numpy" >nul 2>&1
if !errorlevel! neq 0 (
    set NEEDS_INSTALL=1
)

if !NEEDS_INSTALL! equ 1 (
    echo Installing dependencies...

    REM Upgrade pip first
    python -m pip install --upgrade pip --quiet >nul 2>&1

    REM Install requirements
    python -m pip install -r requirements.txt --quiet
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install dependencies
        echo.
        echo Try installing manually:
        echo   1. Open Command Prompt
        echo   2. cd "%~dp0"
        echo   3. venv\Scripts\activate
        echo   4. pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed successfully
) else (
    echo [OK] All dependencies already installed
)

REM ============================================================================
REM 5. LAUNCH APPLICATION
REM ============================================================================

echo.
echo [5/5] Launching VTOL Analyzer...
echo.
echo ================================================================================
echo.

REM Launch the application
python run.py

REM Capture exit code
set EXIT_CODE=!errorlevel!

echo.
echo ================================================================================

if !EXIT_CODE! equ 0 (
    echo [OK] Application closed successfully
) else (
    echo [WARNING] Application exited with code !EXIT_CODE!
    echo.
    echo If you encountered errors, try:
    echo   1. Delete the venv folder and run this script again
    echo   2. Check README.md for troubleshooting
    echo   3. Run: python run.py --test
    echo.
    pause
)

echo.
