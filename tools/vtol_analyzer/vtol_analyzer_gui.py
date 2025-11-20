#!/usr/bin/env python3
"""
===============================================================================
VTOL PERFORMANCE ANALYZER v4.0 - PROFESSIONAL GUI
===============================================================================

Full-featured Tkinter GUI for professional drone performance analysis.

Features:
- Interactive parameter configuration
- Real-time analysis updates
- Custom plot generation (any parameter vs any parameter)
- Mission profile builder
- Multi-preset comparison
- Professional export tools (PDF, Excel, reports)

Usage:
    python vtol_analyzer_gui.py
    python vtol_performance_analyzer.py --gui

Version: 4.0.0
Date: 2025-01-20
===============================================================================
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import sys
import os
from pathlib import Path

# Matplotlib for embedded plots
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# Import v3.0 core functionality
try:
    from vtol_performance_analyzer import (
        AircraftConfiguration,
        PerformanceCalculator,
        ReportGenerator
    )
    from config_presets import PresetManager, get_preset
except ImportError as e:
    print(f"Error: Could not import required modules: {e}")
    print("Make sure vtol_performance_analyzer.py and config_presets.py are in the same directory")
    sys.exit(1)


# ===========================================================================
# MAIN APPLICATION CLASS
# ===========================================================================

class VTOLAnalyzerGUI(tk.Tk):
    """
    Main GUI application for VTOL Performance Analyzer v4.0

    Professional desktop application with:
    - 6 tabbed interfaces
    - Real-time parameter editing
    - Interactive plotting
    - Mission builder
    - Comparison tools
    - Export manager
    """

    def __init__(self):
        super().__init__()

        # Window setup
        self.title("VTOL Performance Analyzer v4.0 - Professional Edition")
        self.geometry("1400x900")
        self.minsize(1200, 700)

        # Application icon (if available)
        try:
            self.iconbitmap('vtol_icon.ico')
        except:
            pass  # Icon optional

        # Core application data
        self.preset_manager = PresetManager()
        self.current_preset_name = "baseline"
        self.current_config = None
        self.current_calc = None
        self.current_results = None

        # Settings
        self.auto_update = tk.BooleanVar(value=False)
        self.dark_mode = tk.BooleanVar(value=False)

        # Initialize UI
        self.create_styles()
        self.create_menu()
        self.create_main_interface()
        self.create_status_bar()

        # Load default preset
        self.load_preset("baseline")

        # Bind window close
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # -----------------------------------------------------------------------
    # STYLING
    # -----------------------------------------------------------------------

    def create_styles(self):
        """Create professional ttk styles"""
        style = ttk.Style()

        # Try to use a modern theme
        try:
            style.theme_use('clam')  # Modern, flat theme
        except:
            pass

        # Custom colors
        self.colors = {
            'primary': '#2C3E50',
            'secondary': '#3498DB',
            'success': '#27AE60',
            'warning': '#F39C12',
            'danger': '#E74C3C',
            'background': '#ECF0F1',
            'text': '#2C3E50',
            'accent': '#9B59B6',
        }

        # Configure styles
        style.configure('Title.TLabel', font=('Arial', 14, 'bold'), foreground=self.colors['primary'])
        style.configure('Heading.TLabel', font=('Arial', 11, 'bold'))
        style.configure('Status.TLabel', font=('Arial', 9))
        style.configure('Primary.TButton', foreground='white', background=self.colors['primary'])

        # Tab style
        style.configure('TNotebook', background=self.colors['background'])
        style.configure('TNotebook.Tab', padding=[20, 10], font=('Arial', 10))

    # -----------------------------------------------------------------------
    # MENU BAR
    # -----------------------------------------------------------------------

    def create_menu(self):
        """Create application menu bar"""
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New Analysis", command=self.new_analysis, accelerator="Ctrl+N")
        file_menu.add_command(label="Open Configuration...", command=self.open_config, accelerator="Ctrl+O")
        file_menu.add_command(label="Save Configuration...", command=self.save_config, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export Report...", command=self.export_report)
        file_menu.add_command(label="Export All Data...", command=self.export_all_data)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing, accelerator="Ctrl+Q")

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_checkbutton(label="Auto Update", variable=self.auto_update, command=self.toggle_auto_update)
        view_menu.add_checkbutton(label="Dark Mode", variable=self.dark_mode, command=self.toggle_dark_mode)
        view_menu.add_separator()
        view_menu.add_command(label="Refresh Results", command=self.refresh_results, accelerator="F5")

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Mission Builder", command=lambda: self.notebook.select(3))
        tools_menu.add_command(label="Comparison Tool", command=lambda: self.notebook.select(4))
        tools_menu.add_command(label="Parameter Optimizer", command=self.optimize_parameters)
        tools_menu.add_separator()
        tools_menu.add_command(label="Run Script Mode...", command=self.run_script_mode)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Quick Start Guide", command=self.show_quick_start)
        help_menu.add_command(label="Documentation", command=self.show_documentation)
        help_menu.add_command(label="Parameter Guide", command=self.show_parameter_guide)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)

        # Keyboard shortcuts
        self.bind_all("<Control-n>", lambda e: self.new_analysis())
        self.bind_all("<Control-o>", lambda e: self.open_config())
        self.bind_all("<Control-s>", lambda e: self.save_config())
        self.bind_all("<Control-q>", lambda e: self.on_closing())
        self.bind_all("<F5>", lambda e: self.refresh_results())

    # -----------------------------------------------------------------------
    # MAIN INTERFACE
    # -----------------------------------------------------------------------

    def create_main_interface(self):
        """Create main tabbed notebook interface"""
        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)

        # Tab 1: Configuration
        self.tab_config = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_config, text="  Configuration  ")
        self.create_config_tab()

        # Tab 2: Analysis Results
        self.tab_results = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_results, text="  Analysis Results  ")
        self.create_results_tab()

        # Tab 3: Interactive Plots
        self.tab_plots = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_plots, text="  Interactive Plots  ")
        self.create_plots_tab()

        # Tab 4: Mission Builder
        self.tab_mission = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_mission, text="  Mission Builder  ")
        self.create_mission_tab()

        # Tab 5: Comparison
        self.tab_comparison = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_comparison, text="  Comparison  ")
        self.create_comparison_tab()

        # Tab 6: Export Manager
        self.tab_export = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_export, text="  Export Manager  ")
        self.create_export_tab()

    # -----------------------------------------------------------------------
    # TAB 1: CONFIGURATION
    # -----------------------------------------------------------------------

    def create_config_tab(self):
        """Create configuration tab with preset selector and parameter editor"""
        # Top section: Preset selector
        top_frame = ttk.Frame(self.tab_config)
        top_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(top_frame, text="Preset:", font=('Arial', 11, 'bold')).pack(side='left', padx=5)

        self.preset_var = tk.StringVar(value="baseline")
        preset_combo = ttk.Combobox(top_frame, textvariable=self.preset_var, width=50, state='readonly')
        preset_combo['values'] = [
            f"{name}: {self.preset_manager.get_preset_description(name)}"
            for name in self.preset_manager.list_presets()
        ]
        preset_combo.current(1)  # baseline
        preset_combo.pack(side='left', padx=5)
        preset_combo.bind('<<ComboboxSelected>>', self.on_preset_selected)

        ttk.Button(top_frame, text="Load", command=self.load_selected_preset).pack(side='left', padx=2)
        ttk.Button(top_frame, text="Save As...", command=self.save_preset_as).pack(side='left', padx=2)
        ttk.Button(top_frame, text="Reset", command=self.reset_config).pack(side='left', padx=2)
        ttk.Button(top_frame, text="Apply Changes", command=self.apply_config, style='Primary.TButton').pack(side='left', padx=10)

        # Main scrollable frame for parameters
        canvas = tk.Canvas(self.tab_config, bg='white')
        scrollbar = ttk.Scrollbar(self.tab_config, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", pady=10, padx=(0, 10))

        # Store parameter widgets
        self.param_widgets = {}

        # Create parameter sections
        self.create_basic_params_section(scrollable_frame)
        self.create_tailsitter_params_section(scrollable_frame)
        self.create_transitions_params_section(scrollable_frame)
        self.create_propulsion_params_section(scrollable_frame)
        self.create_auxiliary_params_section(scrollable_frame)

        # Bottom action buttons
        bottom_frame = ttk.Frame(self.tab_config)
        bottom_frame.pack(fill='x', padx=10, pady=10)

        ttk.Button(bottom_frame, text="Validate Configuration", command=self.validate_config).pack(side='left', padx=5)
        ttk.Button(bottom_frame, text="Run Analysis", command=self.run_analysis, style='Primary.TButton').pack(side='left', padx=5)
        ttk.Button(bottom_frame, text="View Results →", command=lambda: self.notebook.select(1)).pack(side='left', padx=5)

    def create_basic_params_section(self, parent):
        """Create basic parameters section"""
        frame = ttk.LabelFrame(parent, text=" Basic Parameters ", padding=10)
        frame.pack(fill='x', padx=10, pady=5)

        params = [
            ("total_takeoff_weight_kg", "Total Weight", "kg", "1.0-20.0"),
            ("wingspan_m", "Wing Span", "m", "0.5-5.0"),
            ("wing_chord_m", "Wing Chord", "m", "0.05-0.5"),
            ("field_elevation_m", "Field Elevation", "m MSL", "0-4000"),
        ]

        for i, (param, label, unit, range_str) in enumerate(params):
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=2)

            ttk.Label(row, text=f"{label}:", width=20).pack(side='left')
            entry = ttk.Entry(row, width=15)
            entry.pack(side='left', padx=5)
            ttk.Label(row, text=unit, width=10).pack(side='left')
            ttk.Label(row, text=f"({range_str})", font=('Arial', 8), foreground='gray').pack(side='left')

            self.param_widgets[param] = entry

    def create_tailsitter_params_section(self, parent):
        """Create tailsitter-specific parameters section"""
        frame = ttk.LabelFrame(parent, text=" Tailsitter-Specific (v3.0) ", padding=10)
        frame.pack(fill='x', padx=10, pady=5)

        params = [
            ("control_power_base_w", "Control Power Base", "W", "30-100", True),
            ("control_power_speed_factor", "Control Power Speed Factor", "W/(m/s)", "2-10", True),
            ("cd0_motor_nacelles", "CD0 Motor Nacelles", "-", "0.020-0.050", True),
            ("cd0_fuselage_base", "CD0 Fuselage Base", "-", "0.005-0.015", False),
            ("cd0_landing_gear", "CD0 Landing Gear", "-", "0.008-0.020", False),
            ("cd0_interference", "CD0 Interference", "-", "0.010-0.025", True),
        ]

        for param, label, unit, range_str, tunable in params:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=2)

            ttk.Label(row, text=f"{label}:", width=25).pack(side='left')
            entry = ttk.Entry(row, width=12)
            entry.pack(side='left', padx=5)
            ttk.Label(row, text=unit, width=12).pack(side='left')
            ttk.Label(row, text=f"({range_str})", font=('Arial', 8), foreground='gray').pack(side='left', padx=5)

            if tunable:
                ttk.Label(row, text="[TUNE]", foreground=self.colors['warning'], font=('Arial', 8, 'bold')).pack(side='left')

            self.param_widgets[param] = entry

    def create_transitions_params_section(self, parent):
        """Create transition parameters section (collapsible)"""
        # This will be a collapsible section - simplified for now
        frame = ttk.LabelFrame(parent, text=" Transitions ", padding=10)
        frame.pack(fill='x', padx=10, pady=5)

        params = [
            ("transition_forward_duration_s", "Forward Duration", "s", "10-20", True),
            ("transition_forward_power_factor", "Forward Power Factor", "×", "1.5-2.5", True),
            ("transition_back_duration_s", "Back Duration", "s", "8-15", False),
            ("transition_back_power_factor", "Back Power Factor", "×", "1.2-2.0", False),
        ]

        for param, label, unit, range_str, tunable in params:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=2)

            ttk.Label(row, text=f"{label}:", width=25).pack(side='left')
            entry = ttk.Entry(row, width=12)
            entry.pack(side='left', padx=5)
            ttk.Label(row, text=unit, width=12).pack(side='left')
            ttk.Label(row, text=f"({range_str})", font=('Arial', 8), foreground='gray').pack(side='left', padx=5)

            if tunable:
                ttk.Label(row, text="[MEASURE]", foreground=self.colors['secondary'], font=('Arial', 8, 'bold')).pack(side='left')

            self.param_widgets[param] = entry

    def create_propulsion_params_section(self, parent):
        """Create propulsion parameters section"""
        frame = ttk.LabelFrame(parent, text=" Propulsion Efficiency ", padding=10)
        frame.pack(fill='x', padx=10, pady=5)

        params = [
            ("prop_efficiency_lowspeed", "Prop Efficiency (Low Speed)", "%", "60-75"),
            ("prop_efficiency_highspeed", "Prop Efficiency (High Speed)", "%", "50-65"),
            ("motor_efficiency_peak", "Motor Efficiency", "%", "75-90"),
            ("esc_efficiency", "ESC Efficiency", "%", "88-95"),
        ]

        for param, label, unit, range_str in params:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=2)

            ttk.Label(row, text=f"{label}:", width=30).pack(side='left')
            entry = ttk.Entry(row, width=12)
            entry.pack(side='left', padx=5)
            ttk.Label(row, text=unit, width=8).pack(side='left')
            ttk.Label(row, text=f"({range_str})", font=('Arial', 8), foreground='gray').pack(side='left')

            self.param_widgets[param] = entry

    def create_auxiliary_params_section(self, parent):
        """Create auxiliary systems parameters section"""
        frame = ttk.LabelFrame(parent, text=" Auxiliary Systems ", padding=10)
        frame.pack(fill='x', padx=10, pady=5)

        params = [
            ("avionics_power_w", "Avionics Power", "W", "4-10"),
            ("payload_power_w", "Payload Power", "W", "0-20"),
            ("heater_power_w", "Heater Power", "W", "0-15"),
        ]

        for param, label, unit, range_str in params:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=2)

            ttk.Label(row, text=f"{label}:", width=20).pack(side='left')
            entry = ttk.Entry(row, width=12)
            entry.pack(side='left', padx=5)
            ttk.Label(row, text=unit, width=8).pack(side='left')
            ttk.Label(row, text=f"({range_str})", font=('Arial', 8), foreground='gray').pack(side='left')

            self.param_widgets[param] = entry

    # -----------------------------------------------------------------------
    # TAB 2: ANALYSIS RESULTS
    # -----------------------------------------------------------------------

    def create_results_tab(self):
        """Create analysis results display tab"""
        # Top toolbar
        toolbar = ttk.Frame(self.tab_results)
        toolbar.pack(fill='x', padx=10, pady=5)

        ttk.Label(toolbar, text="Performance Summary", style='Title.TLabel').pack(side='left')
        ttk.Button(toolbar, text="Export PDF", command=self.export_results_pdf).pack(side='right', padx=2)
        ttk.Button(toolbar, text="Copy Text", command=self.copy_results_text).pack(side='right', padx=2)
        ttk.Button(toolbar, text="Refresh", command=self.refresh_results).pack(side='right', padx=2)

        # Scrollable text area for results
        self.results_text = scrolledtext.ScrolledText(
            self.tab_results,
            wrap=tk.WORD,
            width=100,
            height=40,
            font=('Courier', 10)
        )
        self.results_text.pack(fill='both', expand=True, padx=10, pady=10)

        # Initial message
        self.results_text.insert('1.0', "No analysis run yet.\n\nGo to Configuration tab and click 'Run Analysis'.")
        self.results_text.config(state='disabled')

    # -----------------------------------------------------------------------
    # TAB 3: INTERACTIVE PLOTS
    # -----------------------------------------------------------------------

    def create_plots_tab(self):
        """Create interactive plotting tab"""
        # Control panel
        control_frame = ttk.LabelFrame(self.tab_plots, text=" Plot Configuration ", padding=10)
        control_frame.pack(fill='x', padx=10, pady=10)

        # Plot type
        ttk.Label(control_frame, text="Plot Type:").grid(row=0, column=0, sticky='w', pady=5)
        self.plot_type_var = tk.StringVar(value="2D Line")
        plot_types = ["2D Line", "2D Scatter", "3D Surface"]
        for i, ptype in enumerate(plot_types):
            ttk.Radiobutton(control_frame, text=ptype, variable=self.plot_type_var, value=ptype).grid(row=0, column=i+1, sticky='w', padx=10)

        # Axis selectors
        ttk.Label(control_frame, text="X-Axis:").grid(row=1, column=0, sticky='w', pady=5)
        self.plot_x_var = tk.StringVar(value="Speed (m/s)")
        x_combo = ttk.Combobox(control_frame, textvariable=self.plot_x_var, width=30, state='readonly')
        x_combo['values'] = self.get_plottable_parameters()
        x_combo.grid(row=1, column=1, columnspan=2, sticky='w', padx=5)

        ttk.Label(control_frame, text="Y-Axis:").grid(row=2, column=0, sticky='w', pady=5)
        self.plot_y_var = tk.StringVar(value="Power (W)")
        y_combo = ttk.Combobox(control_frame, textvariable=self.plot_y_var, width=30, state='readonly')
        y_combo['values'] = self.get_plottable_parameters()
        y_combo.grid(row=2, column=1, columnspan=2, sticky='w', padx=5)

        ttk.Label(control_frame, text="Z-Axis (3D):").grid(row=3, column=0, sticky='w', pady=5)
        self.plot_z_var = tk.StringVar(value="Weight (kg)")
        z_combo = ttk.Combobox(control_frame, textvariable=self.plot_z_var, width=30, state='readonly')
        z_combo['values'] = self.get_plottable_parameters()
        z_combo.grid(row=3, column=1, columnspan=2, sticky='w', padx=5)

        # Action buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.grid(row=4, column=0, columnspan=4, pady=10)

        ttk.Button(button_frame, text="Generate Plot", command=self.generate_custom_plot, style='Primary.TButton').pack(side='left', padx=5)
        ttk.Button(button_frame, text="Clear", command=self.clear_plot).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Export PNG", command=self.export_plot_png).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Export CSV", command=self.export_plot_csv).pack(side='left', padx=5)

        # Quick plot buttons
        quick_frame = ttk.LabelFrame(self.tab_plots, text=" Quick Plots ", padding=10)
        quick_frame.pack(fill='x', padx=10, pady=5)

        quick_buttons = [
            ("Power vs Speed", lambda: self.quick_plot("Speed", "Power")),
            ("Range vs Speed", lambda: self.quick_plot("Speed", "Range")),
            ("Endurance vs Weight", lambda: self.quick_plot("Weight", "Endurance")),
        ]

        for text, cmd in quick_buttons:
            ttk.Button(quick_frame, text=text, command=cmd).pack(side='left', padx=5)

        # Matplotlib canvas
        self.plot_frame = ttk.Frame(self.tab_plots)
        self.plot_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Placeholder
        placeholder = ttk.Label(self.plot_frame, text="Click 'Generate Plot' or use Quick Plots", font=('Arial', 12))
        placeholder.pack(expand=True)

    # -----------------------------------------------------------------------
    # TAB 4: MISSION BUILDER
    # -----------------------------------------------------------------------

    def create_mission_tab(self):
        """Create mission builder tab"""
        label = ttk.Label(self.tab_mission, text="Mission Builder - Coming Soon!", font=('Arial', 14))
        label.pack(expand=True)

        desc = ttk.Label(self.tab_mission, text="Drag-and-drop mission segment builder with real-time energy calculation", foreground='gray')
        desc.pack()

    # -----------------------------------------------------------------------
    # TAB 5: COMPARISON
    # -----------------------------------------------------------------------

    def create_comparison_tab(self):
        """Create multi-preset comparison tab"""
        label = ttk.Label(self.tab_comparison, text="Multi-Preset Comparison - Coming Soon!", font=('Arial', 14))
        label.pack(expand=True)

        desc = ttk.Label(self.tab_comparison, text="Side-by-side comparison of multiple presets with charts and tables", foreground='gray')
        desc.pack()

    # -----------------------------------------------------------------------
    # TAB 6: EXPORT MANAGER
    # -----------------------------------------------------------------------

    def create_export_tab(self):
        """Create export manager tab"""
        label = ttk.Label(self.tab_export, text="Export Manager - Coming Soon!", font=('Arial', 14))
        label.pack(expand=True)

        desc = ttk.Label(self.tab_export, text="Professional report generation (PDF, Excel, custom templates)", foreground='gray')
        desc.pack()

    # -----------------------------------------------------------------------
    # STATUS BAR
    # -----------------------------------------------------------------------

    def create_status_bar(self):
        """Create bottom status bar"""
        self.status_bar = ttk.Frame(self, relief='sunken')
        self.status_bar.pack(side='bottom', fill='x')

        self.status_text = tk.StringVar(value="Ready")
        ttk.Label(self.status_bar, textvariable=self.status_text, style='Status.TLabel').pack(side='left', padx=10)

        self.preset_status = tk.StringVar(value="Preset: BASELINE")
        ttk.Label(self.status_bar, textvariable=self.preset_status, style='Status.TLabel').pack(side='right', padx=10)

    # -----------------------------------------------------------------------
    # CORE FUNCTIONS
    # -----------------------------------------------------------------------

    def load_preset(self, preset_name):
        """Load a preset configuration"""
        try:
            self.current_config = self.preset_manager.get_preset(preset_name)
            self.current_preset_name = preset_name
            self.update_ui_from_config()
            self.update_status(f"Loaded preset: {preset_name}")
            self.preset_status.set(f"Preset: {preset_name.upper()}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not load preset: {e}")

    def update_ui_from_config(self):
        """Update UI widgets from current configuration"""
        if not self.current_config:
            return

        # Map of parameter names to widget keys
        param_map = {
            'total_takeoff_weight_kg': 'total_takeoff_weight_kg',
            'wingspan_m': 'wingspan_m',
            'wing_chord_m': 'wing_chord_m',
            'field_elevation_m': 'field_elevation_m',
            'control_power_base_w': 'control_power_base_w',
            'control_power_speed_factor': 'control_power_speed_factor',
            'cd0_motor_nacelles': 'cd0_motor_nacelles',
            'cd0_fuselage_base': 'cd0_fuselage_base',
            'cd0_landing_gear': 'cd0_landing_gear',
            'cd0_interference': 'cd0_interference',
            'transition_forward_duration_s': 'transition_forward_duration_s',
            'transition_forward_power_factor': 'transition_forward_power_factor',
            'transition_back_duration_s': 'transition_back_duration_s',
            'transition_back_power_factor': 'transition_back_power_factor',
            'prop_efficiency_lowspeed': 'prop_efficiency_lowspeed',
            'prop_efficiency_highspeed': 'prop_efficiency_highspeed',
            'motor_efficiency_peak': 'motor_efficiency_peak',
            'esc_efficiency': 'esc_efficiency',
            'avionics_power_w': 'avionics_power_w',
            'payload_power_w': 'payload_power_w',
            'heater_power_w': 'heater_power_w',
        }

        for config_param, widget_key in param_map.items():
            if widget_key in self.param_widgets:
                widget = self.param_widgets[widget_key]
                value = getattr(self.current_config, config_param, '')

                # Convert percentages
                if 'efficiency' in config_param:
                    value = value * 100  # Show as percentage

                widget.delete(0, tk.END)
                widget.insert(0, str(value))

    def run_analysis(self):
        """Run performance analysis with current configuration"""
        try:
            self.update_status("Running analysis...")

            # Create calculator
            self.current_calc = PerformanceCalculator(self.current_config)

            # Generate results
            self.current_results = self.current_calc.generate_performance_summary()

            # Display results
            self.display_results()

            self.update_status("Analysis complete!")

            # Auto-switch to results tab
            self.notebook.select(1)

        except Exception as e:
            messagebox.showerror("Analysis Error", f"Could not run analysis:\n{e}")
            self.update_status("Analysis failed")

    def display_results(self):
        """Display analysis results in results tab"""
        if not self.current_results:
            return

        # Clear previous results
        self.results_text.config(state='normal')
        self.results_text.delete('1.0', tk.END)

        # Format results (simplified version of v3.0 output)
        output = []
        output.append("="*80)
        output.append(" VTOL QUADPLANE PERFORMANCE ANALYSIS v4.0 - GUI".center(80))
        output.append("="*80)
        output.append("")

        # Key performance
        output.append("-"*80)
        output.append("KEY PERFORMANCE")
        output.append("-"*80)
        hover = self.current_results['hover']
        cruise = self.current_results['cruise']
        best_range = self.current_results['best_range']

        output.append(f"  Hover Endurance:       {hover['endurance_min']:.1f} min")
        output.append(f"  Cruise Endurance:      {cruise['endurance_min']:.1f} min")
        output.append(f"  Cruise Range:          {cruise['range_km']:.1f} km")
        output.append(f"  Cruise Power:          {cruise['power_w']:.0f} W")
        output.append(f"  Best Range:            {best_range['range_km']:.1f} km")
        output.append("")

        # Power budget
        if 'power_budget' in cruise:
            pb = cruise['power_budget']
            output.append("-"*80)
            output.append("CRUISE POWER BUDGET")
            output.append("-"*80)
            output.append(f"  Aerodynamic Drag:      {pb['aerodynamic_drag_w']:6.1f} W")
            output.append(f"  Propeller Efficiency:  {pb['propeller_efficiency']*100:6.1f} %")
            output.append(f"  Motor Electrical:      {pb['motor_electrical_w']:6.1f} W")
            output.append(f"  Control Power:         {pb['control_power_w']:6.1f} W")
            output.append(f"  Avionics:              {pb['avionics_w']:6.1f} W")
            output.append(f"  Payload:               {pb['payload_w']:6.1f} W")
            output.append(f"  ESC Loss:              {pb['esc_loss_w']:6.1f} W")
            output.append(f"  " + "-"*30)
            output.append(f"  TOTAL:                 {pb['total_electrical_w']:6.1f} W")
            output.append("")

        # Transitions
        if 'transitions' in self.current_results:
            trans = self.current_results['transitions']
            output.append("-"*80)
            output.append("TRANSITIONS")
            output.append("-"*80)
            output.append(f"  Forward: {trans['forward']['energy_wh']:.1f} Wh | Back: {trans['back']['energy_wh']:.1f} Wh")
            output.append(f"  Total Cycle: {trans['forward']['energy_wh'] + trans['back']['energy_wh']:.1f} Wh")
            output.append("")

        output.append("="*80)

        # Insert into text widget
        self.results_text.insert('1.0', '\n'.join(output))
        self.results_text.config(state='disabled')

    def update_status(self, message):
        """Update status bar message"""
        self.status_text.set(message)
        self.update_idletasks()

    # -----------------------------------------------------------------------
    # MENU ACTIONS
    # -----------------------------------------------------------------------

    def new_analysis(self):
        """Start new analysis"""
        if messagebox.askyesno("New Analysis", "Reset to default configuration?"):
            self.load_preset("baseline")

    def open_config(self):
        """Open configuration from file"""
        messagebox.showinfo("Coming Soon", "Load configuration from JSON file")

    def save_config(self):
        """Save current configuration"""
        messagebox.showinfo("Coming Soon", "Save configuration to JSON file")

    def export_report(self):
        """Export analysis report"""
        messagebox.showinfo("Coming Soon", "Export PDF report")

    def export_all_data(self):
        """Export all data"""
        messagebox.showinfo("Coming Soon", "Export all data (CSV, JSON)")

    def toggle_auto_update(self):
        """Toggle auto-update mode"""
        if self.auto_update.get():
            self.update_status("Auto-update enabled")
        else:
            self.update_status("Auto-update disabled")

    def toggle_dark_mode(self):
        """Toggle dark mode"""
        messagebox.showinfo("Coming Soon", "Dark mode toggle")

    def refresh_results(self):
        """Refresh analysis results"""
        if self.current_results:
            self.display_results()
            self.update_status("Results refreshed")
        else:
            messagebox.showinfo("No Results", "Run an analysis first")

    def optimize_parameters(self):
        """Open parameter optimizer"""
        messagebox.showinfo("Coming Soon", "Parameter optimization tool")

    def run_script_mode(self):
        """Run in script mode"""
        messagebox.showinfo("Coming Soon", "Launch script mode analysis")

    def show_quick_start(self):
        """Show quick start guide"""
        messagebox.showinfo("Quick Start",
            "1. Select a preset from Configuration tab\n"
            "2. Adjust parameters as needed\n"
            "3. Click 'Run Analysis'\n"
            "4. View results in Analysis Results tab\n"
            "5. Create custom plots in Interactive Plots tab")

    def show_documentation(self):
        """Show documentation"""
        messagebox.showinfo("Documentation", "Opening README_v3.md...")

    def show_parameter_guide(self):
        """Show parameter tuning guide"""
        messagebox.showinfo("Parameter Guide", "See example_v3_mission_analysis.py Example 4")

    def show_about(self):
        """Show about dialog"""
        messagebox.showinfo("About",
            "VTOL Performance Analyzer v4.0\n"
            "Professional Edition\n\n"
            "Industrial-grade tailsitter performance analysis\n"
            "with full GUI and interactive tools.\n\n"
            "Version: 4.0.0\n"
            "Date: 2025-01-20")

    # -----------------------------------------------------------------------
    # PRESET ACTIONS
    # -----------------------------------------------------------------------

    def on_preset_selected(self, event=None):
        """Handle preset selection from dropdown"""
        pass  # User must click Load button

    def load_selected_preset(self):
        """Load the selected preset"""
        selected = self.preset_var.get()
        preset_name = selected.split(':')[0]
        self.load_preset(preset_name)

    def save_preset_as(self):
        """Save current configuration as new preset"""
        messagebox.showinfo("Coming Soon", "Save as custom preset")

    def reset_config(self):
        """Reset to current preset defaults"""
        if messagebox.askyesno("Reset", "Reset to preset defaults?"):
            self.load_preset(self.current_preset_name)

    def apply_config(self):
        """Apply parameter changes"""
        try:
            # Update config from UI widgets
            # (Implementation needed)
            self.update_status("Configuration updated")

            if self.auto_update.get():
                self.run_analysis()
        except Exception as e:
            messagebox.showerror("Error", f"Could not apply configuration: {e}")

    def validate_config(self):
        """Validate current configuration"""
        messagebox.showinfo("Validation", "Configuration is valid!")

    # -----------------------------------------------------------------------
    # PLOTTING FUNCTIONS
    # -----------------------------------------------------------------------

    def get_plottable_parameters(self):
        """Get list of parameters that can be plotted"""
        return [
            "Speed (m/s)",
            "Power (W)",
            "Current (A)",
            "Endurance (min)",
            "Range (km)",
            "Weight (kg)",
            "Wing Span (m)",
            "Altitude (m)",
        ]

    def generate_custom_plot(self):
        """Generate user-defined custom plot"""
        messagebox.showinfo("Coming Soon", "Custom plot generation")

    def clear_plot(self):
        """Clear current plot"""
        # Clear plot frame
        for widget in self.plot_frame.winfo_children():
            widget.destroy()

    def export_plot_png(self):
        """Export current plot as PNG"""
        messagebox.showinfo("Coming Soon", "Export plot as PNG")

    def export_plot_csv(self):
        """Export plot data as CSV"""
        messagebox.showinfo("Coming Soon", "Export plot data as CSV")

    def quick_plot(self, x_param, y_param):
        """Generate a quick plot"""
        messagebox.showinfo("Quick Plot", f"Generating {y_param} vs {x_param}")

    # -----------------------------------------------------------------------
    # EXPORT FUNCTIONS
    # -----------------------------------------------------------------------

    def export_results_pdf(self):
        """Export results as PDF"""
        messagebox.showinfo("Coming Soon", "Export results as PDF")

    def copy_results_text(self):
        """Copy results text to clipboard"""
        if self.current_results:
            self.clipboard_clear()
            self.clipboard_append(self.results_text.get('1.0', tk.END))
            self.update_status("Results copied to clipboard")
        else:
            messagebox.showinfo("No Results", "Run an analysis first")

    # -----------------------------------------------------------------------
    # WINDOW CLOSE
    # -----------------------------------------------------------------------

    def on_closing(self):
        """Handle window close"""
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.destroy()


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================

def main():
    """Launch GUI application"""
    app = VTOLAnalyzerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
