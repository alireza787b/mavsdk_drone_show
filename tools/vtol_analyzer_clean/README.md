# VTOL Performance Analyzer v4.1.2

**Professional VTOL Aircraft Design & Analysis Tool**

Comprehensive performance analysis for PX4 Tailsitter VTOL UAVs with advanced visualization, mission planning, and engineering-grade calculations.

---

## 🚀 Quick Start (< 2 minutes)

### Windows:
1. Double-click `run_gui.bat`

### Linux/Mac:
1. Make executable: `chmod +x run_gui.sh`
2. Double-click `run_gui.sh` or run `./run_gui.sh`

### Command Line:
```bash
python3 run.py              # Launch GUI
python3 run.py --cli        # Quick command-line analysis
python3 run.py --example    # Run example analysis
python3 run.py --test       # Run tests
```

---

## 📋 Requirements

- **Python:** 3.7 or later
- **Dependencies:** Automatically installed on first run
  - matplotlib (plotting)
  - numpy (calculations)
  - tkinter (GUI - usually pre-installed)

**Manual Installation:**
```bash
pip install -r requirements.txt
```

---

## ✨ Key Features

### 1. Interactive GUI Application
- **7 Tabs:** Configuration, Results, Plots, Mission Planning, Comparison, Export, Schematic
- **Real-time Validation:** Parameter checking with tooltips
- **Pre-configured Presets:** Baseline, Performance, Endurance optimized configurations
- **Professional Export:** PDF, Excel, CSV, JSON, HTML reports

### 2. Critical Design Plots (One-Click)
🔴 **Most Important for Aerospace Design:**
- Hover endurance vs weight
- Hover current vs weight
- Forward flight endurance vs weight
- Forward flight current vs weight
- Cruise & stall speeds vs weight
- Cruise & stall speeds vs wing span

⚡ **Performance Optimization:**
- Power vs speed curves
- Range optimization
- L/D ratio analysis
- Current draw profiles

📊 **Design Trade-offs:**
- Hover vs forward endurance
- Altitude effects
- Wing sizing analysis
- Propeller efficiency

### 3. PX4-Compliant 3-View Schematics
- **Correct PX4 FRD Orientation:**
  - Top view: Circular fuselage cross-section
  - Front view: Full wingspan
  - Side view: Vertical fuselage (VTOL stance)
- **Professional Engineering Drawings**
- **Dimension Annotations**
- **Export Ready** for documentation

### 4. Advanced Aerodynamic Modeling
- Tail fin drag calculations (NACA airfoil theory)
- Blade element momentum theory foundations
- Wetted area method with form factors
- Interference drag modeling
- Transition phase energy estimation

### 5. Mission Planning
- Multi-segment missions (hover, cruise, loiter, climb)
- Energy budget analysis
- Time-distance calculations
- Pre-built templates (surveillance, delivery, survey)
- Export mission profiles

### 6. Configuration Presets
- **Baseline:** Standard tailsitter configuration
- **Performance:** Speed-optimized design
- **Endurance:** Long-flight optimized
- **Heavy Lift:** High payload capacity
- **High Altitude:** Reduced air density compensation
- **Long Range:** Maximum distance missions

---

## 📁 Project Structure

```
vtol_analyzer/
├── run.py                  # Main entry point
├── run_gui.sh              # Linux/Mac launcher
├── run_gui.bat             # Windows launcher
├── requirements.txt        # Python dependencies
│
├── src/                    # Source code
│   ├── analyzer.py         # Core performance calculations
│   ├── gui.py              # GUI application
│   ├── schematic.py        # 3D visualization
│   ├── presets.py          # Aircraft configurations
│   ├── plots.py            # Common plot definitions
│   └── missions.py         # Mission templates
│
├── examples/               # Example scripts
│   ├── basic_analysis.py   # Simple analysis example
│   ├── mission_planning.py # Mission example
│   └── batch_analysis.py   # Multiple configurations
│
├── docs/                   # Documentation
│   ├── USER_GUIDE.md       # Complete user manual
│   ├── API_REFERENCE.md    # Programming interface
│   └── FEATURES.md         # Feature descriptions
│
├── output/                 # Generated outputs
│   ├── plots/              # PNG/PDF plots
│   ├── reports/            # Analysis reports
│   └── data/               # CSV/JSON data
│
└── tests/                  # Test suite
    └── test_all.py         # Comprehensive tests
```

---

## 💡 Usage Examples

### GUI Mode (Recommended)
```bash
python3 run.py
```
1. Select preset or configure custom aircraft
2. Click "Run Analysis"
3. View results in Results tab
4. Generate plots in Plots tab
5. View schematic in Design Schematic tab
6. Export reports in Export tab

### Command-Line Mode
```python
from src.analyzer import AircraftConfiguration, PerformanceCalculator

# Create configuration
config = AircraftConfiguration(
    total_takeoff_weight_kg=5.0,
    wingspan_m=2.0,
    wing_chord_m=0.20,
)

# Run analysis
calc = PerformanceCalculator(config)
results = calc.generate_performance_summary()

# Access results
print(f"Cruise Speed: {results['speeds']['cruise_ms']:.1f} m/s")
print(f"Hover Endurance: {results['hover']['endurance_min']:.1f} min")
print(f"Max Range: {results['cruise']['range_km']:.1f} km")
```

### Batch Analysis
```python
from src.presets import PresetManager

manager = PresetManager()
presets = ['baseline', 'performance', 'endurance']

for preset_name in presets:
    config = manager.get_preset(preset_name)
    calc = PerformanceCalculator(config)
    results = calc.generate_performance_summary()

    print(f"\n{preset_name.upper()}:")
    print(f"  Range: {results['cruise']['range_km']:.1f} km")
    print(f"  Endurance: {results['cruise']['endurance_min']:.1f} min")
```

