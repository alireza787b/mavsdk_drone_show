#!/usr/bin/env python3
"""
Common plot definitions for VTOL Performance Analyzer v4.1

Pre-defined plots that users commonly need for drone analysis.
Each plot has description and configuration for quick access.
"""

COMMON_PLOTS = {
    # === CRITICAL DESIGN PLOTS (Most Used) ===
    "hover_endurance_vs_weight": {
        "name": "🔴 Hover Endurance vs Weight",
        "description": "CRITICAL: How payload weight affects hover time.\nEssential for mission planning and payload sizing.",
        "x_param": "Weight (kg)",
        "y_params": ["Hover Endurance (min)"],
        "x_range": (3, 10, 50),
        "icon": "🔴",
        "category": "critical",
    },

    "hover_current_vs_weight": {
        "name": "🔴 Hover Current vs Weight",
        "description": "CRITICAL: Current draw in hover mode vs weight.\nUse for battery and power system sizing.",
        "x_param": "Weight (kg)",
        "y_params": ["Hover Current (A)"],
        "x_range": (3, 10, 50),
        "icon": "🔴",
        "category": "critical",
    },

    "forward_endurance_vs_weight": {
        "name": "🔴 Forward Flight Endurance vs Weight",
        "description": "CRITICAL: Cruise endurance vs weight.\nKey metric for range missions.",
        "x_param": "Weight (kg)",
        "y_params": ["Forward Flight Endurance (min)"],
        "x_range": (3, 10, 50),
        "icon": "🔴",
        "category": "critical",
    },

    "forward_current_vs_weight": {
        "name": "🔴 Forward Flight Current vs Weight",
        "description": "CRITICAL: Current draw in forward flight.\nCrucial for electrical system design.",
        "x_param": "Weight (kg)",
        "y_params": ["Current (A)"],
        "x_range": (3, 10, 50),
        "icon": "🔴",
        "category": "critical",
    },

    "speeds_vs_weight": {
        "name": "🔴 Cruise & Stall Speed vs Weight",
        "description": "CRITICAL: How weight affects flight speeds.\nSafety margin and operational envelope.",
        "x_param": "Weight (kg)",
        "y_params": ["Cruise Speed (m/s)", "Stall Speed (m/s)"],
        "x_range": (3, 10, 50),
        "icon": "🔴",
        "category": "critical",
    },

    "speeds_vs_span": {
        "name": "🔴 Speeds vs Wing Span",
        "description": "CRITICAL: Wing sizing impact on speeds.\nLarger span = lower speeds.",
        "x_param": "Wing Span (m)",
        "y_params": ["Cruise Speed (m/s)", "Stall Speed (m/s)"],
        "x_range": (1.2, 3.0, 50),
        "icon": "🔴",
        "category": "critical",
    },

    "power_vs_span": {
        "name": "🔴 Cruise Power vs Wing Span",
        "description": "CRITICAL: Wing sizing impact on cruise power.\nLarger span = lower power required.",
        "x_param": "Wing Span (m)",
        "y_params": ["Forward Flight Power (W)"],
        "x_range": (1.2, 3.0, 50),
        "icon": "🔴",
        "category": "critical",
    },

    # === PERFORMANCE OPTIMIZATION ===
    "power_vs_speed": {
        "name": "⚡ Power vs Speed",
        "description": "Power consumption across speed range.\nFind minimum power speed.",
        "x_param": "Speed (m/s)",
        "y_params": ["Forward Flight Power (W)"],
        "x_range": (10, 25, 50),
        "icon": "⚡",
        "category": "performance",
    },

    "range_optimization": {
        "name": "📏 Range vs Speed",
        "description": "Optimal cruise speed for maximum range.",
        "x_param": "Speed (m/s)",
        "y_params": ["Forward Flight Range (km)"],
        "x_range": (10, 25, 50),
        "icon": "📏",
        "category": "performance",
    },

    "current_vs_speed": {
        "name": "🔋 Current vs Speed",
        "description": "Battery current at different speeds.\nFor ESC sizing.",
        "x_param": "Speed (m/s)",
        "y_params": ["Current (A)"],
        "x_range": (10, 25, 50),
        "icon": "🔋",
        "category": "performance",
    },

    # === DESIGN TRADE-OFFS ===
    "endurance_comparison": {
        "name": "⏱️ Hover vs Forward Endurance",
        "description": "Compare hover and forward flight endurance.\nMission profile optimization.",
        "x_param": "Weight (kg)",
        "y_params": ["Hover Endurance (min)", "Forward Flight Endurance (min)"],
        "x_range": (3, 10, 50),
        "icon": "⏱️",
        "category": "trade-offs",
    },

    "altitude_effects": {
        "name": "⛰️ Performance vs Altitude",
        "description": "Altitude impact on power requirements.\nHigh-altitude mission planning.",
        "x_param": "Altitude (m)",
        "y_params": ["Forward Flight Power (W)", "Hover Power (W)"],
        "x_range": (0, 3000, 50),
        "icon": "⛰️",
        "category": "trade-offs",
    },

    "wing_sizing": {
        "name": "🦅 Wing Span Trade-offs",
        "description": "Wing size vs performance metrics.\nOptimal span for mission requirements.",
        "x_param": "Wing Span (m)",
        "y_params": ["Forward Flight Range (km)", "Max L/D Ratio"],
        "x_range": (1.2, 3.0, 50),
        "icon": "🦅",
        "category": "trade-offs",
    },

    "efficiency_analysis": {
        "name": "📊 Propeller Efficiency vs Speed",
        "description": "Propeller efficiency across speed range.\nProp selection validation.",
        "x_param": "Speed (m/s)",
        "y_params": ["Propeller Efficiency (%)"],
        "x_range": (10, 25, 50),
        "icon": "📊",
        "category": "trade-offs",
    },
}

# Plot categories for organized display
PLOT_CATEGORIES = {
    "🔴 Critical Design Plots": [
        "hover_endurance_vs_weight",
        "hover_current_vs_weight",
        "forward_endurance_vs_weight",
        "forward_current_vs_weight",
        "speeds_vs_weight",
        "speeds_vs_span",
        "power_vs_span",
    ],
    "⚡ Performance Optimization": [
        "power_vs_speed",
        "range_optimization",
        "current_vs_speed",
    ],
    "📊 Design Trade-offs": [
        "endurance_comparison",
        "altitude_effects",
        "wing_sizing",
        "efficiency_analysis",
    ],
}

def get_common_plot(plot_id):
    """Get common plot configuration by ID"""
    return COMMON_PLOTS.get(plot_id)

def list_common_plots():
    """List all available common plots"""
    return list(COMMON_PLOTS.keys())

def get_plot_by_category(category):
    """Get plots in a specific category"""
    return PLOT_CATEGORIES.get(category, [])
