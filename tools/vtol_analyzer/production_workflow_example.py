#!/usr/bin/env python3
"""
===============================================================================
VTOL ANALYZER v3.0 - PRODUCTION WORKFLOW EXAMPLE
===============================================================================

Demonstrates best practices for production use:
- Clean preset selection
- Organized output management
- No redundant files
- Professional workflow
===============================================================================
"""

from config_presets import PresetManager, get_preset
from vtol_performance_analyzer import (
    PerformanceCalculator,
    ReportGenerator
)
import os
import json


def run_analysis_with_preset(preset_name: str, mission_segments=None):
    """
    Complete analysis workflow with clean output management.

    Args:
        preset_name: Name of configuration preset
        mission_segments: Optional mission profile to analyze

    Returns:
        Output directory path
    """
    print("\n" + "="*80)
    print(f" ANALYZING: {preset_name}".center(80))
    print("="*80 + "\n")

    # 1. Initialize preset manager
    manager = PresetManager()

    # 2. Load configuration
    config = manager.get_preset(preset_name)
    print(f"✓ Loaded preset: {manager.get_preset_description(preset_name)}")

    # 3. Create clean output directory
    output_dir = manager.create_output_directory(preset_name)
    print(f"✓ Output directory: {output_dir}")

    # 4. Run performance analysis
    calc = PerformanceCalculator(config)
    perf = calc.generate_performance_summary()
    print(f"✓ Performance analysis completed")

    # 5. Save analysis report
    report_file = os.path.join(output_dir, "analysis_report.txt")
    import sys
    from io import StringIO

    # Capture console output
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    ReportGenerator.print_performance_report(perf, config)
    report_text = mystdout.getvalue()
    sys.stdout = old_stdout

    with open(report_file, 'w') as f:
        f.write(report_text)
    print(f"✓ Report saved: analysis_report.txt")

    # 6. Save performance data as JSON
    performance_file = os.path.join(output_dir, "performance_data.json")
    with open(performance_file, 'w') as f:
        # Convert numpy/complex types to serializable format
        def make_serializable(obj):
            if isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_serializable(item) for item in obj]
            elif hasattr(obj, 'item'):  # numpy types
                return obj.item()
            else:
                return obj

        json.dump(make_serializable(perf), f, indent=2)
    print(f"✓ Data saved: performance_data.json")

    # 7. Run mission profile analysis (if provided)
    if mission_segments:
        mission = calc.mission_profile_analysis(mission_segments)

        mission_file = os.path.join(output_dir, "mission_analysis.json")
        with open(mission_file, 'w') as f:
            json.dump(mission, f, indent=2)
        print(f"✓ Mission analysis saved: mission_analysis.json")

        # Print mission summary
        print(f"\n  Mission Summary:")
        print(f"    Total Time:      {mission['total_time_min']:.1f} min")
        print(f"    Energy Used:     {mission['total_energy_wh']:.1f} Wh")
        print(f"    Battery Reserve: {mission['battery_remaining_percent']:.1f}%")

        if mission['battery_remaining_percent'] < 20:
            print(f"    ⚠ WARNING: Mission NOT FEASIBLE (reserve < 20%)")
        else:
            print(f"    ✓ Mission FEASIBLE")

    # 8. Save preset metadata
    manager.save_preset_metadata(preset_name, output_dir, perf)
    print(f"✓ Metadata saved: preset_metadata.json")

    # 9. Print key results
    print(f"\n  Key Results:")
    print(f"    Hover Endurance:  {perf['hover']['endurance_min']:.1f} min")
    print(f"    Cruise Endurance: {perf['cruise']['endurance_min']:.1f} min")
    print(f"    Cruise Range:     {perf['cruise']['range_km']:.1f} km")
    print(f"    Cruise Power:     {perf['cruise']['power_w']:.0f} W")

    print(f"\n✓ Analysis complete! Output: {output_dir}")
    print("="*80 + "\n")

    return output_dir


def analyze_all_presets():
    """
    Run analysis for all presets and create comparison summary.
    """
    print("\n" + "="*80)
    print(" BATCH ANALYSIS: ALL PRESETS".center(80))
    print("="*80 + "\n")

    manager = PresetManager()
    results = {}

    # Define standard mission for comparison
    standard_mission = [
        {'type': 'hover', 'duration_s': 60},
        {'type': 'transition_forward'},
        {'type': 'cruise', 'duration_s': 900, 'speed_ms': 15.0},  # 15 min cruise
        {'type': 'transition_back'},
        {'type': 'hover', 'duration_s': 60},
    ]

    # Analyze each preset
    for preset_name in manager.list_presets():
        output_dir = run_analysis_with_preset(preset_name, standard_mission)
        results[preset_name] = output_dir

    # Create comparison summary
    print("\n" + "="*80)
    print(" COMPARISON SUMMARY".center(80))
    print("="*80 + "\n")

    comparison_dir = "output/comparisons"
    os.makedirs(comparison_dir, exist_ok=True)

    comparison_file = os.path.join(comparison_dir, "preset_comparison.txt")
    import sys
    from io import StringIO

    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    manager.print_preset_comparison()
    comparison_text = mystdout.getvalue()
    sys.stdout = old_stdout

    with open(comparison_file, 'w') as f:
        f.write(comparison_text)

    print(comparison_text)
    print(f"✓ Comparison saved: {comparison_file}")

    print("\nOutput Directories:")
    print("-" * 80)
    for preset_name, output_dir in results.items():
        print(f"  • {preset_name:<35} → {output_dir}")

    print("\n" + "="*80 + "\n")

    return results