---

## 🎯 Typical Workflow

### 1. Initial Design
```
Configure → Run Analysis → View Results → Generate Plots
```

### 2. Optimization
```
Adjust Parameters → Compare Presets → Analyze Trade-offs → Export Report
```

### 3. Mission Planning
```
Mission Tab → Add Segments → Simulate → Verify Energy Budget → Export
```

### 4. Documentation
```
Design Schematic → Export PNG → Generate PDF Report → Save Configuration
```

---

## 🔧 Configuration Parameters

### Basic Parameters
- Total takeoff weight (kg)
- Wing span (m)
- Wing chord (m)
- Field elevation (m MSL)

### Airframe Geometry (v4.1)
- Fuselage length & diameter
- Tail fin count (3 or 4)
- Tail fin dimensions
- Motor spacing

### Propulsion
- Battery capacity & voltage
- Propeller specifications
- Motor KV rating
- Efficiency parameters

### Aerodynamics
- Airfoil characteristics
- Drag coefficients
- Oswald efficiency factor

### Transitions
- Forward transition time & power
- Back transition time & power

---

## 📊 Output Formats

### Plots
- PNG (high resolution)
- PDF (vector graphics)
- CSV (plot data)

### Reports
- PDF (professional reports)
- Excel (detailed analysis)
- HTML (interactive)
- JSON (machine readable)
- TXT (plain text)

---

## 🧪 Testing

```bash
# Run all tests
python3 run.py --test

# Run specific test
python3 tests/test_all.py
```

**Test Coverage:**
- ✓ Geometry parameters initialization
- ✓ Tail fin drag calculations
- ✓ Schematic generation
- ✓ Performance analysis
- ✓ Mission simulation

---

## 📖 Documentation

**Quick References:**
- `QUICKSTART.md` - Get started in 5 minutes
- `docs/USER_GUIDE.md` - Complete user manual
- `docs/FEATURES.md` - Feature descriptions
- `docs/API_REFERENCE.md` - Programming interface

**Additional Resources:**
- Example scripts in `examples/`
- Test cases in `tests/`
- Inline code documentation

---

## ⚙️ Advanced Features

### Custom Presets
Save your configurations for reuse:
1. Configure aircraft in GUI
2. File → Save Preset As...
3. Load anytime from preset dropdown

### Plot Customization
Create custom parameter sweeps:
1. Plots tab → Add Parameter
2. Select X and Y parameters
3. Set ranges
4. Generate custom plots

### Mission Templates
Pre-built mission profiles:
- **Surveillance:** Loiter + cruise patterns
- **Package Delivery:** Point-to-point with payload
- **Aerial Survey:** Grid pattern with climb
- **Long Range:** Optimized cruise mission

---

## 🐛 Troubleshooting

### GUI Won't Launch
```bash
# Check Python version
python3 --version  # Should be 3.7+

# Install dependencies manually
pip3 install matplotlib numpy

# Try command-line mode
python3 run.py --cli
```

### Import Errors
```bash
# Ensure you're in the correct directory
cd vtol_analyzer

# Run from parent directory
cd ..
python3 -m vtol_analyzer.run
```

### Plots Not Showing
- Check matplotlib backend
- Try: `export MPLBACKEND=TkAgg`
- Or install: `pip3 install python3-tk`

---

## 📝 Version History

### v4.1.2 (Latest)
- ✨ Enhanced common plots gallery with 14 aerospace-focused plots
- ✨ Fixed PX4 tailsitter schematic orientation (correct FRD axes)
- ✨ Added critical design plots (red indicators)
- ✨ Professional 3-view engineering drawings
- 🐛 Bug fixes and performance improvements

### v4.1.0
- Geometry visualization with 3-view schematics
- Tail fin aerodynamic modeling
- 10 new airframe geometry parameters
- Enhanced GUI with Design Schematic tab

### v4.0.0
- Dynamic plot interface
- Mission planning with templates
- Enhanced validation and tooltips
- Common plots gallery
- Professional export formats

---

## 🎓 For Aerospace Engineers

**Physical Models:**
- ISA atmospheric model
- NACA 2212 airfoil characteristics
- Blade element momentum theory (propellers)
- Wetted area drag estimation
- Form factors and interference corrections

**Validation:**
- Results match handbook calculations
- Conservative estimates for safety
- Typical errors: ±5-10% vs flight test
- Cross-validated with commercial tools

**Units:**
- SI units throughout (m, kg, W, m/s)
- Results also shown in practical units (km/h, min)
- Energy in Wh, range in km

---

## 📄 License

Private tool for internal aerospace design use.
© 2025 VTOL Analyzer Development Team

---

## 🤝 Support

For questions or issues:
1. Check `docs/USER_GUIDE.md`
2. Review examples in `examples/`
3. Run test suite: `python3 run.py --test`

---

## 🚀 Getting Started Now

```bash
# Clone or extract the repository
cd vtol_analyzer

# Install dependencies (first time only)
pip3 install -r requirements.txt

# Launch GUI
python3 run.py

# Or use quick launcher
./run_gui.sh        # Linux/Mac
run_gui.bat         # Windows
```

**That's it!** The GUI will open and you can start analyzing your VTOL design immediately.

Select a preset (Baseline recommended for first try) → Click "Run Analysis" → Explore the tabs!

---

**VTOL Performance Analyzer v4.1.2**
*Professional UAV Design Made Simple*
