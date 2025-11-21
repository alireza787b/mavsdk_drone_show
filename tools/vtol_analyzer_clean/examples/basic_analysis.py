#!/usr/bin/env python3
"""
Basic Analysis Example
Simple VTOL performance analysis with visualization
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from analyzer import AircraftConfiguration, PerformanceCalculator
import matplotlib.pyplot as plt


def main():
    """Run basic performance analysis"""

    print("=" * 70)
    print("VTOL PERFORMANCE ANALYZER - Basic Analysis Example")
    print("=" * 70)

    # Create configuration
    config = AircraftConfiguration(
        # Basic parameters
        total_takeoff_weight_kg=5.0,
        wingspan_m=2.0,
        wing_chord_m=0.20,

        # Geometry (v4.1)
        fuselage_length_m=1.2,
        fuselage_diameter_m=0.10,
        num_tail_fins=3,
    )

    print("\nConfiguration:")
    print(f"  Weight: {config.total_takeoff_weight_kg} kg")
    print(f"  Wing: {config.wingspan_m}m × {config.wing_chord_m}m")
    print(f"  Wing Area: {config.wing_area_m2:.2f} m²")
    print(f"  Wing Loading: {config.wing_loading_kgm2:.1f} kg/m²")

    # Run analysis
    print("\nRunning analysis...")
    calc = PerformanceCalculator(config)
    results = calc.generate_performance_summary()

    # Display key results
    print("\n" + "=" * 70)
    print("PERFORMANCE RESULTS")
    print("=" * 70)

    print("\n SPEEDS:")
    print(f"  Stall Speed:      {results['speeds']['stall_ms']:.1f} m/s ({results['speeds']['stall_kmh']:.1f} km/h)")
    print(f"  Min Power Speed:  {results['speeds']['min_power_ms']:.1f} m/s")
    print(f"  Cruise Speed:     {results['speeds']['cruise_ms']:.1f} m/s ({results['speeds']['cruise_kmh']:.1f} km/h)")
    print(f"  Max Safe Speed:   {results['speeds']['max_safe_ms']:.1f} m/s")

    print("\n✈️ AERODYNAMICS:")
    print(f"  Max L/D Ratio:    {results['aerodynamics']['max_ld_ratio']:.1f}")
    print(f"  CD0 Total:        {results['aerodynamics']['cd0']:.4f}")
    print(f"  Aspect Ratio:     {results['aerodynamics']['aspect_ratio']:.1f}")

    print("\n🔋 ENDURANCE:")
    print(f"  Hover:            {results['hover']['endurance_min']:.1f} min")
    print(f"  Cruise:           {results['cruise']['endurance_min']:.1f} min")

    print("\n📏 RANGE:")
    print(f"  Best Range:       {results['range']['max_range_km']:.1f} km")
    print(f"  @ Speed:          {results['range']['best_range_speed_ms']:.1f} m/s")

    print("\n⚡ POWER:")
    print(f"  Hover Power:      {results['hover']['power_w']:.0f} W")
    print(f"  Cruise Power:     {results['cruise']['power_w']:.0f} W")

    # Generate visualization
    print("\nGenerating plots...")

    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('VTOL Performance Analysis', fontsize=14, fontweight='bold')

    # Plot 1: Power vs Speed
    speeds = range(10, 26)
    powers = [calc.power_required(v) for v in speeds]
    ax1.plot(speeds, powers, 'b-', linewidth=2)
    ax1.set_xlabel('Speed (m/s)')
    ax1.set_ylabel('Power Required (W)')
    ax1.set_title('Power vs Speed')
    ax1.grid(True, alpha=0.3)
    ax1.axvline(results['speeds']['cruise_ms'], color='r', linestyle='--', label='Cruise Speed')
    ax1.legend()

    # Plot 2: L/D Ratio vs Speed
    ld_ratios = [calc.lift_to_drag_ratio(v) for v in speeds]
    ax2.plot(speeds, ld_ratios, 'g-', linewidth=2)
    ax2.set_xlabel('Speed (m/s)')
    ax2.set_ylabel('L/D Ratio')
    ax2.set_title('Aerodynamic Efficiency')
    ax2.grid(True, alpha=0.3)
    max_ld_speed = speeds[ld_ratios.index(max(ld_ratios))]
    ax2.axvline(max_ld_speed, color='r', linestyle='--', label=f'Max L/D @ {max_ld_speed}m/s')
    ax2.legend()

    # Plot 3: Range vs Speed
    ranges = [calc.range_km(v, calc.endurance(calc.cruise_current(v))) for v in speeds]
    ax3.plot(speeds, ranges, 'purple', linewidth=2)
    ax3.set_xlabel('Speed (m/s)')
    ax3.set_ylabel('Range (km)')
    ax3.set_title('Range vs Speed')
    ax3.grid(True, alpha=0.3)
    best_range_speed = speeds[ranges.index(max(ranges))]
    ax3.axvline(best_range_speed, color='r', linestyle='--', label=f'Best Range @ {best_range_speed}m/s')
    ax3.legend()

    # Plot 4: Current vs Speed
    currents = [calc.cruise_current(v) for v in speeds]
    ax4.plot(speeds, currents, 'orange', linewidth=2)
    ax4.set_xlabel('Speed (m/s)')
    ax4.set_ylabel('Current (A)')
    ax4.set_title('Battery Current vs Speed')
    ax4.grid(True, alpha=0.3)
    ax4.axhline(results['hover']['current_a'], color='b', linestyle='--', label='Hover Current')
    ax4.legend()

    plt.tight_layout()

    # Save plot
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'output', 'plots')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'basic_analysis.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✓ Plot saved to: {output_file}")

    plt.show()

    print("\n" + "=" * 70)
    print("✓ Analysis Complete!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
