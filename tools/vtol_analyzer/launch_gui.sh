#!/bin/bash
################################################################################
# VTOL Performance Analyzer v4.0 - GUI Launcher (Linux/macOS)
################################################################################

echo "=========================================="
echo " VTOL Performance Analyzer v4.0"
echo " Professional Edition - GUI"
echo "=========================================="
echo ""

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found!"
    echo "Please install Python 3.7 or higher"
    exit 1
fi

# Check tkinter
python3 -c "import tkinter" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: tkinter not found!"
    echo ""
    echo "Install tkinter:"
    echo "  Ubuntu/Debian: sudo apt-get install python3-tk"
    echo "  macOS: brew install python-tk"
    exit 1
fi

# Check dependencies
echo "Checking dependencies..."
python3 -c "import numpy, matplotlib" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "WARNING: Some dependencies missing"
    echo "Installing from requirements_gui.txt..."
    pip3 install -r requirements_gui.txt
fi

echo ""
echo "Launching GUI..."
python3 vtol_analyzer_gui.py

echo ""
echo "GUI closed."
