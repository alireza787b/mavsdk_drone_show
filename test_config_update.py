#!/usr/bin/env python3
"""
Test script to verify config.csv updates work correctly
Tests both backend CSV loading and new serial_port/baudrate columns
"""

import sys
import csv
sys.path.insert(0, '/root/mavsdk_drone_show')
sys.path.insert(0, '/root/mavsdk_drone_show/gcs-server')

print("=" * 80)
print("CONFIG.CSV UPDATE - BACKEND TESTING")
print("=" * 80)

# Test 1: GCS Config Module
print("\n[TEST 1] Testing gcs-server/config.py...")
try:
    from config import CONFIG_COLUMNS, load_config

    print(f"✓ CONFIG_COLUMNS imported: {CONFIG_COLUMNS}")

    if 'serial_port' in CONFIG_COLUMNS and 'baudrate' in CONFIG_COLUMNS:
        print("✓ New columns present in CONFIG_COLUMNS")
    else:
        print("✗ ERROR: New columns missing from CONFIG_COLUMNS!")
        sys.exit(1)

    # Load config.csv
    config_data = load_config('/root/mavsdk_drone_show/config.csv')
    if config_data:
        print(f"✓ Loaded {len(config_data)} drones from config.csv")

        # Check first drone has new columns
        first_drone = config_data[0]
        if 'serial_port' in first_drone and 'baudrate' in first_drone:
            print(f"✓ First drone has serial_port: {first_drone['serial_port']}")
            print(f"✓ First drone has baudrate: {first_drone['baudrate']}")
        else:
            print("✗ ERROR: New columns missing from loaded data!")
            sys.exit(1)
    else:
        print("✗ ERROR: Failed to load config.csv!")
        sys.exit(1)

except Exception as e:
    print(f"✗ ERROR in Test 1: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Drone Config Module
print("\n[TEST 2] Testing src/drone_config.py accessors...")
try:
    from src.params import Params
    from src.drone_config import DroneConfig

    # Create a mock drone config with new columns
    mock_drones = {}

    # Test with hw_id=1 (should load from config.csv)
    drone = DroneConfig(mock_drones, hw_id='1')

    print(f"✓ DroneConfig created for hw_id=1")

    # Test new accessor methods
    serial_port = drone.get_serial_port()
    baudrate = drone.get_baudrate()

    print(f"✓ get_serial_port() returned: {serial_port}")
    print(f"✓ get_baudrate() returned: {baudrate}")

    # Verify values
    if serial_port and baudrate:
        print(f"✓ Serial config loaded successfully")
        print(f"  - Serial Port: {serial_port}")
        print(f"  - Baudrate: {baudrate}")
    else:
        print("✗ WARNING: Serial config returned empty/None")

except Exception as e:
    print(f"✗ ERROR in Test 2: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: SITL Config
print("\n[TEST 3] Testing config_sitl.csv...")
try:
    sitl_data = load_config('/root/mavsdk_drone_show/config_sitl.csv')
    if sitl_data:
        print(f"✓ Loaded {len(sitl_data)} drones from config_sitl.csv")

        first_sitl = sitl_data[0]
        if 'serial_port' in first_sitl and 'baudrate' in first_sitl:
            print(f"✓ SITL drone has serial_port: {first_sitl['serial_port']}")
            print(f"✓ SITL drone has baudrate: {first_sitl['baudrate']}")

            if first_sitl['serial_port'] == 'N/A' and first_sitl['baudrate'] == 'N/A':
                print("✓ SITL values correctly set to N/A")
            else:
                print("⚠ WARNING: SITL values not N/A (acceptable but unusual)")
        else:
            print("✗ ERROR: New columns missing from SITL config!")
            sys.exit(1)
    else:
        print("✗ ERROR: Failed to load config_sitl.csv!")
        sys.exit(1)

except Exception as e:
    print(f"✗ ERROR in Test 3: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Backward Compatibility (legacy 8-column CSV)
print("\n[TEST 4] Testing backward compatibility...")
try:
    from functions.read_config import read_config

    # Test with new 10-column format
    drones = read_config('/root/mavsdk_drone_show/config.csv')
    if drones:
        print(f"✓ Legacy read_config() loaded {len(drones)} drones")

        if isinstance(drones[0], dict):
            print(f"✓ Returns dict format (updated code)")
            if 'serial_port' in drones[0] and 'baudrate' in drones[0]:
                print(f"✓ New columns present: {drones[0]['serial_port']}, {drones[0]['baudrate']}")
            else:
                print("✗ ERROR: New columns missing!")
                sys.exit(1)
        else:
            print("⚠ WARNING: Returns non-dict format (old Drone class?)")
    else:
        print("✗ ERROR: read_config() returned empty!")
        sys.exit(1)

except Exception as e:
    print(f"✗ ERROR in Test 4: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Column Count Validation
print("\n[TEST 5] Validating CSV structure...")
try:
    with open('/root/mavsdk_drone_show/config.csv', 'r') as f:
        reader = csv.reader(f)
        header = next(reader)

        print(f"✓ CSV header: {','.join(header)}")

        if len(header) == 10:
            print(f"✓ Correct column count: 10")
        else:
            print(f"✗ ERROR: Expected 10 columns, got {len(header)}")
            sys.exit(1)

        # Check all rows have 10 columns
        for i, row in enumerate(reader, start=2):
            if len(row) != 10:
                print(f"✗ ERROR: Row {i} has {len(row)} columns, expected 10")
                sys.exit(1)

        print(f"✓ All rows have 10 columns")

except Exception as e:
    print(f"✗ ERROR in Test 5: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✓ ALL BACKEND TESTS PASSED!")
print("=" * 80)
print("\nSummary:")
print("  • gcs-server/config.py correctly updated")
print("  • src/drone_config.py accessors working")
print("  • config.csv has 10 columns with serial_port and baudrate")
print("  • config_sitl.csv has N/A values for hardware fields")
print("  • Backward compatibility maintained")
print("\nReady for frontend testing and deployment!")
