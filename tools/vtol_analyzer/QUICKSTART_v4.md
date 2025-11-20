# VTOL Analyzer v4.0 - Quick Start Guide

## 🚀 5-Minute Quick Start

### Step 1: Install (One-Time Setup)

```bash
# Install Python dependencies
pip install -r requirements_gui.txt

# Or install core packages only
pip install numpy matplotlib
```

### Step 2: Launch

**Windows:**
```
Double-click: launch_gui.bat
```

**Linux/macOS:**
```bash
./launch_gui.sh
# or
python3 vtol_analyzer_gui.py
```

### Step 3: Run Your First Analysis

1. **Application opens → Configuration Tab**
2. **Select a preset:**
   - LIGHTNING (5.2 kg) - High power, short missions
   - BASELINE (6.0 kg) - Balanced, validated design ⭐ START HERE
   - THUNDER (8.0 kg) - Heavy payload, long missions
3. **Click "Load"** to apply preset
4. **Click "Run Analysis"** button
5. **Results appear automatically** in Analysis Results tab

**That's it!** You now have:
- Hover endurance (minutes)
- Cruise range (kilometers)
- Power budget breakdown
- Complete performance analysis

---

## 🎯 Common Tasks

### Task: Compare Different Drones

1. Go to **Comparison Tab**
2. Check 2-3 presets (LIGHTNING, BASELINE, THUNDER)
3. Click **Run Comparison**
4. View side-by-side performance table

### Task: Plan a Mission

1. Go to **Mission Builder Tab**
2. Add segments:
   - Hover (60s) - Takeoff
   - Transition Forward
   - Cruise (900s @ 15 m/s) - Travel
   - Transition Back
   - Hover (60s) - Landing
3. Click **Simulate Mission**
4. Check if battery reserve > 20% ✓

### Task: Find Optimal Cruise Speed

1. Go to **Interactive Plots Tab**
2. X-Axis: Speed (m/s)
3. Y-Axis: Range (km)
4. Click **Generate Plot**
5. Look for peak = optimal speed

### Task: Export a Report

1. Run analysis in Configuration tab
2. Go to **Export Manager Tab**
3. Select format: PDF Report
4. Select template: Engineering Report
5. Click **Export**
6. Report opens automatically (if enabled)

---

## 📝 Customizing Parameters

**Want to modify a preset?**

1. Configuration Tab → Load a preset
2. Scroll down to parameter sections:
   - **Basic**: Weight, wingspan, altitude
   - **Tailsitter-Specific**: Control power, drag
   - **Transitions**: Duration, power factors
   - **Propulsion**: Motor/prop efficiencies
   - **Auxiliary**: Avionics, payload power
3. Modify values (ranges shown in gray)
4. Click **Apply Changes**
5. Click **Validate Configuration** (optional but recommended)
6. Click **Run Analysis**

---

## 💾 Saving Your Work

**Auto-Save (Automatic):**
- Enabled by default
- Saves every 5 minutes to `~/.vtol_analyzer/autosave.json`
- Toggle in **View → Auto-Save Configuration**

**Manual Save:**
- **File → Save Configuration** (Ctrl+S)
- Save as `.json` file
- Load later with **File → Open Configuration** (Ctrl+O)

---

## 🔧 Troubleshooting

### GUI Won't Start

**Error: "tkinter not found"**

```bash
# Ubuntu/Debian
sudo apt-get install python3-tk

# macOS
brew install python-tk

# Windows: Reinstall Python with "tcl/tk" checked
```

### Missing Dependencies

```bash
pip install numpy matplotlib reportlab openpyxl
```

### Analysis Fails

1. Click **Validate Configuration**
2. Fix any red errors
3. Review yellow warnings (acceptable but unusual)
4. Try again

---

## 📚 Learn More

- **Full Documentation**: `README_v4_GUI.md`
- **API Reference**: `V3_RELEASE_NOTES.md`
- **Implementation Details**: `V4_IMPLEMENTATION_PLAN.md`

---

## 🎉 You're Ready!

The v4.0 GUI is production-ready. Key capabilities:

✓ **6 Professional Tabs** - Configuration, Results, Plots, Missions, Comparison, Export
✓ **3 Validated Presets** - Start analyzing immediately
✓ **5 Export Formats** - PDF, Excel, CSV, JSON, HTML
✓ **Auto-Save** - Never lose your work
✓ **Session Restore** - Continues where you left off
✓ **Professional Reports** - Ready for stakeholders

**Need help?** Check `README_v4_GUI.md` for detailed guides.

---

**Version**: 4.0.0
**Date**: 2025-01-20
**Platform**: Cross-platform (Windows, macOS, Linux)
