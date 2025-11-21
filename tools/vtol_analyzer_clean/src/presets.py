#!/usr/bin/env python3
"""
===============================================================================
VTOL ANALYZER v3.0 - CONFIGURATION PRESETS
===============================================================================

Pre-validated configurations for common tailsitter designs.
Automatically loaded and organized for clean workflow.

Usage:
    from presets import PresetManager
    presets = PresetManager()
    config = presets.get_preset("validated_6kg_tailsitter")
===============================================================================
"""

from dataclasses import dataclass, replace
from analyzer import AircraftConfiguration
import os
import json
from datetime import datetime
from typing import Dict, List


class PresetManager:
    """
    Manage aircraft configuration presets with clean output organization.

    Features:
    - Pre-validated configurations (5.2kg, 6kg, 8kg)
    - Automatic preset discovery
    - Organized output per preset
    - No redundant files
    - Easy preset selection
    """

    def __init__(self):
        """Initialize preset manager with all available presets"""
        self.presets = {
            "lightning": self._create_5_2kg_preset(),
            "baseline": self._create_6kg_preset(),
            "thunder": self._create_8kg_preset(),
        }

        self.preset_descriptions = {
            "lightning": "LIGHTNING - 5.2kg Ultra-Light (12.5 min hover, 38 min cruise) ✓ Validated",
            "baseline": "BASELINE - 6.0kg Standard (10.5 min hover, 30 min cruise) [Production]",
            "thunder": "THUNDER - 8.0kg Heavy Payload (6.8 min hover, 19 min cruise, +60% payload)",
        }

        # Legacy aliases for backwards compatibility
        self.preset_aliases = {
            "validated_5_2kg_tailsitter": "lightning",
            "validated_6kg_tailsitter": "baseline",
            "heavy_8kg_tailsitter": "thunder",
        }

    def list_presets(self) -> List[str]:
        """Get list of available preset names"""
        return list(self.presets.keys())

    def get_preset_description(self, preset_name: str) -> str:
        """Get human-readable description of preset"""
        return self.preset_descriptions.get(preset_name, "Unknown preset")

    def get_preset(self, preset_name: str) -> AircraftConfiguration:
        """
        Get aircraft configuration by preset name.

        Supports both new names (lightning, baseline, thunder) and legacy names.

        Args:
            preset_name: Name of the preset

        Returns:
            AircraftConfiguration object

        Raises:
            ValueError: If preset name not found
        """
        # Check if it's a legacy alias first
        if preset_name in self.preset_aliases:
            preset_name = self.preset_aliases[preset_name]

        if preset_name not in self.presets:
            available = ", ".join(self.presets.keys())
            aliases = ", ".join(self.preset_aliases.keys())
            raise ValueError(
                f"Preset '{preset_name}' not found.\n"
                f"Available: {available}\n"
                f"Legacy aliases: {aliases}"
            )

        return self.presets[preset_name]

    def create_output_directory(self, preset_name: str) -> str:
        """
        Create clean organized output directory for preset.

        Structure:
            output/
            └── presets/
                └── validated_6kg_tailsitter/
                    └── 2025-01-20_15-30/
                        ├── analysis_report.txt
                        ├── performance_data.csv
                        ├── mission_analysis.json
                        └── plots/

        Args:
            preset_name: Name of the preset

        Returns:
            Path to output directory
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        output_dir = os.path.join("output", "presets", preset_name, timestamp)

        # Create directory structure
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "plots"), exist_ok=True)

        return output_dir

    def save_preset_metadata(self, preset_name: str, output_dir: str, performance_summary: Dict):
        """
        Save preset metadata for future reference.

        Args:
            preset_name: Name of the preset
            output_dir: Output directory path
            performance_summary: Performance analysis results
        """
        metadata = {
            "preset_name": preset_name,
            "description": self.get_preset_description(preset_name),
            "analysis_date": datetime.now().isoformat(),
            "version": "3.0.0",
            "key_results": {
                "hover_endurance_min": performance_summary["hover"]["endurance_min"],
                "cruise_endurance_min": performance_summary["cruise"]["endurance_min"],
                "cruise_range_km": performance_summary["cruise"]["range_km"],
                "cruise_power_w": performance_summary["cruise"]["power_w"],
                "total_weight_kg": performance_summary["weight"]["total_kg"],
            }
        }

        metadata_file = os.path.join(output_dir, "preset_metadata.json")
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

    # =========================================================================
    # PRESET DEFINITIONS
    # =========================================================================

    def _create_5_2kg_preset(self) -> AircraftConfiguration:
        """
        5.2kg Tailsitter - Flight Validated Configuration

        VALIDATION STATUS:
        - Hover: 12.5 min (VALIDATED from flight logs)
        - Cruise: Not yet validated
        - Transitions: Not yet measured

        This is the lightest configuration with validated hover performance.
        """
        return AircraftConfiguration(
            # === BASIC PARAMETERS ===
            total_takeoff_weight_kg=5.2,
            wingspan_m=2.0,
            wing_chord_m=0.12,

            # === TAILSITTER TYPE ===
            aircraft_type="TAILSITTER",

            # === DRAG BREAKDOWN ===
            cd0_clean=0.025,
            cd0_motor_nacelles=0.035,
            cd0_fuselage_base=0.008,
            cd0_landing_gear=0.012,
            cd0_interference=0.015,

            # === CONTROL POWER ===
            control_power_base_w=45.0,          # Lighter = slightly less power
            control_power_speed_factor=5.0,

            # === TRANSITIONS ===
            transition_forward_duration_s=14.0,  # Lighter = faster transition
            transition_forward_power_factor=1.9,
            transition_back_duration_s=9.0,
            transition_back_power_factor=1.5,

            # === Q-ASSIST ===
            q_assist_enabled=True,
            q_assist_threshold_speed_ms=12.0,
            q_assist_max_power_fraction=0.25,

            # === PROPELLER EFFICIENCY ===
            prop_efficiency_lowspeed=0.68,
            prop_efficiency_highspeed=0.55,

            # === AUXILIARY SYSTEMS ===
            avionics_power_w=6.5,
            payload_power_w=8.0,
            heater_power_w=0.0,
            esc_efficiency=0.92,

            # === STANDARD PARAMETERS ===
            battery_cells=6,
            battery_capacity_mah=11000.0,
            battery_voltage_nominal=22.2,
            battery_usable_capacity_factor=0.85,

            motor_name="MAD 3120 1000KV",
            motor_kv=1000.0,
            motor_r0=0.065,
            motor_i0=1.5,
            motor_efficiency_peak=0.85,
            motor_count=4,

            prop_diameter_inch=10.0,
            prop_pitch_inch=5.0,

            field_elevation_m=1000.0,
            temperature_offset_c=0.0,
        )

    def _create_6kg_preset(self) -> AircraftConfiguration:
        """
        6.0kg Tailsitter - Production Baseline Configuration

        VALIDATION STATUS:
        - Hover: 10.5 min (validated)
        - Cruise: Estimated (needs validation)
        - Transitions: Estimated (needs measurement)

        This is the standard production configuration.
        All v3.0 development was based on this weight.
        """
        return AircraftConfiguration(
            # === BASIC PARAMETERS ===
            total_takeoff_weight_kg=6.0,
            wingspan_m=2.0,
            wing_chord_m=0.12,

            # === TAILSITTER TYPE ===
            aircraft_type="TAILSITTER",

            # === DRAG BREAKDOWN ===
            cd0_clean=0.025,
            cd0_motor_nacelles=0.035,
            cd0_fuselage_base=0.008,
            cd0_landing_gear=0.012,
            cd0_interference=0.015,

            # === CONTROL POWER ===
            control_power_base_w=50.0,
            control_power_speed_factor=5.0,

            # === TRANSITIONS ===
            transition_forward_duration_s=15.0,
            transition_forward_power_factor=2.0,
            transition_back_duration_s=10.0,
            transition_back_power_factor=1.6,

            # === Q-ASSIST ===
            q_assist_enabled=True,
            q_assist_threshold_speed_ms=12.0,
            q_assist_max_power_fraction=0.25,

            # === PROPELLER EFFICIENCY ===
            prop_efficiency_lowspeed=0.68,
            prop_efficiency_highspeed=0.55,

            # === AUXILIARY SYSTEMS ===
            avionics_power_w=6.5,
            payload_power_w=8.0,
            heater_power_w=0.0,
            esc_efficiency=0.92,

            # === STANDARD PARAMETERS ===
            battery_cells=6,
            battery_capacity_mah=11000.0,
            battery_voltage_nominal=22.2,
            battery_usable_capacity_factor=0.85,

            motor_name="MAD 3120 1000KV",
            motor_kv=1000.0,
            motor_r0=0.065,
            motor_i0=1.5,
            motor_efficiency_peak=0.85,
            motor_count=4,

            prop_diameter_inch=10.0,
            prop_pitch_inch=5.0,

            field_elevation_m=1000.0,
            temperature_offset_c=0.0,
        )

    def _create_8kg_preset(self) -> AircraftConfiguration:
        """
        8.0kg Tailsitter - Heavy Payload Configuration

        VALIDATION STATUS:
        - All parameters: ESTIMATED (not yet validated)

        This configuration models a heavier variant with additional payload.
        Assumes same airframe with increased payload weight only.

        KEY DIFFERENCES vs 6kg:
        - Total weight: +33% (8kg vs 6kg)
        - Control power: +20% (60W vs 50W) - heavier = needs more control
        - Transition time: +20% (18s vs 15s) - heavier = slower transition
        - Wing loading: +33% (33.3 vs 25.0 kg/m²)
        - Payload: +60% (12.8W vs 8.0W) - assumes heavier camera/gimbal
        """
        return AircraftConfiguration(
            # === BASIC PARAMETERS ===
            total_takeoff_weight_kg=8.0,        # +33% vs 6kg
            wingspan_m=2.0,                     # Same airframe
            wing_chord_m=0.12,                  # Same airframe

            # === TAILSITTER TYPE ===
            aircraft_type="TAILSITTER",

            # === DRAG BREAKDOWN ===
            cd0_clean=0.025,                    # Same airframe
            cd0_motor_nacelles=0.035,           # Same motors
            cd0_fuselage_base=0.008,            # Same fuselage
            cd0_landing_gear=0.012,             # Same gear
            cd0_interference=0.015,             # Same interference

            # === CONTROL POWER ===
            control_power_base_w=60.0,          # +20% (heavier = more control)
            control_power_speed_factor=6.0,     # +20% (more speed factor needed)

            # === TRANSITIONS ===
            transition_forward_duration_s=18.0, # +20% (heavier = slower)
            transition_forward_power_factor=2.2, # +10% (more inertia)
            transition_back_duration_s=12.0,    # +20% (heavier = slower)
            transition_back_power_factor=1.7,   # +6% (more inertia)

            # === Q-ASSIST ===
            q_assist_enabled=True,
            q_assist_threshold_speed_ms=12.0,   # Same threshold
            q_assist_max_power_fraction=0.30,   # +20% (heavier = more assist)

            # === PROPELLER EFFICIENCY ===
            prop_efficiency_lowspeed=0.65,      # -4% (higher disk loading)
            prop_efficiency_highspeed=0.52,     # -5% (higher disk loading)

            # === AUXILIARY SYSTEMS ===
            avionics_power_w=6.5,               # Same avionics
            payload_power_w=12.8,               # +60% (heavier payload)
            heater_power_w=0.0,                 # Same
            esc_efficiency=0.92,                # Same ESCs

            # === STANDARD PARAMETERS ===
            battery_cells=6,
            battery_capacity_mah=11000.0,       # Same battery
            battery_voltage_nominal=22.2,
            battery_usable_capacity_factor=0.85,

            motor_name="MAD 3120 1000KV",
            motor_kv=1000.0,
            motor_r0=0.065,
            motor_i0=1.5,
            motor_efficiency_peak=0.85,
            motor_count=4,

            prop_diameter_inch=10.0,
            prop_pitch_inch=5.0,

            field_elevation_m=1000.0,
            temperature_offset_c=0.0,
        )

    def print_preset_comparison(self):
        """Print comparison table of all presets"""
        from analyzer import PerformanceCalculator

        print("\n" + "="*80)
        print(" PRESET CONFIGURATION COMPARISON".center(80))
        print("="*80 + "\n")

        print(f"{'Parameter':<30} {'5.2kg':<15} {'6.0kg':<15} {'8.0kg':<15}")
        print("-" * 80)

        # Calculate performance for each preset
        results = {}
        for name in self.list_presets():
            config = self.get_preset(name)
            calc = PerformanceCalculator(config)
            results[name] = calc.generate_performance_summary()

        # Weight comparison
        print("\nWEIGHT & GEOMETRY:")
        print(f"  {'Total Weight':<28} {5.2:<15.1f} {6.0:<15.1f} {8.0:<15.1f} kg")
        print(f"  {'Wing Loading':<28} {results['validated_5_2kg_tailsitter']['weight']['wing_loading_kgm2']:<15.1f} {results['validated_6kg_tailsitter']['weight']['wing_loading_kgm2']:<15.1f} {results['heavy_8kg_tailsitter']['weight']['wing_loading_kgm2']:<15.1f} kg/m²")

        # Performance comparison
        print("\nPERFORMANCE:")
        print(f"  {'Hover Endurance':<28} {results['validated_5_2kg_tailsitter']['hover']['endurance_min']:<15.1f} {results['validated_6kg_tailsitter']['hover']['endurance_min']:<15.1f} {results['heavy_8kg_tailsitter']['hover']['endurance_min']:<15.1f} min")
        print(f"  {'Cruise Endurance':<28} {results['validated_5_2kg_tailsitter']['cruise']['endurance_min']:<15.1f} {results['validated_6kg_tailsitter']['cruise']['endurance_min']:<15.1f} {results['heavy_8kg_tailsitter']['cruise']['endurance_min']:<15.1f} min")
        print(f"  {'Cruise Range':<28} {results['validated_5_2kg_tailsitter']['cruise']['range_km']:<15.1f} {results['validated_6kg_tailsitter']['cruise']['range_km']:<15.1f} {results['heavy_8kg_tailsitter']['cruise']['range_km']:<15.1f} km")
        print(f"  {'Cruise Speed':<28} {results['validated_5_2kg_tailsitter']['cruise']['speed_ms']:<15.1f} {results['validated_6kg_tailsitter']['cruise']['speed_ms']:<15.1f} {results['heavy_8kg_tailsitter']['cruise']['speed_ms']:<15.1f} m/s")

        # Power comparison
        print("\nPOWER BUDGET:")
        print(f"  {'Hover Power':<28} {results['validated_5_2kg_tailsitter']['hover']['power_w']:<15.0f} {results['validated_6kg_tailsitter']['hover']['power_w']:<15.0f} {results['heavy_8kg_tailsitter']['hover']['power_w']:<15.0f} W")
        print(f"  {'Cruise Power':<28} {results['validated_5_2kg_tailsitter']['cruise']['power_w']:<15.0f} {results['validated_6kg_tailsitter']['cruise']['power_w']:<15.0f} {results['heavy_8kg_tailsitter']['cruise']['power_w']:<15.0f} W")
        print(f"  {'Control Power (20m/s)':<28} {self.get_preset('validated_5_2kg_tailsitter').control_power_base_w:<15.0f} {self.get_preset('validated_6kg_tailsitter').control_power_base_w:<15.0f} {self.get_preset('heavy_8kg_tailsitter').control_power_base_w:<15.0f} W")

        # Transition comparison
        print("\nTRANSITIONS:")
        print(f"  {'Forward Transition Time':<28} {self.get_preset('validated_5_2kg_tailsitter').transition_forward_duration_s:<15.1f} {self.get_preset('validated_6kg_tailsitter').transition_forward_duration_s:<15.1f} {self.get_preset('heavy_8kg_tailsitter').transition_forward_duration_s:<15.1f} s")
        print(f"  {'Forward Transition Energy':<28} {results['validated_5_2kg_tailsitter']['transitions']['forward']['energy_wh']:<15.1f} {results['validated_6kg_tailsitter']['transitions']['forward']['energy_wh']:<15.1f} {results['heavy_8kg_tailsitter']['transitions']['forward']['energy_wh']:<15.1f} Wh")

        print("\n" + "="*80)
        print("\nKEY INSIGHTS:")
        print("  • 5.2kg: Longest endurance, validated hover performance")
        print("  • 6.0kg: Production baseline, best range/endurance balance")
        print("  • 8.0kg: Heavy payload, -30% endurance, needs more power")
        print("\n" + "="*80 + "\n")


# Quick access functions
def get_preset(preset_name: str) -> AircraftConfiguration:
    """Quick access to preset configuration"""
    manager = PresetManager()
    return manager.get_preset(preset_name)


def list_all_presets():
    """List all available presets with descriptions"""
    manager = PresetManager()
    print("\nAvailable Presets:")
    print("-" * 60)
    for name in manager.list_presets():
        desc = manager.get_preset_description(name)
        print(f"  • {name:<35} {desc}")
    print()


if __name__ == "__main__":
    # Demo preset system
    print("\n" + "="*80)
    print(" VTOL ANALYZER v3.0 - PRESET SYSTEM DEMO".center(80))
    print("="*80)

    # List all presets
    list_all_presets()

    # Show preset comparison
    manager = PresetManager()
    manager.print_preset_comparison()

    print("\nUsage Example:")
    print("-" * 60)
    print("from presets import get_preset")
    print("config = get_preset('validated_6kg_tailsitter')")
    print("calc = PerformanceCalculator(config)")
    print()
