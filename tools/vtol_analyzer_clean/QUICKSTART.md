# VTOL Analyzer - Quick Start Guide

Get up and running in **5 minutes**!

---

## Step 1: Install (First Time Only)

### Windows:
```cmd
pip install -r requirements.txt
```

### Linux/Mac:
```bash
pip3 install -r requirements.txt
```

**That's it!** You're ready to go.

---

## Step 2: Launch

### Quick Launch (Easiest):

**Windows:** Double-click `run_gui.bat`

**Linux/Mac:** Double-click `run_gui.sh`
- If it doesn't work: `chmod +x run_gui.sh` then try again

### Command Line:
```bash
python3 run.py
```

---

## Step 3: Your First Analysis (30 seconds)

1. **GUI opens** → You'll see the Configuration tab

2. **Select a Preset:**
   - Dropdown at top: Choose "baseline"
   - Click "Load"

3. **Run Analysis:**
   - Click big "Run Analysis" button
   - Wait 2 seconds

4. **View Results:**
   - Results tab shows automatically
   - See: Speeds, Endurance, Range, Power

5. **Generate Plots:**
   - Click "Plots" tab
   - Click any 🔴 critical plot name
   - Instant graph appears!

6. **View Schematic:**
   - Click "Design Schematic" tab
   - Click "Update Schematic"
   - See 3-view engineering drawing

**Done!** You just analyzed your first VTOL aircraft.

---

## Quick Tips

### Compare Designs:
1. Comparison tab
2. Select multiple presets
3. Click "Run Comparison"
4. Side-by-side results table

### Export Report:
1. Export tab
2. Choose format (PDF recommended)
3. Click "Export"
4. Professional report generated!

### Mission Planning:
1. Mission tab
2. Click "Load Template" → Choose "Surveillance"
3. Click "Simulate Mission"
4. Energy budget calculated

---

## Common Questions

**Q: Where are my results saved?**
A: `output/` folder (plots, reports, data)

**Q: How do I customize parameters?**
A: Configuration tab → Edit any field → Click "Apply Changes"

**Q: Can I save my custom design?**
A: Yes! File menu → "Save Preset As..."

**Q: Need help?**
A: See full `README.md` or `docs/USER_GUIDE.md`

---

## Next Steps

**Beginner:**
- Try all 3 presets (baseline, performance, endurance)
- Generate all critical plots (🔴 red ones)
- Export a PDF report

**Intermediate:**
- Modify parameters (weight, wing span, etc.)
- Create custom missions
- Compare multiple configurations

**Advanced:**
- Use command-line mode: `python3 run.py --cli`
- Write custom analysis scripts (see `examples/`)
- Batch process designs

---

## Troubleshooting

**GUI won't start:**
```bash
python3 run.py --cli  # Try command-line mode
```

**Missing dependencies:**
```bash
pip3 install matplotlib numpy  # Install manually
```

**Still stuck?**
Check `README.md` section "Troubleshooting"

---

**Ready to Design VTOL Aircraft?**

Just run: `python3 run.py` and start analyzing!
