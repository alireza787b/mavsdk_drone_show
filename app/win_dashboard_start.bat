@echo off
REM ============================================
REM Drone Services Launcher for Windows
REM ============================================
REM This script manages the execution of the GUI React App and GCS Server
REM on Windows. It handles port conflicts and opens separate terminal
REM windows for each service.
REM ============================================
REM Usage:
REM   Double-click win_dashboard_start.bat or run it from a command prompt
REM ============================================

set SESSION_NAME=DroneServices
set GCS_PORT=5000
set GUI_PORT=3000
set WAIT_TIME=10   REM Wait time (in seconds) between retries
set RETRY_LIMIT=10 REM Maximum number of retries to free ports

REM Function to check if a port is in use
:port_in_use
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%1') do (
    set PID=%%a
)
if defined PID (
    exit /b 0
) else (
    exit /b 1
)

REM Function to kill a process using a specific port
:force_kill_port
setlocal enabledelayedexpansion
set /a retries=0

:retry_kill
call :port_in_use %1
if %errorlevel%==0 (
    echo Killing process using port %1 with PID: !PID!
    taskkill /F /PID !PID! >nul 2>&1
    if %errorlevel%==0 (
        echo Successfully killed process !PID! on port %1.
    ) else (
        echo Failed to kill process !PID! on port %1.
    )
) else (
    echo Port %1 is now free.
    goto end_kill
)

REM Wait and retry if the port is still in use
timeout /t %WAIT_TIME% /nobreak >nul
set /a retries+=1

if !retries! geq %RETRY_LIMIT% (
    echo Error: Unable to free port %1 after %RETRY_LIMIT% attempts.
    exit /b 1
)

echo Port %1 is still in use. Retrying... (!retries!/%RETRY_LIMIT%)
goto retry_kill

:end_kill
endlocal
exit /b 0

REM Main Script Execution

echo ============================================
echo Checking if ports are in use...
echo ============================================

call :force_kill_port %GCS_PORT%
if %errorlevel% neq 0 exit /b 1
call :force_kill_port %GUI_PORT%
if %errorlevel% neq 0 exit /b 1

echo ============================================
echo Waiting for ports to fully release...
timeout /t %WAIT_TIME% /nobreak >nul
echo ============================================

REM Launch GCS Server in a new terminal window
start "GCS-Server" powershell -NoExit -Command "cd %cd%\..\gcs-server; ./venv/Scripts/activate; python app.py"

REM Launch GUI React App in a new terminal window
start "GUI-React" powershell -NoExit -Command "cd %cd%\dashboard\drone-dashboard; ./venv/Scripts/activate; npm start"

REM Display user instructions
echo ============================================
echo All Drone Services components have been started successfully!
echo You can close each terminal window to stop the respective service.
echo ============================================

pause
exit /b 0
