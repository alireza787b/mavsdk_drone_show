import csv

# NOTE: This file appears to be legacy/unused code (no Drone class exists, no imports found)
# Updated to new 8-column format: hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate

def read_config(filename):
    """
    Reads drone configuration from CSV file.
    Expected format: hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate
    """
    dronesConfig = []

    with open(filename, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip the header
        for row in reader:
            if len(row) == 8:
                hw_id = row[0]
                pos_id = row[1]
                x = float(row[2])
                y = float(row[3])
                ip = row[4]
                mavlink_port = row[5]
                serial_port = row[6]
                baudrate = row[7]

                # Return dict format
                drone = {
                    'hw_id': hw_id,
                    'pos_id': pos_id,
                    'x': x,
                    'y': y,
                    'ip': ip,
                    'mavlink_port': mavlink_port,
                    'serial_port': serial_port,
                    'baudrate': baudrate
                }
                dronesConfig.append(drone)

    return dronesConfig