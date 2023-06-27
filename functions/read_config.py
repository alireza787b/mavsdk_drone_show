import csv


def read_config(filename):
    dronesConfig = []

    with open(filename, newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip the header
        for row in reader:
            hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip = row
            drone = Drone(hw_id, pos_id, float(x), float(y), ip, mavlink_port, debug_port, gcs_ip)
            dronesConfig.append(drone)

    return dronesConfig