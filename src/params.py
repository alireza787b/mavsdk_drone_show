import struct
from enum import Enum

class Params():

    # URLs for configuration files
    config_url = 'https://nb1.joomtalk.ir/download/config.csv'  # URL for the configuration file
    swarm_url = 'https://nb1.joomtalk.ir/download/swarm.csv'  # URL for the swarm file

    # Simulation and Mode Switches
    sim_mode = False  # Set to True for simulation mode, False for real-life mode
    enable_drones_http_server = True  # Enable HTTP server on drones
    single_drone = False  # Enable single drone mode
    offline_config = True  # Use offline configuration
    offline_swarm = True  # Use offline swarm
    default_sitl = True  # Use default 14550 port for single drone simulation
    online_sync_time = False  # Sync time from Internet Time Servers

    # Flask Server Configuration
    drones_flask_port = 7070  # Port for the drone's Flask server
    polling_interval = 1  # Polling interval in seconds
    get_drone_state_URI = 'get_drone_state'  # URI for getting drone state
    send_drone_command_URI = 'send_drone_command'  # URI for sending drone commands
    flask_telem_socket_port = 5000  # Flask telemetry socket port
    
    TELEMETRY_POLLING_TIMEOUT = 10  # Threshold in seconds to check for telemetry timeout
    HTTP_REQUEST_TIMEOUT = 5  # Timeout in seconds for HTTP request
    
    # Environment mode
    env_mode = 'development'  # Change to 'production' for production mode

    # UDP Telemetry Configuration
    enable_udp_telemetry = False  # Enable/disable UDP telemetry
    TELEM_SEND_INTERVAL = 0.5  # Send telemetry data every TELEM_SEND_INTERVAL seconds
    local_mavlink_refresh_interval = 0.1  # Refresh interval for local Mavlink connection
    broadcast_mode = False  # Enable broadcast mode
    extra_swarm_telem = []  # Extra swarm telemetry IPs
    income_packet_check_interval = 0.1  # Interval for checking incoming packets

    # MAVLink Connection Configuration
    serial_mavlink = True  # Use serial connection for MAVLink
    serial_mavlink_port = '/dev/ttyS0'  # Serial port for Raspberry Pi Zero TTL
    serial_baudrate = 57600  # Serial connection baudrate
    sitl_port = 14550  # SITL port
    gcs_mavlink_port = 34550  # Port for sending MAVLink messages to GCS
    mavsdk_port = 14540  # MAVSDK port
    local_mavlink_port = 12550  # Local MAVLink port
    shared_gcs_port = True  # Shared GCS port
    extra_devices = [f"127.0.0.1:{local_mavlink_port}", "100.84.110.118:14550", "100.84.21.128:14550", "100.84.20.178:14550"]  # Extra devices for MAVLink routing

    # Packet Formats and Sizes
    telem_struct_fmt = '>BHHBBIddddddddBIB'  # Telemetry packet format
    command_struct_fmt = '>B B B B B I B'  # Command packet format
    telem_packet_size = struct.calcsize(telem_struct_fmt)  # Size of telemetry packet
    command_packet_size = struct.calcsize(command_struct_fmt)  # Size of command packet

    # GRPC Configuration
    default_GRPC_port = 50051  # Default GRPC port

    # Offboard Control Configuration
    offboard_follow_update_interval = 0.1  # Offboard follow update interval
    schedule_mission_frequency = 2  # Frequency for scheduling missions
    follow_setpoint_frequency = 4  # Frequency for follow setpoints

    # Sleep Interval for Main Loop
    sleep_interval = 0.1  # Sleep interval for the main loop in seconds

    # Mission Types
    class Mission(Enum):
        NONE = 0
        DRONE_SHOW_FROM_CSV = 1
        SMART_SWARM = 2
        TAKE_OFF = 10
        LAND = 101
        HOLD = 102
        TEST = 100
