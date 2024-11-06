#src/params.py
import struct
from enum import Enum

class Params():

    # URLs for configuration files (not used!)
    config_url = 'https://nb1.joomtalk.ir/download/config.csv'  # URL for the configuration file
    swarm_url = 'https://nb1.joomtalk.ir/download/swarm.csv'  # URL for the swarm file

    # Simulation and Mode Switches
    sim_mode = True  # Set to True for simulation mode, False for real-life mode
    GIT_AUTO_PUSH = True
    GIT_REPO_URL = 'git@github.com:alireza787b/mavsdk_drone_show.git'
    
    # Conditional Configuration File Names
    if sim_mode:
        config_csv_name = "config_sitl.csv"
        swarm_csv_name = "swarm_sitl.csv"
        GIT_BRANCH = 'docker-sitl-2'  # Example branch for simulation mode
    else:
        config_csv_name = "config.csv"
        swarm_csv_name = "swarm.csv"
        GIT_BRANCH = 'real-test-1'  # Example branch for real-life mode
    

    enable_drones_http_server = True  # Enable HTTP server on drones
    single_drone = False  # Enable single drone mode
    offline_config = True  # Use offline configuration (not used!)
    offline_swarm = True  # Use offline swarm (not used!)
    default_sitl = True  # Use default 14550 port for single drone simulation
    online_sync_time = True  # Sync time from Internet Time Servers

    # Flask Server Configuration
    drones_flask_port = 7070  # Port for the drone's Flask server
    polling_interval = 1  # Polling interval in seconds
    get_drone_state_URI = 'get_drone_state'  # URI for getting drone state
    send_drone_command_URI = 'send_drone_command'  # URI for sending drone commands
    get_drone_home_URI = 'get-home-pos'
    flask_telem_socket_port = 5000  # Flask telemetry socket port
    
    get_position_deviation_URI = 'get-position-deviation'
    acceptable_deviation = 3.0  # Acceptable deviation in meters
    
    TELEMETRY_POLLING_TIMEOUT = 10  # Threshold in seconds to check for telemetry timeout
    HTTP_REQUEST_TIMEOUT = 5  # Timeout in seconds for HTTP request
    
    enable_default_subscriptions = True # all drones subscribe to each other and get contineous polling 
    
    # Environment mode
    env_mode = 'development'  # Change to 'production' for production mode

    # UDP Telemetry Configuration
    enable_udp_telemetry = False  # Enable/disable UDP telemetry
    TELEM_SEND_INTERVAL = 0.5  # Send telemetry data every TELEM_SEND_INTERVAL seconds
    local_mavlink_refresh_interval = 0.1  # Refresh interval for local Mavlink connection
    broadcast_mode = True  # Enable broadcast mode
    extra_swarm_telem = []  # Extra swarm telemetry IPs
    income_packet_check_interval = 0.1  # Interval for checking incoming packets

    # MAVLink Connection Configuration
    serial_mavlink = True  # Use serial connection for MAVLink
    serial_mavlink_port = '/dev/ttyS0'  # Serial port for Raspberry Pi Zero TTL
    serial_baudrate = 57600  # Serial connection baudrate
    sitl_port = 14550  # SITL port
    hw_udp_port = 14550
    gcs_mavlink_port = 34550  # Port for sending MAVLink messages to GCS
    mavsdk_port = 14540  # MAVSDK port
    local_mavlink_port = 12550  # Local MAVLink port
    local_mavlink2rest_port = 14569
    shared_gcs_port = True  # Shared GCS port
    #extra_devices = [f"127.0.0.1:{local_mavlink_port}", "100.84.110.118:14550", "100.84.21.128:14550", "100.84.20.178:14550"]  # Extra devices for MAVLink routing
    extra_devices = [f"127.0.0.1:{local_mavlink_port}" , f"127.0.0.1:{local_mavlink2rest_port}", "100.84.110.118:14550"]  # Extra devices for MAVLink routing

    hard_reboot_command_enabled = True  # Default to not rebooting the system , make sure have root priv
    force_reboot = True

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
    trigger_sooner_seconds = 4 # trigger mission a bit early to compensate for initialization

       
    max_takeoff_alt = 100
    default_takeoff_alt = 10
    

    
    
    # LED Configuration
    led_count = 25        # Number of LED pixels.
    led_pin = 10          # GPIO pin connected to the pixels.
    led_freq_hz = 800000  # LED signal frequency in hertz.
    led_dma = 10          # DMA channel to use for generating signal.
    led_brightness = 255  # Brightness of the LEDs.
    led_invert = False    # True to invert the signal.
    led_channel = 0       # GPIO channel.
    
    
    custom_csv_file_name = "active.csv" # Name of custom csv execution
    main_offboard_executer = "drone_show.py" #name of script that executes offboard missions from csv
    
    smart_swarm_executer = "smart_swarm.py"
    
    # Smart Swarm parameters
    CONTROL_LOOP_FREQUENCY = 10  # Hz
    LEADER_UPDATE_FREQUENCY = 3   # Hz
    DATA_FRESHNESS_THRESHOLD = 1.0  # seconds
    SWARM_FEEDFORWARD_VELOCITY_ENABLED = True
    
    
    MAX_LOG_FILES = 100
    
    
    


    # Fixed gRPC port for MAVSDK server
    DEFAULT_GRPC_PORT = 50040

    # Maximum number of retries for critical operations
    PREFLIGHT_MAX_RETRIES = 3

    # Timeout for pre-flight checks in seconds
    PRE_FLIGHT_TIMEOUT = 5

    # Timeout for landing detection during landing phase in seconds
    LANDING_TIMEOUT = 10  # Adjusted as per requirement

    # Altitude threshold to determine if trajectory ends high or at ground level
    GROUND_ALTITUDE_THRESHOLD = 1.0  # Configurable

    # Minimum altitude to start controlled landing in meters
    CONTROLLED_LANDING_ALTITUDE = 3.0  # Configurable

    # Minimum time before end of trajectory to start controlled landing in seconds
    CONTROLLED_LANDING_TIME = 2.0  #

    # Minimum mission progress percentage before considering controlled landing
    MISSION_PROGRESS_THRESHOLD = 0.5  # 50%

    # Descent speed during controlled landing in m/s
    CONTROLLED_DESCENT_SPEED = 0.5  # Configurable

    # Maximum time to wait during controlled landing before initiating PX4 native landing
    CONTROLLED_LANDING_TIMEOUT = 15  # Configurable

    # Enable initial position correction to account for GPS drift before takeoff
    ENABLE_INITIAL_POSITION_CORRECTION = True  # Set to False to disable this feature

    # Maximum number of log files to keep
    MAX_LOG_FILES = 100  # Keep the last 100 log files

    # Altitude threshold for initial climb phase in meters
    INITIAL_CLIMB_ALTITUDE_THRESHOLD = 3.0  # Configurable

    # Time threshold for initial climb phase in seconds
    INITIAL_CLIMB_TIME_THRESHOLD = 3.0  # Configurable

    # Set to False to disable feedforward velocity setpoints
    FEEDFORWARD_VELOCITY_ENABLED = False

    # Set to False to disable feedforward acceleration setpoints (if acceleration is true, velocity should be true as well, otherwise only position would be executed)
    # Since MAVSDK doesn't support position + acceleration yet
    FEEDFORWARD_ACCELERATION_ENABLED = False