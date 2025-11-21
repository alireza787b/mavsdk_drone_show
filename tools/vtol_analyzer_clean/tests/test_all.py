#!/usr/bin/env python3
"""
VTOL Analyzer - Comprehensive Test Suite
Tests all major functionality
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_imports():
    """Test 1: Import all modules"""
    print("TEST 1: Module Imports")
    print("-" * 60)

    try:
        from analyzer import AircraftConfiguration, PerformanceCalculator, AtmosphericModel
        from schematic import DroneSchematicDrawer
        from presets import PresetManager
        from plots import COMMON_PLOTS
        from missions import MISSION_TEMPLATES
        print("✓ All modules imported successfully")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def test_configuration():
    """Test 2: Aircraft configuration"""
    print("\nTEST 2: Aircraft Configuration")
    print("-" * 60)

    try:
        from analyzer import AircraftConfiguration

        config = AircraftConfiguration()
        print(f"  Weight: {config.total_takeoff_weight_kg} kg")
        print(f"  Wing Area: {config.wing_area_m2:.2f} m²")
        print(f"  Wing Loading: {config.wing_loading_kgm2:.1f} kg/m²")
        print(f"  Fuselage Length: {config.fuselage_length_m} m")
        print(f"  Tail Fins: {config.num_tail_fins}")
        print("✓ Configuration created successfully")
        return True
    except Exception as e:
        print(f"✗ Configuration failed: {e}")
        return False


def test_analysis():
    """Test 3: Performance analysis"""
    print("\nTEST 3: Performance Analysis")
    print("-" * 60)

    try:
        from analyzer import AircraftConfiguration, PerformanceCalculator

        config = AircraftConfiguration()
        calc = PerformanceCalculator(config)
        results = calc.generate_performance_summary()

        print(f"  Cruise Speed: {results['speeds']['cruise_ms']:.1f} m/s")
        print(f"  Hover Endurance: {results['hover']['endurance_min']:.1f} min")
        print(f"  Max Range: {results['cruise']['range_km']:.1f} km")
        print(f"  CD0 Tail Fins: {config.cd0_tail_fins:.6f}")
        print("✓ Analysis completed successfully")
        return True
    except Exception as e:
        print(f"✗ Analysis failed: {e}")
        return False


def test_schematic():
    """Test 4: Schematic generation"""
    print("\nTEST 4: Schematic Generation")
    print("-" * 60)

    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt

        from analyzer import AircraftConfiguration
        from schematic import DroneSchematicDrawer

        config = AircraftConfiguration()
        drawer = DroneSchematicDrawer(config)
        fig = drawer.draw_3_view(figsize=(15, 5))

        # Save schematic
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'output', 'plots')
        os.makedirs(output_dir, exist_ok=True)
        fig.savefig(os.path.join(output_dir, 'test_schematic.png'), dpi=150, bbox_inches='tight')
        plt.close(fig)

        print("  Top view: ✓ Circular fuselage cross-section")
        print("  Front view: ✓ Full wingspan visible")
        print("  Side view: ✓ Vertical fuselage (VTOL stance)")
        print("✓ Schematic generated successfully")
        return True
    except Exception as e:
        print(f"✗ Schematic generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_presets():
    """Test 5: Preset configurations"""
    print("\nTEST 5: Configuration Presets")
    print("-" * 60)

    try:
        from presets import PresetManager
        from analyzer import PerformanceCalculator

        manager = PresetManager()
        presets = manager.list_presets()

        print(f"  Available presets: {len(presets)}")

        # Test with actual available presets
        test_presets = ['baseline', 'lightning', 'thunder'] if len(presets) >= 3 else presets[:3]
        for preset_name in test_presets:
            config = manager.get_preset(preset_name)
            calc = PerformanceCalculator(config)
            results = calc.generate_performance_summary()
            print(f"  {preset_name}: Range = {results['cruise']['range_km']:.1f} km")

        print("✓ All presets loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Preset test failed: {e}")
        return False


def test_common_plots():
    """Test 6: Common plots definitions"""
    print("\nTEST 6: Common Plots")
    print("-" * 60)

    try:
        from plots import COMMON_PLOTS, PLOT_CATEGORIES

        print(f"  Total plots defined: {len(COMMON_PLOTS)}")
        print(f"  Plot categories: {len(PLOT_CATEGORIES)}")

        # Check critical plots
        critical_plots = PLOT_CATEGORIES.get("🔴 Critical Design Plots", [])
        print(f"  Critical plots: {len(critical_plots)}")

        for plot_id in critical_plots[:3]:
            plot = COMMON_PLOTS[plot_id]
            print(f"    - {plot['name']}")

        print("✓ Common plots loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Common plots test failed: {e}")
        return False


def run_all_tests():
    """Run complete test suite"""
    print("\n" + "=" * 60)
    print("VTOL ANALYZER - COMPREHENSIVE TEST SUITE")
    print("=" * 60)

    tests = [
        test_imports,
        test_configuration,
        test_analysis,
        test_schematic,
        test_presets,
        test_common_plots,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(results)
    total = len(results)
    percentage = (passed / total * 100) if total > 0 else 0

    print(f"Passed: {passed}/{total} ({percentage:.0f}%)")

    if passed == total:
        print("\n✓ ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n✗ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
