# VTOL Performance Analyzer v4.0 - GUI Edition

Professional desktop application for industrial-grade tailsitter drone performance analysis.

## Features

### 🎯 Six Tabbed Interfaces

1. **Configuration Tab**
   - Select from 3 pre-validated presets (LIGHTNING, BASELINE, THUNDER)
   - Edit all 20+ parameters with live validation
   - Real-time parameter ranges and hints
   - Apply changes and run analysis

2. **Analysis Results Tab**
   - Complete performance summary
   - Hover and cruise performance metrics
   - Detailed power budget breakdown
   - Transition energy analysis
   - Copy to clipboard or export

3. **Interactive Plots Tab**
   - Custom X vs Y parameter plotting
   - Parameter sweep analysis (50 data points)
   - Quick plot buttons for common analyses
   - Export plots as PNG (300 DPI) or CSV data
   - Matplotlib navigation toolbar included

4. **Mission Builder Tab**
   - Visual mission segment builder
   - Add/remove/reorder segments
   - Hover, cruise, and transition segments
   - Real-time mission simulation
   - Feasibility check (>20% battery reserve)
   - Save/load mission profiles

5. **Comparison Tab**
   - Side-by-side multi-preset comparison
   - Select 2-3 presets to compare
   - Performance table with all key metrics
   - Export comparison to CSV

6. **Export Manager Tab**
   - 5 export formats: PDF, Excel, CSV, JSON, HTML
   - 4 report templates: Engineering, Executive, Flight Test, Comparison
   - Preview before export
   - Batch export (all formats at once)
   - Auto-open after export

### 💾 Auto-Save & Session Management

- Auto-save every 5 minutes (toggleable)
- Save/load configurations to JSON
- Session state persistence (remembers last preset, settings, window size)
- Recent files tracking
- Restore from autosave on crash recovery

### 🎨 Professional UI/UX

- Modern flat design with professional colors
- Keyboard shortcuts (Ctrl+N, Ctrl+O, Ctrl+S, Ctrl+Q, F5)
- Status bar with real-time feedback
- Validation with helpful error messages
- Organized parameter sections with range hints
- Responsive layout (1400x900 default, 1200x700 minimum)

## Installation

### Prerequisites

```bash
# Core dependencies (required)
pip install tkinter  # Usually comes with Python
pip install matplotlib
pip install numpy

# Optional dependencies (for advanced export)
pip install reportlab  # For PDF export (falls back to text if not available)
pip install openpyxl   # For Excel export (falls back to CSV if not available)
```

### Quick Start

```bash
# Method 1: Direct launch
python vtol_analyzer_gui.py

# Method 2: Via main analyzer with --gui flag
python vtol_performance_analyzer.py --gui
```

## Usage Guide

### Basic Workflow

1. **Select Preset**
   - Configuration Tab → Preset dropdown → Select BASELINE, LIGHTNING, or THUNDER
   - Click "Load" to apply preset

2. **Customize Parameters** (optional)
   - Modify any parameters in the scrollable parameter editor
   - Click "Apply Changes" to update configuration
   - Click "Validate Configuration" to check ranges

3. **Run Analysis**
   - Click "Run Analysis" button
   - Results automatically appear in Analysis Results tab

4. **View Results**
   - Analysis Results tab shows complete performance summary
   - Key metrics: hover endurance, cruise range, power budget
   - Export to PDF/Excel for reporting

### Advanced Features

#### Custom Plotting

1. Go to **Interactive Plots** tab
2. Select X-axis parameter (e.g., "Speed (m/s)")
3. Select Y-axis parameter (e.g., "Power (W)")
4. Click "Generate Plot"
5. Use matplotlib toolbar to zoom/pan
6. Export as PNG (300 DPI) or CSV data

**Quick Plot Examples:**
- Power vs Speed: Shows power consumption across cruise speeds
- Range vs Speed: Finds optimal cruise speed for maximum range
- Endurance vs Weight: Shows how weight affects flight time

#### Mission Planning

1. Go to **Mission Builder** tab
2. Add segments using dropdown + "Add" button
   - **Hover**: Duration (seconds)
   - **Cruise**: Duration (seconds) + Speed (m/s)
   - **Transition Forward/Back**: Auto-calculated
3. Reorder with ↑↓ buttons, delete with ✕
4. Click "Simulate Mission"
5. Check feasibility (battery reserve must be >20%)

**Example Mission:**
```
1. Hover (60s) - Takeoff
2. Transition Forward - Switch to cruise
3. Cruise (900s @ 15 m/s) - Travel to site (13.5 km)
4. Transition Back - Switch to hover
5. Hover (300s) - Survey/inspection
6. Transition Forward
7. Cruise (900s @ 15 m/s) - Return trip
8. Transition Back
9. Hover (60s) - Landing
```

