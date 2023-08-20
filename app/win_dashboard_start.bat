@echo off
cls

echo Welcome to the Drone Dashboard and GCS Terminal App Startup Script!
echo MAVSDK_Drone_Show Version 0.8
echo.
echo This script will do the following:
echo 1. Check if the Drone Dashboard (a Node.js React app) is running.
echo 2. If not, it will start the Drone Dashboard. Once started, you can access the dashboard at http://localhost:3000 (can also be done manually with npm start command)
echo 3. The script will also open the terminal-based GCS (Ground Control Station) app. This GCS app serves data to the Drone Dashboard using Flask endpoints + ability to send command and receive telemetry from drones using terminal.
echo 4. Start the getElevation server that acts as a proxy for fetching elevation data.
echo.
echo Please wait as the script checks and initializes the necessary components...
echo.

REM Get the directory of the current script
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%\..


REM Check if the Drone Dashboard server is running
powershell -Command "try { $response = Invoke-WebRequest -Uri http://localhost:3000 -UseBasicParsing -ErrorAction Stop; exit 0 } catch { exit 1 }"

IF %ERRORLEVEL% NEQ 0 (
    echo Starting the Drone Dashboard server...
    cd "%SCRIPT_DIR%\dashboard\drone-dashboard"
    start cmd /k npm start
    echo Drone Dashboard server started successfully!
) ELSE (
    echo Drone Dashboard server is already running!
)

REM Check if the getElevation server is running
powershell -Command "try { $response = Invoke-WebRequest -Uri http://localhost:5001 -UseBasicParsing -ErrorAction Stop; exit 0 } catch { exit 1 }"

IF %ERRORLEVEL% NEQ 0 (
    echo Starting the getElevation server...
    cd "%SCRIPT_DIR%\dashboard\getElevation"
    start cmd /k node server.js
    echo getElevation server started successfully!
) ELSE (
    echo getElevation server is already running!
)

echo Now starting the GCS Terminal App with Flask...
cd "%REPO_ROOT%"
start cmd /k python gcs_with_flask.py
echo GCS Terminal App started successfully!

echo.
echo For more details, please check the documentation in the 'docs' folder.
echo You can also refer to GitHub repo: https://github.com/alireza787b/mavsdk_drone_show
echo For tutorials and additional content, visit Alireza Ghaderi's YouTube channel: https://www.youtube.com/@alirezaghaderi
echo.
echo Press any key to close this script...
pause
