# src/params.py

import os
import struct
from enum import Enum

class Params:
    """
    Params class manages configuration settings for the drone system,
    determining whether to operate in simulation (SITL) mode or real-life mode
    based on the presence of the 'real.mode' file.

    This class contains class variables that can be accessed throughout the code
    without instantiation. The variables are initialized at module load time,
    and depend on the operational mode.

    Attributes:
        sim_mode (bool): Indicates if the system is in simulation mode.
        config_csv_name (str): Filename for the configuration CSV.
        swarm_csv_name (str): Filename for the swarm CSV.
        GIT_BRANCH (str): Git branch name used for synchronization.
        (Other attributes as per project requirements.)
    """

    # Path to the 'real.mode' file relative to the current directory
    real_mode_file = 'real.mode'

    # Determine simulation mode based on the existence of 'real.mode'
    # If 'real.mode' exists, sim_mode is False (real-life mode)
    sim_mode = not os.path.exists(real_mode_file)

    # Debug: Print the current mode
    print(f"[DEBUG] Simulation Mode: {sim_mode}")

    # URLs for configuration files (not used in current implementation)
    config_url = 'https://nb1.joomtalk.ir/download/config.csv'  # URL for the configuration file
    swarm_url = 'https://nb1.joomtalk.ir/download/swarm.csv'    # URL for the swarm file

    # Git Configuration
    GIT_AUTO_PUSH = True
    GIT_REPO_URL = 'git@github.com:alireza787b/mavsdk_drone_show.git'
    GIT_BRANCH = 'main-candidate'  # Git branch is 'main-candidate' for both modes

    # Conditional Configuration File Names based on sim_mode
    if sim_mode:
        config_csv_name = "config_sitl.csv"
        swarm_csv_name = "swarm_sitl.csv"
    else:
        config_csv_name = "config.csv"
        swarm_csv_name = "swarm.csv"

    # Debug: Print the selected configuration files
    print(f"[DEBUG] Configuration CSV: {config_csv_name}")
    print(f"[DEBUG] Swarm CSV: {swarm_csv_name}")

    # General Settings
    enable_drones_http_server = True  # Enable HTTP server on drones
    single_drone = False              # Enable single drone mode
    offline_config = True             # Use offline configuration (not used!)
    offline_swarm = True              # Use offline swarm (not used!)
    default_sitl = True               # Use default 14550 port for single drone simulation
    online_sync_time = True           # Sync time from Internet Time Servers

    # Flask Server Configuration
    drones_flask_port = 7070                # Port for the drone's Flask server
    polling_interval = 1                    # Polling interval in seconds
    get_drone_state_URI = 'get_drone_state' # URI for getting drone state
    send_drone_command_URI = 'send_drone_command'  # URI for sending drone commands
    get_drone_home_URI = 'get-home-pos'     # URI for getting drone home position
    flask_telem_socket_port = 5000          # Flask telemetry socket port

    get_position_deviation_URI = 'get-position-deviation'
    acceptable_deviation = 3.0              # Acceptable deviation in meters

    TELEMETRY_POLLING_TIMEOUT = 10  # Threshold in seconds to check for telemetry timeout
    HTTP_REQUEST_TIMEOUT = 5        # Timeout in seconds for HTTP requests

    enable_default_subscriptions = True  # All drones subscribe to each other for continuous polling

    # Environment Mode
    env_mode = 'development'  # Change to 'production' for production mode

    # UDP Telemetry Configuration
    enable_udp_telemetry = False         # Enable/disable UDP telemetry
    TELEM_SEND_INTERVAL = 0.5            # Send telemetry data every TELEM_SEND_INTERVAL seconds
    local_mavlink_refresh_interval = 0.1 # Refresh interval for local MAVLink connection
    broadcast_mode = True                # Enable broadcast mode
    extra_swarm_telem = []               # Extra swarm telemetry IPs
    income_packet_check_interval = 0.1   # Interval for checking incoming packets

    # MAVLink Connection Configuration
    serial_mavlink = True              # Use serial connection for MAVLink
    serial_mavlink_port = '/dev/ttyS0' # Serial port for Raspberry Pi Zero TTL
    serial_baudrate = 57600            # Serial connection baudrate
    sitl_port = 14550                  # SITL port
    hw_udp_port = 14550
    gcs_mavlink_port = 34550           # Port for sending MAVLink messages to GCS
    mavsdk_port = 14540                # MAVSDK port
    local_mavlink_port = 12550         # Local MAVLink port
    local_mavlink2rest_port = 14569
    shared_gcs_port = True             # Shared GCS port
    extra_devices = [
        f"127.0.0.1:{local_mavlink_port}",
        f"127.0.0.1:{local_mavlink2rest_port}",
        "100.93.169.180:14550"
    ]  # Extra devices for MAVLink routing

    hard_reboot_command_enabled = True  # Allow hard reboot commands (ensure root privileges)
    force_reboot = True

    schedule_mission_frequency = 2  # Frequency for scheduling missions

    # Sleep Interval for Main Loop
    sleep_interval = 0.1           # Sleep interval for the main loop in seconds
    trigger_sooner_seconds = 4     # Trigger mission a bit early to compensate for initialization

    max_takeoff_alt = 100          # Maximum allowable takeoff altitude
    default_takeoff_alt = 10       # Default takeoff altitude

    # LED Configuration
    led_count = 25        # Number of LED pixels
    led_pin = 10          # GPIO pin connected to the pixels
    led_freq_hz = 800000  # LED signal frequency in hertz
    led_dma = 10          # DMA channel to use for generating signal
    led_brightness = 255  # Brightness of the LEDs
    led_invert = False    # True to invert the signal
    led_channel = 0       # GPIO channel

    custom_csv_file_name = "active.csv"         # Name of custom CSV execution
    main_offboard_executer = "drone_show.py"    # Name of script that executes offboard missions from CSV
    smart_swarm_executer = "smart_swarm.py"     # Name of the smart swarm executor script

    # Smart Swarm Parameters
    CONTROL_LOOP_FREQUENCY = 10       # Control loop frequency in Hz
    LEADER_UPDATE_FREQUENCY = 3       # Leader update frequency in Hz
    DATA_FRESHNESS_THRESHOLD = 3.0    # Data freshness threshold in seconds
    SWARM_FEEDFORWARD_VELOCITY_ENABLED = False

    ENABLE_KALMAN_FILTER = False  # Set to False to disable Kalman filter

    # Logging Configuration
    MAX_LOG_FILES = 100  # Maximum number of log files to keep

    # Fixed gRPC Port for MAVSDK Server
    DEFAULT_GRPC_PORT = 50040

    # Critical Operation Settings
    PREFLIGHT_MAX_RETRIES = 3       # Maximum number of retries for pre-flight checks
    PRE_FLIGHT_TIMEOUT = 5          # Timeout for pre-flight checks in seconds
    LANDING_TIMEOUT = 10            # Timeout during landing phase in seconds

    # Trajectory and Landing Configuration
    GROUND_ALTITUDE_THRESHOLD = 1.0        # Threshold to determine if trajectory ends at ground level
    CONTROLLED_LANDING_ALTITUDE = 3.0      # Minimum altitude to start controlled landing
    CONTROLLED_LANDING_TIME = 2.0          # Minimum time before end of trajectory to start controlled landing
    MISSION_PROGRESS_THRESHOLD = 0.5       # Minimum mission progress percentage for controlled landing
    CONTROLLED_DESCENT_SPEED = 0.5         # Descent speed during controlled landing in m/s
    CONTROLLED_LANDING_TIMEOUT = 15        # Maximum time to wait during controlled landing

    # Initial Position Correction
    ENABLE_INITIAL_POSITION_CORRECTION = True  # Enable initial position correction to account for GPS drift

    # Initial Climb Phase Settings
    INITIAL_CLIMB_ALTITUDE_THRESHOLD = 3.0  # Altitude threshold for initial climb phase
    INITIAL_CLIMB_TIME_THRESHOLD = 3.0      # Time threshold for initial climb phase

    # Feedforward Control Settings
    FEEDFORWARD_VELOCITY_ENABLED = True        # Enable feedforward velocity setpoints
    FEEDFORWARD_ACCELERATION_ENABLED = False   # Enable feedforward acceleration setpoints

    # PD Controller Gains
    PD_KP = 0.5            # Proportional gain
    PD_KD = 0.1            # Derivative gain
    MAX_VELOCITY = 3.0     # Maximum velocity in m/s

    # Low-Pass Filter Parameter
    LOW_PASS_FILTER_ALPHA = 0.2  # Smoothing factor between 0 and 1

    @classmethod
    def get_trajectory_files(cls, position_id, custom_csv):
        """
        Returns the paths to the trajectory files based on the current mode.

        Args:
            position_id (int): The identifier for the drone's position.
            custom_csv (str): The filename for the custom trajectory CSV.

        Returns:
            tuple: (drone_show_trajectory_filename, custom_show_trajectory_filename)
        """
        if cls.sim_mode:
            drone_show_trajectory_filename = os.path.join(
                'shapes_sitl', 'swarm', 'processed', f"Drone {position_id}.csv"
            )
            custom_show_trajectory_filename = os.path.join(
                'shapes_sitl', custom_csv
            )
        else:
            drone_show_trajectory_filename = os.path.join(
                'shapes', 'swarm', 'processed', f"Drone {position_id}.csv"
            )
            custom_show_trajectory_filename = os.path.join(
                'shapes', custom_csv
            )

        # Debug: Print the selected trajectory files
        print(f"[DEBUG] Drone Trajectory File: {drone_show_trajectory_filename}")
        print(f"[DEBUG] Custom Trajectory File: {custom_show_trajectory_filename}")

        return (drone_show_trajectory_filename, custom_show_trajectory_filename)
