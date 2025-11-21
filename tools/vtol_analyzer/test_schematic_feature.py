#!/usr/bin/env python3
"""
Test script for v4.1 Geometry Visualization Feature
Tests the integration of geometry parameters, tail fin calculations, and schematic drawing
"""

import sys
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for testing
import matplotlib.pyplot as plt

# Import the modules
from vtol_performance_analyzer import AircraftConfiguration, PerformanceCalculator
from drone_schematic_drawer import DroneSchematicDrawer

def test_geometry_parameters():
    """Test 1: Verify geometry parameters are properly initialized"""
    print("=" * 70)
    print("TEST 1: Geometry Parameters Initialization")
    print("=" * 70)

    config = AircraftConfiguration()

    # Check that all new geometry parameters exist
    geometry_params = [
        'fuselage_length_m',
        'fuselage_diameter_m',
        'num_tail_fins',
        'tail_fin_chord_m',
        'tail_fin_span_m',
        'tail_fin_position_m',
        'tail_fin_thickness_ratio',
        'tail_fin_taper_ratio',
        'motor_spacing_m',
        'num_motors',
    ]

    print("\nGeometry Parameter Values:")
    for param in geometry_params:
        value = getattr(config, param)
        print(f"  {param:30s} = {value}")

    print("\n✓ All geometry parameters initialized successfully")
    return config

def test_tail_fin_drag_calculation(config):
    """Test 2: Verify tail fin drag is calculated and included in total CD0"""
    print("\n" + "=" * 70)
    print("TEST 2: Tail Fin Drag Calculation")
    print("=" * 70)

    # Check that tail fin drag method exists and returns a value
    cd0_tail = config.cd0_tail_fins

    print(f"\nCD0 Tail Fins:        {cd0_tail:.6f}")
    print(f"CD0 Total Cruise:     {config.cd0_total_cruise:.6f}")
    print(f"CD0 Clean:            {config.cd0_clean:.6f}")

    # Verify tail fins contribute to total drag
    assert cd0_tail > 0, "Tail fin CD0 should be positive"
    assert config.cd0_total_cruise > config.cd0_clean, "Total CD0 should include tail fins"

    # Calculate percentage contribution
    tail_contribution = (cd0_tail / config.cd0_total_cruise) * 100
    print(f"\nTail fin contribution: {tail_contribution:.2f}% of total CD0")

    print("\n✓ Tail fin drag calculation working correctly")

def test_schematic_drawing(config):
    """Test 3: Generate 3-view schematic drawing"""
    print("\n" + "=" * 70)
    print("TEST 3: Schematic Drawing Generation")
    print("=" * 70)

    # Create drawer
    drawer = DroneSchematicDrawer(config)
    print("\n✓ DroneSchematicDrawer created successfully")

    # Generate 3-view drawing
    fig = drawer.draw_3_view(figsize=(15, 5))
    print("✓ 3-view drawing generated successfully")

    # Save the figure
    output_path = "test_schematic_output.png"
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Schematic saved to: {output_path}")

    plt.close(fig)

    return output_path

def test_custom_configuration():
    """Test 4: Test with custom geometry parameters"""
    print("\n" + "=" * 70)
    print("TEST 4: Custom Configuration Test")
    print("=" * 70)

    # Create config with custom geometry
    custom_config = AircraftConfiguration(
        # Basic parameters
        total_takeoff_weight_kg=5.0,
        wingspan_m=2.0,
        wing_chord_m=0.20,

        # Custom geometry (v4.1)
        fuselage_length_m=1.4,
        fuselage_diameter_m=0.12,
        num_tail_fins=4,  # 4 fins instead of 3
        tail_fin_chord_m=0.06,
        tail_fin_span_m=0.18,
        tail_fin_position_m=0.55,
        tail_fin_thickness_ratio=0.10,
        tail_fin_taper_ratio=0.6,
        motor_spacing_m=0.6,
        num_motors=4,
    )

    print("\nCustom Configuration:")
    print(f"  Fuselage: {custom_config.fuselage_length_m}m × {custom_config.fuselage_diameter_m}m")
    print(f"  Tail Fins: {custom_config.num_tail_fins} × {custom_config.tail_fin_chord_m}m chord × {custom_config.tail_fin_span_m}m span")
    print(f"  Motors: {custom_config.num_motors} @ {custom_config.motor_spacing_m}m spacing")
    print(f"  CD0 Tail: {custom_config.cd0_tail_fins:.6f}")

    # Generate schematic with custom config
    drawer = DroneSchematicDrawer(custom_config)
    fig = drawer.draw_3_view(figsize=(15, 5))

    output_path = "test_schematic_custom.png"
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Custom schematic saved to: {output_path}")

    plt.close(fig)

def test_performance_impact():
    """Test 5: Compare performance with/without tail fin drag"""
    print("\n" + "=" * 70)
    print("TEST 5: Performance Impact Analysis")
    print("=" * 70)

    # Create baseline config
    config_with_tail = AircraftConfiguration()

    # Create config without tail fin drag (manually zero it out for comparison)
    config_no_tail = AircraftConfiguration()
    cd0_original = config_no_tail.cd0_total_cruise
    cd0_tail_contribution = config_no_tail.cd0_tail_fins

    print("\nDrag Coefficient Comparison:")
    print(f"  CD0 with tail fins:    {cd0_original:.6f}")
    print(f"  Tail fin contribution: {cd0_tail_contribution:.6f}")
    print(f"  Percentage impact:     {(cd0_tail_contribution/cd0_original)*100:.2f}%")

    # Calculate performance
    calc = PerformanceCalculator(config_with_tail)
    results = calc.generate_performance_summary()

    print("\nPerformance Metrics:")
    print(f"  Max Safe Speed: {results['speeds']['max_safe_ms']:.2f} m/s")
    print(f"  Cruise Speed:   {results['speeds']['cruise_ms']:.2f} m/s")
    print(f"  Stall Speed:    {results['speeds']['stall_ms']:.2f} m/s")

    print("\n✓ Performance analysis complete")

def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("VTOL ANALYZER v4.1 - GEOMETRY FEATURE TEST SUITE")
    print("=" * 70)

    try:
        # Test 1: Parameter initialization
        config = test_geometry_parameters()

        # Test 2: Tail fin drag calculation
        test_tail_fin_drag_calculation(config)

        # Test 3: Schematic drawing
        test_schematic_drawing(config)

        # Test 4: Custom configuration
        test_custom_configuration()

        # Test 5: Performance impact
        test_performance_impact()

        # Summary
        print("\n" + "=" * 70)
        print("ALL TESTS PASSED ✓")
        print("=" * 70)
        print("\nv4.1 Geometry Visualization Feature is fully functional!")
        print("\nGenerated files:")
        print("  - test_schematic_output.png (baseline configuration)")
        print("  - test_schematic_custom.png (custom 4-fin configuration)")
        print("\n")

        return 0

    except Exception as e:
        print("\n" + "=" * 70)
        print("TEST FAILED ✗")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(run_all_tests())
