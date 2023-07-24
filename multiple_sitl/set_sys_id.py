import os
import re

# Directory where the .hwID files are
hwid_dir = os.path.expanduser('~/mavsdk_drone_show')

# The rcS file path
rcs_file_path = os.path.expanduser('~/PX4-Autopilot/build/px4_sitl_default/etc/init.d-posix/rcS')

# Find the .hwID file
hwid_file = next((f for f in os.listdir(hwid_dir) if f.endswith('.hwID')), None)

# If the .hwID file is not found, throw an error
if not hwid_file:
    raise FileNotFoundError('.hwID file not found')

# Extract the hwid from the file name
hwid = hwid_file.split('.')[0]

print(f"Found .hwID file with ID: {hwid}")

# Read the rcS file
with open(rcs_file_path, 'r') as f:
    rcs_content = f.readlines()

# Find any existing MAV_SYS_ID line(s) and remove them if not equal to the correct hwid
rcs_content = [line for line in rcs_content if not (re.match('param set MAV_SYS_ID \d+', line) and not line.strip().endswith(hwid))]

# Check if the correct line already exists
if any(f'param set MAV_SYS_ID {hwid}' in line for line in rcs_content):
    print(f"param set MAV_SYS_ID {hwid} is already in the file.")
else:
    print(f"Adding line: param set MAV_SYS_ID {hwid}")
    # Add the correct line at the end of the file
    rcs_content.append(f'param set MAV_SYS_ID {hwid}\n')

# Write the rcS file back
with open(rcs_file_path, 'w') as f:
    f.writelines(rcs_content)
