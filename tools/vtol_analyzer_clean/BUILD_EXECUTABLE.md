# Building Standalone Executables

This guide explains how to create standalone executables for VTOL Analyzer that can run on systems without Python installed.

---

## Quick Start

### Windows
```cmd
build_executable.bat
```

### Linux/macOS
```bash
chmod +x build_executable.sh
./build_executable.sh
```

That's it! The script handles everything automatically.

---

## What Gets Created

### Windows
- **Output:** `dist\VTOLAnalyzer.exe` (~50-100 MB)
- **Standalone:** No Python required on target system
- **Double-click to run**

### Linux
- **Output:** `dist/VTOLAnalyzer` (~80-150 MB)
- **Standalone:** No Python required on target system
- **Run:** `./VTOLAnalyzer`

### macOS
- **Output:** `dist/VTOLAnalyzer` (~80-150 MB)
- **Standalone:** No Python required on target system
- **Run:** `./VTOLAnalyzer` or double-click in Finder

---

## Prerequisites

### What You Need

1. **Python 3.7+** installed on BUILD system (not target system)
2. **Virtual environment** created (run `run_gui.sh` or `run_gui.bat` first)
3. **Dependencies** installed (automatic)
4. **PyInstaller** (installed automatically by build script)

### First-Time Setup

Before building, ensure the application works:

**Windows:**
```cmd
run_gui.bat
```

**Linux/macOS:**
```bash
./run_gui.sh
```

This creates the virtual environment and installs all dependencies.

---

## Building Process

### Automatic Build

The build scripts handle everything automatically:

1. ✓ Check virtual environment exists
2. ✓ Activate virtual environment
3. ✓ Install PyInstaller if needed
4. ✓ Clean previous builds
5. ✓ Build executable with PyInstaller
6. ✓ Verify build succeeded

### Build Time

- **First build:** 2-5 minutes (downloads and bundles Python runtime)
- **Subsequent builds:** 1-3 minutes (reuses cached files)

### What Gets Bundled

The executable includes:
- Python 3 runtime
- All required libraries (matplotlib, numpy, tkinter)
- Source code (src/ folder)
- Examples (examples/ folder)
- Documentation (README.md, QUICKSTART.md)

---

## Distribution

### Distributing to Other Systems

**Windows:**
1. Copy `dist\VTOLAnalyzer.exe` to target Windows PC
2. Double-click to run
3. If Windows Defender blocks: Add exclusion (see Troubleshooting)

**Linux:**
1. Copy `dist/VTOLAnalyzer` to target Linux system
2. Make executable: `chmod +x VTOLAnalyzer`
3. Run: `./VTOLAnalyzer`

**macOS:**
1. Copy `dist/VTOLAnalyzer` to target Mac
2. Make executable: `chmod +x VTOLAnalyzer`
3. Run: `./VTOLAnalyzer`
4. If Gatekeeper blocks: Right-click → Open → Open anyway

### System Requirements for Target System

- **Windows:** Windows 7 or later (64-bit)
- **Linux:** Most modern distributions (64-bit, glibc 2.17+)
- **macOS:** macOS 10.13 (High Sierra) or later

**No Python required on target system!**

---

## Advanced Options

### Custom Build Configuration

Edit the PyInstaller command in the build script to customize:

```bash
pyinstaller \
    --name=VTOLAnalyzer \
    --onefile \                    # Single file (vs --onedir for folder)
    --windowed \                   # No console window
    --add-data="src:src" \         # Include data files
    --hidden-import=matplotlib \   # Explicitly include modules
    --icon=icon.ico \              # Add custom icon (if you have one)
    run.py
```

### Create Icon (Optional)

To add a custom icon:

1. Create `icon.ico` (Windows) or `icon.icns` (macOS)
2. Place in project root
3. Edit build script, change:
   ```bash
   --icon=icon.ico \
   ```

### Build for Specific Python Version

The executable uses the Python version from your venv:

```bash
# Use specific Python version
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./build_executable.sh
```

---

## Troubleshooting

### Build Fails - Missing Dependencies

**Problem:** `ModuleNotFoundError during build`

**Solution:**
```bash
# Linux/macOS
source venv/bin/activate
pip install -r requirements.txt
./build_executable.sh

# Windows
venv\Scripts\activate
pip install -r requirements.txt
build_executable.bat
```

### Build Fails - Tkinter Not Found

**Problem:** `No module named '_tkinter'`