#### Preset Comparison

1. Go to **Comparison** tab
2. Check 2-3 presets to compare
3. Click "Run Comparison"
4. View side-by-side performance table
5. Export to CSV for further analysis

### Export Options

#### PDF Reports

- **Engineering Report**: Full technical details, all sections
- **Executive Summary**: Key results only, 1-2 pages
- **Flight Test Report**: Predicted performance + blank test data sheets
- **Comparison Report**: Multi-preset comparison with charts

#### Excel Spreadsheets

- Multiple sheets: Summary, Configuration, Hover, Cruise, Power Budget
- Formatted tables with color coding
- Ready for further analysis in Excel

#### CSV Data

- Performance metrics in tabular format
- Easy import into Python, R, MATLAB
- Multiple files: performance, configuration, mission

#### JSON Export

- Complete data export with metadata
- API-compatible format
- Easy to parse programmatically

#### HTML Reports

- Responsive web-ready reports
- Professional styling with CSS
- Can be hosted on web servers
- Print-optimized

### Configuration Files

Configurations are stored in `~/.vtol_analyzer/`:
- `autosave.json` - Auto-saved configuration (every 5 minutes)
- `.vtol_analyzer_session.json` - Session state (last preset, settings)
- User-saved configurations (via File → Save Configuration)

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+N` | New Analysis |
| `Ctrl+O` | Open Configuration |
| `Ctrl+S` | Save Configuration |
| `Ctrl+Q` | Quit Application |
| `F5` | Refresh Results |

## Tips & Best Practices

### Parameter Tuning

1. **Start with a validated preset** - LIGHTNING, BASELINE, or THUNDER
2. **Use validation** - Click "Validate Configuration" after changes
3. **Test incrementally** - Change one parameter at a time
4. **Use plots** - Visualize how parameters affect performance

### Mission Planning

1. **Always include transitions** - Don't forget forward/back transitions
2. **Add margin** - Keep battery reserve >20% (ideally >30%)
3. **Test different speeds** - Compare 12 m/s vs 15 m/s vs 18 m/s cruise speeds
4. **Account for wind** - Real missions may consume more energy

### Reporting

1. **Use templates** - Select appropriate report template for audience
   - Engineering: For technical team
   - Executive: For management/stakeholders
   - Flight Test: For field operations
2. **Export all formats** - Use "Export All Formats" for complete documentation
3. **Include mission analysis** - Check "Include mission analysis" in export options

## Troubleshooting

### GUI Won't Start

**Issue**: `ModuleNotFoundError: No module named 'tkinter'`

**Solution**:
```bash
# Ubuntu/Debian
sudo apt-get install python3-tk

# macOS
brew install python-tk

# Windows
# Reinstall Python with "tcl/tk" option checked
```

### PDF Export Fails

**Issue**: `reportlab library not installed`

**Solution**:
```bash
pip install reportlab
# Or use text export as fallback (automatic)
```

### Excel Export Fails

**Issue**: `openpyxl library not installed`

**Solution**:
```bash
pip install openpyxl
# Or use CSV export as fallback (automatic)
```

### Parameters Not Saving

**Issue**: Changes not persisting after restart

**Solution**:
- Enable "Auto-Save Configuration" in View menu
- Or use File → Save Configuration manually

### Analysis Fails

**Issue**: "Invalid parameter value" error

**Solution**:
1. Click "Validate Configuration" to see specific errors
2. Check parameter ranges (shown in gray text next to each field)
3. Reset to preset defaults with "Reset" button

## Version History

### v4.0 (2025-01-20) - GUI Edition

- Complete Tkinter desktop GUI application
- 6 tabbed interfaces for all features
- Interactive parameter editing with live validation
- Custom plotting (any parameter vs any parameter)
- Visual mission builder with simulation
- Multi-preset comparison tool
- Professional export manager (PDF, Excel, CSV, JSON, HTML)
- Auto-save and session management
- Keyboard shortcuts
- 2600+ lines of production-ready code

### v3.0 (2025-01-19) - Script Edition

- Industrial-grade core engine
- HTML output reports
- Preset system (LIGHTNING, BASELINE, THUNDER)
- Command-line interface

## Support & Documentation

- **Full API Documentation**: See `V3_RELEASE_NOTES.md`
- **Implementation Plan**: See `V4_IMPLEMENTATION_PLAN.md`
- **Example Workflows**: See `production_workflow_example.py`

## License

MIT License - Industrial-grade tailsitter performance analysis tool

## Credits

- Core v3.0 engine with validated physics models
- Professional v4.0 GUI built on proven v3.0 foundation
- Optimized for production drone operations
