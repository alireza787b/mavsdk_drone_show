import csv

# NOTE: This file appears to be legacy/unused code (no Drone class exists, no imports found)
# Keeping for backward compatibility but updated to support new CSV format with serial_port and baudrate

def read_config(filename):
    dronesConfig = []

    with open(filename, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip the header
        for row in reader:
            # Support both old (8 columns) and new (10 columns) format
            if len(row) >= 8:
                hw_id = row[0]
                pos_id = row[1]
                x = float(row[2])
                y = float(row[3])
                ip = row[4]
                mavlink_port = row[5]
                debug_port = row[6]
                gcs_ip = row[7]
                serial_port = row[8] if len(row) > 8 else '/dev/ttyS0'  # Default for RP4
                baudrate = row[9] if len(row) > 9 else '57600'  # Default baudrate

                # Return dict instead of Drone object (Drone class doesn't exist)
                drone = {
                    'hw_id': hw_id,
                    'pos_id': pos_id,
                    'x': x,
                    'y': y,
                    'ip': ip,
                    'mavlink_port': mavlink_port,
                    'debug_port': debug_port,
                    'gcs_ip': gcs_ip,
                    'serial_port': serial_port,
                    'baudrate': baudrate
                }
                dronesConfig.append(drone)

    return dronesConfig