#!/bin/bash
# VTOL Analyzer - Quick Launcher (Linux/Mac)
# Double-click to launch GUI

cd "$(dirname "$0")"

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3.7 or later"
    read -p "Press Enter to exit..."
    exit 1
fi

# Check dependencies
python3 -c "import matplotlib" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

# Launch GUI
echo "Starting VTOL Analyzer..."
python3 run.py

# Keep terminal open on error
if [ $? -ne 0 ]; then
    read -p "Press Enter to exit..."
fi