def quick_mission_feasibility_check():
    """
    Quick workflow to check if a mission is feasible for all presets.
    """
    print("\n" + "="*80)
    print(" MISSION FEASIBILITY CHECK".center(80))
    print("="*80 + "\n")

    # Define test mission
    test_mission = [
        {'type': 'hover', 'duration_s': 60},
        {'type': 'transition_forward'},
        {'type': 'cruise', 'duration_s': 1200, 'speed_ms': 15.0},  # 20 min cruise
        {'type': 'transition_back'},
        {'type': 'hover', 'duration_s': 300},  # 5 min hover survey
        {'type': 'transition_forward'},
        {'type': 'cruise', 'duration_s': 1200, 'speed_ms': 15.0},  # 20 min return
        {'type': 'transition_back'},
        {'type': 'hover', 'duration_s': 60},
    ]

    print("Mission Profile:")
    print("  1. Takeoff: 60s hover")
    print("  2. Transition to cruise")
    print("  3. Cruise to site: 20 min @ 15 m/s (18 km)")
    print("  4. Survey: 5 min hover")
    print("  5. Return cruise: 20 min @ 15 m/s (18 km)")
    print("  6. Landing: 60s hover")
    print(f"\n  Total Distance: 36 km")
    print("-" * 80)

    manager = PresetManager()
    feasibility = {}

    for preset_name in manager.list_presets():
        config = manager.get_preset(preset_name)
        calc = PerformanceCalculator(config)
        mission = calc.mission_profile_analysis(test_mission)

        feasible = mission['battery_remaining_percent'] >= 20
        feasibility[preset_name] = {
            'feasible': feasible,
            'total_time_min': mission['total_time_min'],
            'energy_used_wh': mission['total_energy_wh'],
            'battery_remaining_percent': mission['battery_remaining_percent'],
        }

        status = "✓ FEASIBLE" if feasible else "✗ NOT FEASIBLE"
        print(f"\n{preset_name}:")
        print(f"  Time:    {mission['total_time_min']:.1f} min")
        print(f"  Energy:  {mission['total_energy_wh']:.1f} Wh")
        print(f"  Reserve: {mission['battery_remaining_percent']:.1f}%")
        print(f"  Status:  {status}")

    print("\n" + "="*80)
    print("\nRecommendation:")

    feasible_presets = [name for name, data in feasibility.items() if data['feasible']]

    if feasible_presets:
        print(f"  ✓ Mission is feasible with: {', '.join(feasible_presets)}")
        best = max(feasibility.items(), key=lambda x: x[1]['battery_remaining_percent'])
        print(f"  ✓ Best choice: {best[0]} (Reserve: {best[1]['battery_remaining_percent']:.1f}%)")
    else:
        print(f"  ✗ Mission is NOT feasible with any preset")
        print(f"  → Reduce cruise time or add battery capacity")

    print("\n" + "="*80 + "\n")


def interactive_preset_selector():
    """
    Interactive menu for preset selection.
    """
    manager = PresetManager()

    print("\n" + "="*80)
    print(" VTOL ANALYZER v3.0 - INTERACTIVE PRESET SELECTOR".center(80))
    print("="*80 + "\n")

    print("Available Presets:")
    print("-" * 80)

    presets = manager.list_presets()
    for i, preset_name in enumerate(presets, 1):
        desc = manager.get_preset_description(preset_name)
        print(f"  [{i}] {desc}")

    print("  [4] Analyze all presets")
    print("  [5] Mission feasibility check")
    print("  [6] Exit")

    print("-" * 80)

    try:
        choice = input("\nSelect option (1-6): ").strip()

        if choice in ['1', '2', '3']:
            preset_name = presets[int(choice) - 1]
            run_analysis_with_preset(preset_name)
        elif choice == '4':
            analyze_all_presets()
        elif choice == '5':
            quick_mission_feasibility_check()
        elif choice == '6':
            print("\nExiting...\n")
            return
        else:
            print("\nInvalid choice!")

    except (ValueError, IndexError, KeyboardInterrupt):
        print("\nInvalid input or interrupted.\n")


if __name__ == "__main__":
    import sys

    print("\n" + "="*80)
    print(" VTOL ANALYZER v3.0 - PRODUCTION WORKFLOW".center(80))
    print("="*80 + "\n")

    if len(sys.argv) > 1:
        # Command line mode
        if sys.argv[1] == "--all":
            analyze_all_presets()
        elif sys.argv[1] == "--feasibility":
            quick_mission_feasibility_check()
        elif sys.argv[1] == "--preset" and len(sys.argv) > 2:
            run_analysis_with_preset(sys.argv[2])
        else:
            print("Usage:")
            print("  python3 production_workflow_example.py --all")
            print("  python3 production_workflow_example.py --feasibility")
            print("  python3 production_workflow_example.py --preset validated_6kg_tailsitter")
            print("  python3 production_workflow_example.py   (interactive mode)")
    else:
        # Interactive mode
        interactive_preset_selector()
