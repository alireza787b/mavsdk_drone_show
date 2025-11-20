#!/usr/bin/env python3
"""
Common plot definitions for VTOL Performance Analyzer v4.1

Pre-defined plots that users commonly need for drone analysis.
Each plot has description and configuration for quick access.
"""

COMMON_PLOTS = {
    "power_vs_speed": {
        "name": "Power vs Speed",
        "description": "Shows how power consumption changes with flight speed.\nFind the most efficient cruise speed.",
        "x_param": "Speed (m/s)",
        "y_params": ["Forward Flight Power (W)"],
        "x_range": (10, 25, 50),  # min, max, points
        "icon": "⚡",
    },

    "range_optimization": {
        "name": "Range vs Speed",
        "description": "Find optimal cruise speed for maximum range.\nPeak of curve = best speed for distance.",
        "x_param": "Speed (m/s)",
        "y_params": ["Forward Flight Range (km)"],
        "x_range": (10, 25, 50),
        "icon": "📏",
    },

    "endurance_vs_weight": {
        "name": "Endurance vs Weight",
        "description": "See how payload weight affects flight time.\nUse for mission planning with variable payload.",
        "x_param": "Weight (kg)",
        "y_params": ["Hover Endurance (min)", "Forward Flight Endurance (min)"],
        "x_range": (4, 8, 50),
        "icon": "⏱️",
    },

    "efficiency_analysis": {
        "name": "Efficiency vs Speed",
        "description": "System efficiency across speed range.\nHigher efficiency = longer flight time.",
        "x_param": "Speed (m/s)",
        "y_params": ["Propeller Efficiency (%)"],
        "x_range": (10, 25, 50),
        "icon": "📊",
    },

    "ld_performance": {
        "name": "L/D Ratio vs Speed",
        "description": "Aerodynamic efficiency curve.\nHigher L/D = better glide performance.",
        "x_param": "Speed (m/s)",
        "y_params": ["L/D Ratio"],
        "x_range": (10, 25, 50),
        "icon": "✈️",
    },

    "current_vs_speed": {
        "name": "Current vs Speed",
        "description": "Battery current draw at different speeds.\nUse for battery and ESC sizing.",
        "x_param": "Speed (m/s)",
        "y_params": ["Current (A)"],
        "x_range": (10, 25, 50),
        "icon": "🔋",
    },

    "altitude_effects": {
        "name": "Performance vs Altitude",
        "description": "How altitude affects performance.\nHigher altitude = less dense air = more power needed.",
        "x_param": "Altitude (m)",
        "y_params": ["Forward Flight Power (W)", "Hover Power (W)"],
        "x_range": (0, 3000, 50),
        "icon": "⛰️",
    },

    "wing_sizing": {
        "name": "Performance vs Wing Span",
        "description": "Effect of wing size on performance.\nLarger wings = better efficiency but more drag.",
        "x_param": "Wing Span (m)",
        "y_params": ["Forward Flight Range (km)", "Max L/D Ratio"],
        "x_range": (1.5, 2.5, 50),
        "icon": "🦅",
    },
}

# Plot categories for organization
PLOT_CATEGORIES = {
    "Performance": ["power_vs_speed", "range_optimization", "efficiency_analysis"],
    "Design Trade-offs": ["endurance_vs_weight", "wing_sizing", "altitude_effects"],
    "Technical": ["ld_performance", "current_vs_speed"],
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
