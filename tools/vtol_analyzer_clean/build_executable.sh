#!/bin/bash
################################################################################
# VTOL Analyzer - Executable Builder (Linux/macOS)
#
# This script creates a standalone executable using PyInstaller.
#
# Requirements:
# - Python 3.7+
# - Virtual environment (run_gui.sh creates this automatically)
# - PyInstaller (installed automatically by this script)
#
# Usage:
#   ./build_executable.sh
#
# Output:
#   dist/VTOLAnalyzer - Standalone executable
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
echo "  VTOL Performance Analyzer - Executable Builder"
echo "================================================================================"
echo ""

################################################################################
# 1. CHECK VIRTUAL ENVIRONMENT
################################################################################

echo -e "${BLUE}[1/6] Checking virtual environment...${NC}"

VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}⚠ Virtual environment not found${NC}"
    echo ""
    echo "Creating virtual environment first..."
    echo "Please run: ./run_gui.sh"
    echo ""
    echo "Or create it manually:"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo -e "${GREEN}✓ Virtual environment found${NC}"

# Activate venv
source "$VENV_DIR/bin/activate"

if [ "$VIRTUAL_ENV" == "" ]; then
    echo -e "${RED}✗ Failed to activate virtual environment${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Virtual environment activated${NC}"

################################################################################
# 2. CHECK DEPENDENCIES
################################################################################

echo ""
echo -e "${BLUE}[2/6] Checking dependencies...${NC}"

# Check if matplotlib and numpy are installed
if ! python -c "import matplotlib, numpy" 2>/dev/null; then
    echo -e "${YELLOW}⚠ Dependencies not installed${NC}"
    echo "Installing dependencies..."
    pip install -r requirements.txt --quiet
fi

echo -e "${GREEN}✓ Dependencies installed${NC}"

################################################################################
# 3. INSTALL PYINSTALLER
################################################################################

echo ""
echo -e "${BLUE}[3/6] Installing PyInstaller...${NC}"

if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller --quiet

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to install PyInstaller${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ PyInstaller installed${NC}"
else
    echo -e "${GREEN}✓ PyInstaller already installed${NC}"
fi

################################################################################
# 4. CLEAN PREVIOUS BUILDS
################################################################################

echo ""
echo -e "${BLUE}[4/6] Cleaning previous builds...${NC}"

# Remove previous build artifacts
if [ -d "build" ]; then
    rm -rf build
    echo "  Removed build/"
fi

if [ -d "dist" ]; then
    rm -rf dist
    echo "  Removed dist/"
fi

if [ -f "VTOLAnalyzer.spec" ]; then
    rm -f VTOLAnalyzer.spec
    echo "  Removed VTOLAnalyzer.spec"
fi

echo -e "${GREEN}✓ Clean build environment${NC}"

################################################################################
# 5. BUILD EXECUTABLE
################################################################################

echo ""
echo -e "${BLUE}[5/6] Building executable with PyInstaller...${NC}"
echo ""
echo "This may take 2-5 minutes..."
echo ""

# Build with PyInstaller
pyinstaller \
    --name=VTOLAnalyzer \
    --onefile \
    --windowed \
    --add-data="src:src" \
    --add-data="examples:examples" \
    --add-data="requirements.txt:." \
    --add-data="README.md:." \
    --add-data="QUICKSTART.md:." \
    --hidden-import=matplotlib \
    --hidden-import=numpy \
    --hidden-import=tkinter \
    --hidden-import=matplotlib.backends.backend_tkagg \
    --collect-all matplotlib \
    --collect-all numpy \
    --noconfirm \
    run.py

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}✗ Build failed${NC}"
    echo ""
    echo "Common issues:"
    echo "  1. Missing dependencies - run: pip install -r requirements.txt"
    echo "  2. Tkinter not installed - install python3-tk"
    echo "  3. Check build/VTOLAnalyzer/*.log for details"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Build completed successfully${NC}"

################################################################################
# 6. VERIFY BUILD
################################################################################

echo ""
echo -e "${BLUE}[6/6] Verifying build...${NC}"

EXECUTABLE=""
if [[ "$OSTYPE" == "darwin"* ]]; then
    EXECUTABLE="dist/VTOLAnalyzer"
else
    EXECUTABLE="dist/VTOLAnalyzer"
fi

if [ -f "$EXECUTABLE" ]; then
    SIZE=$(du -h "$EXECUTABLE" | cut -f1)
    echo -e "${GREEN}✓ Executable created: $EXECUTABLE${NC}"
    echo "  Size: $SIZE"
else
    echo -e "${RED}✗ Executable not found${NC}"
    exit 1
fi

################################################################################
# SUCCESS
################################################################################

echo ""
echo "================================================================================"
echo -e "${GREEN}✓ BUILD SUCCESSFUL!${NC}"
echo "================================================================================"
echo ""
echo "Executable location:"
echo "  $SCRIPT_DIR/$EXECUTABLE"
echo ""
echo "To run the executable:"
echo "  ./$EXECUTABLE"
echo ""
echo "To distribute:"
echo "  1. Copy the executable to target system"
echo "  2. Make executable: chmod +x VTOLAnalyzer"
echo "  3. Run: ./VTOLAnalyzer"
echo ""
echo "Notes:"
echo "  - The executable is standalone (no Python required on target)"
echo "  - Size is larger due to bundled Python runtime and libraries"
echo "  - First launch may be slower (unpacking)"
echo "  - Some antivirus software may flag PyInstaller executables"
echo ""
echo "For more information, see BUILD_EXECUTABLE.md"
echo ""

# Offer to test
echo -n "Would you like to test the executable now? (y/n): "
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Testing executable..."
    ./$EXECUTABLE --test
fi

echo ""
