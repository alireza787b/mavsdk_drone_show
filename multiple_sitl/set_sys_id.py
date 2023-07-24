import os

# Directory where the .hwID files are
hwid_dir = '~/mavsdk_drone_show'

# The rcS file path
rcs_file_path = '~/PX4-Autopilot/build/px4_sitl_default/etc/init.d-posix/rcS'

# Expand the rcS file path
rcs_file_path = os.path.expanduser(rcs_file_path)

# Find the .hwID file
hwid_file = next((f for f in os.listdir(hwid_dir) if f.endswith('.hwID')), None)

# If the .hwID file is not found, throw an error
if not hwid_file:
    raise FileNotFoundError('.hwID file not found')

# Read the hwID from the file
with open(os.path.join(hwid_dir, hwid_file), 'r') as f:
    hwid = f.read().strip()

print(f"Found .hwID file with ID: {hwid}")

# Read the rcS file
with open(rcs_file_path, 'r') as f:
    rcs_content = f.readlines()

# Find the line where MAV_SYS_ID is set
index = next(i for i, line in enumerate(rcs_content) if 'param set MAV_SYS_ID' in line)

# Check if the line 'param set MAV_SYS_ID hwID' already exists
if any(f'param set MAV_SYS_ID {hwid}' in line for line in rcs_content):
    print(f"param set MAV_SYS_ID {hwid} is already in the file.")
else:
    print(f"Adding line: param set MAV_SYS_ID {hwid}")
    # Add a new line after the found line
    rcs_content.insert(index + 1, f'param set MAV_SYS_ID {hwid}\n')

    # Write the rcS file back
    with open(rcs_file_path, 'w') as f:
        f.writelines(rcs_content)
