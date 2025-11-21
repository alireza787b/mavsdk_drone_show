"""
VTOL Performance Analyzer v4.1.2
Professional VTOL aircraft design and analysis tool

Main components:
- analyzer: Core performance calculations and aerodynamic modeling
- gui: Interactive GUI application
- schematic: 3D visualization and engineering drawings
- presets: Pre-configured aircraft designs
- plots: Common analysis plots
- missions: Mission planning templates
"""

from .analyzer import AircraftConfiguration, PerformanceCalculator, AtmosphericModel
from .presets import PresetManager
from .plots import COMMON_PLOTS, PLOT_CATEGORIES

__version__ = "4.1.2"
__author__ = "VTOL Analyzer Team"

__all__ = [
    'AircraftConfiguration',
    'PerformanceCalculator',
    'AtmosphericModel',
    'PresetManager',
    'COMMON_PLOTS',
    'PLOT_CATEGORIES',
]