**Solution:**

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install python3-tk
```

**Linux (Fedora/RHEL):**
```bash
sudo dnf install python3-tkinter
```

**macOS:**
```bash
brew install python-tk
```

**Windows:** Tkinter is included with Python - reinstall Python and check "tcl/tk" option

### Executable Won't Run - Windows Defender

**Problem:** Windows Defender blocks or deletes executable

**Reason:** PyInstaller executables sometimes trigger false positives

**Solution:**
1. Open Windows Security
2. Virus & threat protection
3. Manage settings → Exclusions
4. Add exclusion → Folder
5. Add `dist` folder

### Executable Won't Run - macOS Gatekeeper

**Problem:** "App is damaged and can't be opened"

**Solution:**
```bash
# Remove quarantine attribute
xattr -d com.apple.quarantine VTOLAnalyzer

# Or: Right-click → Open → Open Anyway
```

### Executable is Very Large

**Normal:** Executables are 50-150 MB because they include:
- Python runtime (~30 MB)
- Matplotlib (~20 MB)
- NumPy (~20 MB)
- Tkinter (~10 MB)
- Your code (~1 MB)

**To reduce size:**
- Use `--onedir` instead of `--onefile` (slower startup, smaller)
- Remove unused imports from code
- Use UPX compression (add `--upx-dir=/path/to/upx`)

### Slow Startup

**First run:** Slower due to unpacking (10-30 seconds)
**Subsequent runs:** Faster (2-5 seconds)

**To improve:**
- Use `--onedir` mode (faster startup, multiple files)
- Build with `--noupx` to skip compression

---

## Comparison: Executable vs Python Script

| Feature | Standalone Executable | Python Script |
|---------|---------------------|---------------|
| **Target System** | No Python needed | Requires Python 3.7+ |
| **File Size** | 50-150 MB | < 1 MB (+ Python install) |
| **Distribution** | Single file | Multiple files |
| **Startup Speed** | Slower (2-30s) | Faster (< 1s) |
| **Updates** | Rebuild & redistribute | Update files |
| **Best For** | End users, demos | Developers, internal use |

---

## Best Practices

### For Distribution

1. **Test thoroughly** before distributing
   ```bash
   ./dist/VTOLAnalyzer --test
   ```

2. **Include documentation** with the executable
   - Copy README.md alongside executable
   - Create simple usage instructions

3. **Version your builds**
   ```bash
   # Rename with version number
   mv dist/VTOLAnalyzer dist/VTOLAnalyzer_v4.1.2
   ```

4. **Sign executables** (for trusted distribution)
   - Windows: Use `signtool` with code signing certificate
   - macOS: Use `codesign` with Apple Developer ID

### For Development

1. **Use Python directly** during development
   ```bash
   ./run_gui.sh  # Faster iteration
   ```

2. **Build executables** for testing on clean systems

3. **Build release versions** only when ready to distribute

---

## Continuous Integration

### Automated Builds

To automate builds:

```yaml
# Example GitHub Actions workflow
name: Build Executables
on: [push]
jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - run: pip install -r requirements.txt
      - run: pip install pyinstaller
      - run: pyinstaller --onefile run.py
      - uses: actions/upload-artifact@v2
        with:
          name: windows-exe
          path: dist/
```

---

## Additional Resources

### PyInstaller Documentation
- Official: https://pyinstaller.org/
- Advanced Usage: https://pyinstaller.org/en/stable/usage.html

### Common Issues
- Antivirus False Positives: https://github.com/pyinstaller/pyinstaller/wiki
- Hidden Imports: https://pyinstaller.org/en/stable/when-things-go-wrong.html

### Alternative Tools
- **PyOxidizer:** Rust-based bundler (faster, smaller)
- **Nuitka:** Compiles to C (fastest execution)
- **cx_Freeze:** Cross-platform alternative

---

## Summary

**Quick Commands:**

```bash
# Build executable
./build_executable.sh           # Linux/macOS
build_executable.bat            # Windows

# Test executable
./dist/VTOLAnalyzer --test      # Linux/macOS
dist\VTOLAnalyzer.exe --test    # Windows

# Distribute
# Just copy the executable - no Python needed on target!
```

**When to Use:**
- ✅ Distributing to users without Python
- ✅ Creating demos or presentations
- ✅ Deploying to production systems
- ❌ Active development (use Python directly)
- ❌ Frequent updates (rebuild required)

---

For questions or issues, see:
- Main documentation: README.md
- Quick start guide: QUICKSTART.md
- Project information: PROJECT_INFO.txt
