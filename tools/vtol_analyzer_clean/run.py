#!/usr/bin/env python3
"""
VTOL Performance Analyzer - Main Entry Point
Launch the GUI application or run command-line analysis
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='VTOL Performance Analyzer v4.1.2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s                    Launch GUI application
  %(prog)s --cli              Run command-line analysis
  %(prog)s --example          Run example analysis
  %(prog)s --test             Run test suite

For detailed documentation, see docs/USER_GUIDE.md
        '''
    )

    parser.add_argument('--cli', action='store_true',
                       help='Run command-line analysis instead of GUI')
    parser.add_argument('--example', action='store_true',
                       help='Run example analysis')
    parser.add_argument('--test', action='store_true',
                       help='Run test suite')
    parser.add_argument('--version', action='version',
                       version='VTOL Analyzer v4.1.2')

    args = parser.parse_args()

    if args.test:
        print("Running test suite...")
        from tests.test_all import run_all_tests
        return run_all_tests()

    elif args.example:
        print("Running example analysis...")
        from examples.basic_analysis import main as example_main
        return example_main()

    elif args.cli:
        print("Running command-line analysis...")
        from analyzer import AircraftConfiguration, PerformanceCalculator

        # Quick analysis
        config = AircraftConfiguration()
        calc = PerformanceCalculator(config)
        results = calc.generate_performance_summary()

        print("\n=== VTOL Performance Analysis ===")
        print(f"Cruise Speed:     {results['speeds']['cruise_ms']:.1f} m/s ({results['speeds']['cruise_kmh']:.1f} km/h)")
        print(f"Stall Speed:      {results['speeds']['stall_ms']:.1f} m/s ({results['speeds']['stall_kmh']:.1f} km/h)")
        print(f"Hover Endurance:  {results['hover']['endurance_min']:.1f} min")
        print(f"Cruise Endurance: {results['cruise']['endurance_min']:.1f} min")
        print(f"Max Range:        {results['cruise']['range_km']:.1f} km")
        print(f"Max L/D:          {results['aerodynamics']['max_ld_ratio']:.1f}")
        print("\n✓ Analysis complete. Use --example for detailed analysis.")
        return 0

    else:
        # Launch GUI (default)
        print("Launching VTOL Analyzer GUI...")
        from gui import VTOLAnalyzerGUI

        try:
            app = VTOLAnalyzerGUI()
            app.mainloop()
            return 0
        except Exception as e:
            print(f"Error launching GUI: {e}")
            print("\nTry running with --cli for command-line mode")
            return 1


if __name__ == "__main__":
    sys.exit(main())
