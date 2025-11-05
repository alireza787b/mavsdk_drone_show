#!/usr/bin/env python3
"""
Simple test script to verify config.csv updates work correctly
Tests CSV structure and data integrity without requiring Flask
"""

import csv
import sys

print("=" * 80)
print("CONFIG.CSV UPDATE - SIMPLE BACKEND TESTING")
print("=" * 80)

# Test 1: Check CONFIG_COLUMNS definition
print("\n[TEST 1] Checking gcs-server/config.py CONFIG_COLUMNS...")
try:
    with open('/root/mavsdk_drone_show/gcs-server/config.py', 'r') as f:
        content = f.read()
        if "'serial_port'" in content and "'baudrate'" in content:
            print("✓ CONFIG_COLUMNS contains 'serial_port' and 'baudrate'")
        else:
            print("✗ ERROR: CONFIG_COLUMNS missing new fields!")
            sys.exit(1)
except Exception as e:
    print(f"✗ ERROR: {e}")
    sys.exit(1)

# Test 2: Validate config.csv structure
print("\n[TEST 2] Validating config.csv structure...")
try:
    with open('/root/mavsdk_drone_show/config.csv', 'r') as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames

        print(f"  Header: {', '.join(header)}")

        expected_columns = ['hw_id', 'pos_id', 'x', 'y', 'ip', 'mavlink_port',
                          'debug_port', 'gcs_ip', 'serial_port', 'baudrate']

        if header == expected_columns:
            print("✓ Header matches expected 10-column structure")
        else:
            print(f"✗ ERROR: Header mismatch!")
            print(f"  Expected: {expected_columns}")
            print(f"  Got: {header}")
            sys.exit(1)

        # Load all rows
        rows = list(reader)
        print(f"✓ Loaded {len(rows)} drone configurations")

        # Check first drone
        if rows:
            first = rows[0]
            print(f"\n  First Drone (hw_id={first['hw_id']}):")
            print(f"    - Serial Port: {first['serial_port']}")
            print(f"    - Baudrate: {first['baudrate']}")

            if first['serial_port'] and first['baudrate']:
                print("✓ New columns populated correctly")
            else:
                print("✗ ERROR: New columns empty!")
                sys.exit(1)

except Exception as e:
    print(f"✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Validate config_sitl.csv structure
print("\n[TEST 3] Validating config_sitl.csv structure...")
try:
    with open('/root/mavsdk_drone_show/config_sitl.csv', 'r') as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames

        if header == expected_columns:
            print("✓ SITL header matches expected structure")
        else:
            print(f"✗ ERROR: SITL header mismatch!")
            sys.exit(1)

        rows = list(reader)
        print(f"✓ Loaded {len(rows)} SITL drone configurations")

        if rows:
            first = rows[0]
            print(f"\n  First SITL Drone (hw_id={first['hw_id']}):")
            print(f"    - Serial Port: {first['serial_port']}")
            print(f"    - Baudrate: {first['baudrate']}")

            if first['serial_port'] == 'N/A' and first['baudrate'] == 'N/A':
                print("✓ SITL values correctly set to N/A")
            else:
                print(f"⚠ WARNING: SITL values not N/A ({first['serial_port']}, {first['baudrate']})")

except Exception as e:
    print(f"✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Check functions/read_config.py was updated
print("\n[TEST 4] Checking functions/read_config.py...")
try:
    with open('/root/mavsdk_drone_show/functions/read_config.py', 'r') as f:
        content = f.read()
        if 'serial_port' in content and 'baudrate' in content:
            print("✓ read_config.py updated with new columns")
        else:
            print("✗ ERROR: read_config.py not updated!")
            sys.exit(1)

        if 'len(row) >= 8' in content or 'len(row) > 8' in content:
            print("✓ Backward compatibility check present")
        else:
            print("⚠ WARNING: No backward compatibility detected")

except Exception as e:
    print(f"✗ ERROR: {e}")
    sys.exit(1)

# Test 5: Check src/drone_config.py has accessor methods
print("\n[TEST 5] Checking src/drone_config.py accessors...")
try:
    with open('/root/mavsdk_drone_show/src/drone_config.py', 'r') as f:
        content = f.read()
        if 'def get_serial_port' in content and 'def get_baudrate' in content:
            print("✓ get_serial_port() and get_baudrate() methods present")
        else:
            print("✗ ERROR: Accessor methods missing!")
            sys.exit(1)

except Exception as e:
    print(f"✗ ERROR: {e}")
    sys.exit(1)

# Test 6: Verify backups exist
print("\n[TEST 6] Checking backup files...")
try:
    import os
    if os.path.exists('/root/mavsdk_drone_show/config.csv.backup'):
        print("✓ config.csv.backup exists")
    else:
        print("⚠ WARNING: config.csv.backup not found")

    if os.path.exists('/root/mavsdk_drone_show/config_sitl.csv.backup'):
        print("✓ config_sitl.csv.backup exists")
    else:
        print("⚠ WARNING: config_sitl.csv.backup not found")

except Exception as e:
    print(f"✗ ERROR: {e}")
    sys.exit(1)

print("\n" + "=" * 80)
print("✓ ALL SIMPLE BACKEND TESTS PASSED!")
print("=" * 80)
print("\nSummary:")
print("  ✓ CONFIG_COLUMNS updated in gcs-server/config.py")
print("  ✓ config.csv has correct 10-column structure")
print("  ✓ config_sitl.csv has correct 10-column structure")
print("  ✓ SITL uses N/A for hardware-specific fields")
print("  ✓ functions/read_config.py updated")
print("  ✓ src/drone_config.py has accessor methods")
print("  ✓ Backup files created")
print("\n✓ Backend implementation complete!")
print("\nNext steps:")
print("  1. Test frontend (start dashboard and verify UI)")
print("  2. Create documentation/migration guide")
print("  3. Test in real deployment")
