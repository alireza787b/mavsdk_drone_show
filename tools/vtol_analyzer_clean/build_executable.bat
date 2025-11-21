@echo off
REM ============================================================================
REM VTOL Analyzer - Executable Builder (Windows)
REM
REM This script creates a standalone executable using PyInstaller.
REM
REM Requirements:
REM - Python 3.7+
REM - Virtual environment (run_gui.bat creates this automatically)
REM - PyInstaller (installed automatically by this script)
REM
REM Usage:
REM   build_executable.bat
REM
REM Output:
REM   dist\VTOLAnalyzer.exe - Standalone executable
REM ============================================================================

setlocal enabledelayedexpansion

REM Change to script directory
cd /d "%~dp0"

echo.
echo ================================================================================
echo   VTOL Performance Analyzer - Executable Builder
echo ================================================================================
echo.

REM ============================================================================
REM 1. CHECK VIRTUAL ENVIRONMENT
REM ============================================================================

echo [1/6] Checking virtual environment...

set VENV_DIR=%~dp0venv

if not exist "%VENV_DIR%" (
    echo [WARNING] Virtual environment not found
    echo.
    echo Creating virtual environment first...
    echo Please run: run_gui.bat
    echo.
    echo Or create it manually:
    echo   python -m venv venv
    echo   venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo [OK] Virtual environment found

REM Activate venv
call "%VENV_DIR%\Scripts\activate.bat"
if !errorlevel! neq 0 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)

echo [OK] Virtual environment activated

REM ============================================================================
REM 2. CHECK DEPENDENCIES
REM ============================================================================

echo.
echo [2/6] Checking dependencies...

REM Check if matplotlib and numpy are installed
python -c "import matplotlib, numpy" >nul 2>&1
if !errorlevel! neq 0 (
    echo [WARNING] Dependencies not installed
    echo Installing dependencies...
    pip install -r requirements.txt --quiet >nul 2>&1
)

echo [OK] Dependencies installed

REM ============================================================================
REM 3. INSTALL PYINSTALLER
REM ============================================================================

echo.
echo [3/6] Installing PyInstaller...

python -c "import PyInstaller" >nul 2>&1
if !errorlevel! neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller --quiet

    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install PyInstaller
        pause
        exit /b 1
    )
    echo [OK] PyInstaller installed
) else (
    echo [OK] PyInstaller already installed
)

REM ============================================================================
REM 4. CLEAN PREVIOUS BUILDS
REM ============================================================================

echo.
echo [4/6] Cleaning previous builds...

REM Remove previous build artifacts
if exist "build" (
    rmdir /s /q build
    echo   Removed build\
)

if exist "dist" (
    rmdir /s /q dist
    echo   Removed dist\
)

if exist "VTOLAnalyzer.spec" (
    del /f /q VTOLAnalyzer.spec
    echo   Removed VTOLAnalyzer.spec
)

echo [OK] Clean build environment

REM ============================================================================
REM 5. BUILD EXECUTABLE
REM ============================================================================

echo.
echo [5/6] Building executable with PyInstaller...
echo.
echo This may take 2-5 minutes...
echo.

REM Build with PyInstaller
pyinstaller ^
    --name=VTOLAnalyzer ^
    --onefile ^
    --windowed ^
    --add-data="src;src" ^
    --add-data="examples;examples" ^
    --add-data="requirements.txt;." ^
    --add-data="README.md;." ^
    --add-data="QUICKSTART.md;." ^
    --hidden-import=matplotlib ^
    --hidden-import=numpy ^
    --hidden-import=tkinter ^
    --hidden-import=matplotlib.backends.backend_tkagg ^
    --collect-all matplotlib ^
    --collect-all numpy ^
    --noconfirm ^
    run.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Build failed
    echo.
    echo Common issues:
    echo   1. Missing dependencies - run: pip install -r requirements.txt
    echo   2. Check build\VTOLAnalyzer\*.log for details
    echo   3. Antivirus may block PyInstaller - add exception
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Build completed successfully

REM ============================================================================
REM 6. VERIFY BUILD
REM ============================================================================

echo.
echo [6/6] Verifying build...

set EXECUTABLE=dist\VTOLAnalyzer.exe

if exist "%EXECUTABLE%" (
    REM Get file size
    for %%A in ("%EXECUTABLE%") do set SIZE=%%~zA
    REM Convert to MB
    set /a SIZE_MB=!SIZE! / 1048576
    echo [OK] Executable created: %EXECUTABLE%
    echo   Size: ~!SIZE_MB! MB
) else (
    echo [ERROR] Executable not found
    pause
    exit /b 1
)

REM ============================================================================
REM SUCCESS
REM ============================================================================

echo.
echo ================================================================================
echo [OK] BUILD SUCCESSFUL!
echo ================================================================================
echo.
echo Executable location:
echo   %~dp0%EXECUTABLE%
echo.
echo To run the executable:
echo   %EXECUTABLE%
echo.
echo To distribute:
echo   1. Copy VTOLAnalyzer.exe to target Windows system
echo   2. Double-click to run (no Python required)
echo   3. Allow through Windows Defender if prompted
echo.
echo Notes:
echo   - The executable is standalone (no Python required on target)
echo   - Size is larger (~50-100 MB) due to bundled Python and libraries
echo   - First launch may be slower (unpacking)
echo   - Windows Defender may flag PyInstaller executables (false positive)
echo   - To allow: Windows Security -^> Virus Protection -^> Add exclusion
echo.
echo For more information, see BUILD_EXECUTABLE.md
echo.

REM Offer to test
set /p response="Would you like to test the executable now? (y/n): "

if /i "!response!"=="y" (
    echo.
    echo Testing executable...
    "%EXECUTABLE%" --test
)

echo.
pause
