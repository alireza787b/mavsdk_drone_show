#!/bin/bash
################################################################################
# VTOL Analyzer - Quick Launcher (Linux/Mac)
#
# This script:
# - Checks for Python 3.7+
# - Creates and manages virtual environment
# - Installs dependencies automatically
# - Launches the GUI application
#
# Double-click to launch or run: ./run_gui.sh
################################################################################

set -e  # Exit on error

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output (if terminal supports it)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    GREEN=''
    YELLOW=''
    RED=''
    BLUE=''
    NC=''
fi

echo ""
echo "================================================================================"
echo "  VTOL Performance Analyzer v4.1.2 - Quick Launcher"
echo "================================================================================"
echo ""

################################################################################
# 1. CHECK PYTHON INSTALLATION
################################################################################

echo -e "${BLUE}[1/5] Checking Python installation...${NC}"

# Try to find Python 3
PYTHON_CMD=""
for cmd in python3.11 python3.10 python3.9 python3.8 python3.7 python3; do
    if command -v $cmd &> /dev/null; then
        # Check version
        VERSION=$($cmd --version 2>&1 | grep -oP '(?<=Python )\d+\.\d+' || echo "0.0")
        MAJOR=$(echo $VERSION | cut -d. -f1)
        MINOR=$(echo $VERSION | cut -d. -f2)

        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 7 ]; then
            PYTHON_CMD=$cmd
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}✗ Python 3.7+ not found${NC}"
    echo ""
    echo "Please install Python 3.7 or later:"
    echo ""

    # OS-specific instructions
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS:"
        echo "    1. Download from: https://www.python.org/downloads/"
        echo "    2. Or install via Homebrew: brew install python3"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "  Linux:"
        if command -v apt-get &> /dev/null; then
            echo "    sudo apt-get update"
            echo "    sudo apt-get install python3 python3-pip python3-venv python3-tk"
        elif command -v yum &> /dev/null; then
            echo "    sudo yum install python3 python3-pip python3-tkinter"
        elif command -v dnf &> /dev/null; then
            echo "    sudo dnf install python3 python3-pip python3-tkinter"
        else
            echo "    Use your package manager to install python3"
        fi
    fi
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '(?<=Python )\d+\.\d+\.\d+' || echo "unknown")
echo -e "${GREEN}✓ Found Python $PYTHON_VERSION at $PYTHON_CMD${NC}"

################################################################################
# 2. CHECK/CREATE VIRTUAL ENVIRONMENT
################################################################################

echo ""
echo -e "${BLUE}[2/5] Setting up virtual environment...${NC}"

VENV_DIR="$SCRIPT_DIR/venv"

if [ -d "$VENV_DIR" ]; then
    echo -e "${GREEN}✓ Virtual environment already exists${NC}"
else
    echo "Creating virtual environment..."

    # Check if venv module is available
    if ! $PYTHON_CMD -m venv --help &> /dev/null; then
        echo -e "${RED}✗ Python venv module not found${NC}"
        echo ""
        echo "Please install python3-venv:"
        if command -v apt-get &> /dev/null; then
            echo "  sudo apt-get install python3-venv"
        elif command -v yum &> /dev/null; then
            echo "  sudo yum install python3-venv"
        fi
        echo ""
        read -p "Press Enter to exit..."
        exit 1
    fi

    $PYTHON_CMD -m venv "$VENV_DIR"
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

################################################################################
# 3. ACTIVATE VIRTUAL ENVIRONMENT
################################################################################

echo ""
echo -e "${BLUE}[3/5] Activating virtual environment...${NC}"

# Activate venv
source "$VENV_DIR/bin/activate"

# Verify activation
if [ "$VIRTUAL_ENV" != "" ]; then
    echo -e "${GREEN}✓ Virtual environment activated${NC}"
else
    echo -e "${RED}✗ Failed to activate virtual environment${NC}"
    read -p "Press Enter to exit..."
    exit 1
fi

################################################################################
# 4. INSTALL/UPDATE DEPENDENCIES
################################################################################

echo ""
echo -e "${BLUE}[4/5] Checking dependencies...${NC}"

# Check if requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}✗ requirements.txt not found${NC}"
    read -p "Press Enter to exit..."
    exit 1
fi

# Check if packages are already installed
NEEDS_INSTALL=0

# Check for matplotlib (key dependency)
if ! python -c "import matplotlib" 2>/dev/null; then
    NEEDS_INSTALL=1
fi

# Check for numpy
if ! python -c "import numpy" 2>/dev/null; then
    NEEDS_INSTALL=1
fi

if [ $NEEDS_INSTALL -eq 1 ]; then
    echo "Installing dependencies..."

    # Upgrade pip first
    python -m pip install --upgrade pip --quiet

    # Install requirements
    python -m pip install -r requirements.txt --quiet

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Dependencies installed successfully${NC}"
    else
        echo -e "${RED}✗ Failed to install dependencies${NC}"
        echo ""
        echo "Try installing manually:"
        echo "  source venv/bin/activate"
        echo "  pip install -r requirements.txt"
        echo ""
        read -p "Press Enter to exit..."
        exit 1
    fi
else
    echo -e "${GREEN}✓ All dependencies already installed${NC}"
fi

################################################################################
# 5. LAUNCH APPLICATION
################################################################################

echo ""
echo -e "${BLUE}[5/5] Launching VTOL Analyzer...${NC}"
echo ""
echo "================================================================================"
echo ""

# Launch the application
python run.py

# Capture exit code
EXIT_CODE=$?

echo ""
echo "================================================================================"

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Application closed successfully${NC}"
else
    echo -e "${YELLOW}⚠ Application exited with code $EXIT_CODE${NC}"
    echo ""
    echo "If you encountered errors, try:"
    echo "  1. Delete the venv folder and run this script again"
    echo "  2. Check README.md for troubleshooting"
    echo "  3. Run: python run.py --test"
    echo ""
    read -p "Press Enter to exit..."
fi

echo ""
