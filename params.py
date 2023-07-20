# config.py

"""
Drone configuration and settings module.

Contains all the global configuration and constants required for the drone program.
Settings are grouped logically and documented.

To access any setting, simply import config and access it directly:

from config import config
print(config.sitl_port)

"""

import struct


class Params():

    # Configuration Variables
    # URLs
    config_url = 'https://alumsharif.org/download/config.csv'  # URL for the configuration file
    swarm_url = 'https://alumsharif.org/download/swarm.csv'  # URL for the swarm file

    # Simulation mode switch
    sim_mode = False  # Set to True for simulation mode, False for real-life mode

    # Mavlink Connection
    serial_mavlink = False  # Set to True if Raspberry Pi is connected to Pixhawk using serial, False for UDP
    serial_mavlink_port = '/dev/ttyAMA0'  # Default serial port for Raspberry Pi Zero
    serial_baudrate = 57600  # Default baudrate
    sitl_port = 14550  # Default SITL port
    gcs_mavlink_port = 14550  # Port to send Mavlink messages to GCS
    mavsdk_port = 14540  # Default MAVSDK port
    local_mavlink_port = 12550  # Local Mavlink port
    shared_gcs_port = True
    extra_devices = [f"127.0.0.1:{local_mavlink_port}"]  # List of extra devices (IP:Port) to route Mavlink

    # Sleep interval for the main loop in seconds
    sleep_interval = 0.1

    # Offline configuration switch
    offline_config = True  # Set to True to use offline configuration
    offline_swarm = True  # Set to True to use offline swarm

    # Default SITL port for single drone simulation
    default_sitl = True  # Set to True to use default 14550 port for single drone simulation

    # Online time synchronization switch
    online_sync_time = False  # Set to True to sync time from Internet Time Servers

    # Telemetry and Communication
    TELEM_SEND_INTERVAL = 1  # Send telemetry data every TELEM_SEND_INTERVAL seconds
    local_mavlink_refresh_interval = 0.1  # Refresh interval for local Mavlink connection
    broadcast_mode = True  # Set to True for broadcast mode, False for unicast mode

    # Packet formats
    telem_struct_fmt = '=BHHBBIddddddddBB'  # Telemetry packet format
    command_struct_fmt = '=B B B B B I B'  # Command packet format

    # Packet sizes
    telem_packet_size = struct.calcsize(telem_struct_fmt)  # Size of telemetry packet
    command_packet_size = struct.calcsize(command_struct_fmt)  # Size of command packet

    # Interval for checking incoming packets
    income_packet_check_interval = 0.5

    # Default GRPC port
    default_GRPC_port = 50051

    # Offboard follow update interval
    offboard_follow_update_interval = 0.2


