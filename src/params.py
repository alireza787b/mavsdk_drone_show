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
    config_url = 'https://nb1.joomtalk.ir/download/config.csv'  # Ugit addRL for the configuration file
    swarm_url = 'https://nb1.joomtalk.ir/download/swarm.csv'    # URL for the swarm file

    # Git Configuration
    # ===================================================================================
    # REPOSITORY CONFIGURATION: Environment Variable Support (MDS v3.1+)
    # ===================================================================================
    # These settings now support environment variable override for advanced deployments
    # while maintaining 100% backward compatibility for normal users.
    #
    # FOR NORMAL USERS (99%):
    #   - No action required - defaults work identically to previous versions
    #   - Uses: git@github.com:alireza787b/mavsdk_drone_show.git@main-candidate
    #
    # FOR ADVANCED USERS (Custom Forks):
    #   - Set environment variables before running any MDS scripts:
    #     export MDS_REPO_URL="git@github.com:yourcompany/your-fork.git"
    #     export MDS_BRANCH="your-production-branch"
    #   - All Python components (GCS server, functions, etc.) automatically use your config
    #
    # ENVIRONMENT VARIABLES:
    #   MDS_REPO_URL  - Git repository URL (SSH or HTTPS)
    #   MDS_BRANCH    - Git branch name
    # ===================================================================================
    GIT_AUTO_PUSH = True
    GIT_REPO_URL = os.environ.get('MDS_REPO_URL', 'git@github.com:the-mak-00/mavsdk_drone_show.git')
    GIT_BRANCH = os.environ.get('MDS_BRANCH', 'main')
    
    connectivity_check_ip = "8.8.8.8"  # Default IP to ping eg. 8.8.8.8 for the gcs IP
    connectivity_check_port = 5000        # Default port to ping eg. 80 for the gcs backend port
    connectivity_check_interval = 10    # Interval in seconds between connectivity checks

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
    MAX_STALE_DURATION = 10           # Max time delay follower would still use the leader data
    
    reboot_after_params = True
    

    # how many failed polls before we elect
    MAX_LEADER_UNREACHABLE_ATTEMPTS = 15

    # minimum seconds between successive elections
    LEADER_ELECTION_COOLDOWN = 30

    
    csv_dt = 0.05                     # default step time of the processed CSV file to generate (s)



    # Flask Server Configuration
    drones_flask_port = 7070                # Port for the drone's Flask server
    polling_interval = 1                    # Polling interval in seconds
    get_drone_state_URI = 'get_drone_state' # URI for getting drone state
    send_drone_command_URI = 'api/send-command'  # Replace with actual URI

    # Professional Logging & Status Reporting Configuration (Ultra-Quiet Mode)
    TELEMETRY_REPORT_INTERVAL = 120         # Report telemetry summary every 2 minutes (was 30s)
    GIT_STATUS_REPORT_INTERVAL = 300        # Report git status summary every 5 minutes (was 60s)
    STATUS_DASHBOARD_INTERVAL = 30          # Update status dashboard every 30 seconds (was 10s)
    POLLING_QUIET_MODE = True               # Suppress routine polling success messages
    ERROR_REPORT_THROTTLE = 20              # Report recurring errors every N occurrences (was 10)
    HEALTH_CHECK_INTERVAL = 600             # Overall system health check every 10 minutes (was 5m)

    # Ultra-Quiet Mode Settings
    ULTRA_QUIET_MODE = True                 # Enable ultra-quiet mode for production
    SUPPRESS_RECOVERY_MESSAGES = True       # Don't log every recovery event
    MIN_ERROR_THRESHOLD = 5                 # Minimum errors before logging starts

    # API Request Logging Optimization
    LOG_ROUTINE_API_CALLS = False           # Don't log routine API calls (telemetry, ping)
    API_ERROR_LOG_THRESHOLD = 400           # Only log API responses >= this status code
    LOG_SUCCESSFUL_COMMANDS = True          # Still log successful command completions

    get_drone_home_URI = 'get-home-pos'     # URI for getting drone home position
    get_drone_gps_origin_URI = 'get-gps-global-origin'  # URI for getting drone GPS global origin position
    flask_telem_socket_port = 5000          # Flask telemetry socket port

    get_position_deviation_URI = 'get-position-deviation'
    acceptable_deviation = 3.0              # Acceptable deviation in meters

    TELEMETRY_POLLING_TIMEOUT = 10  # Threshold in seconds to check for telemetry timeout
    HTTP_REQUEST_TIMEOUT = 5        # Timeout in seconds for HTTP requests

    enable_default_subscriptions = True  # All drones subscribe to each other for continuous polling
    
    enable_connectivity_check  = True # Enable Connectivity check Thread to ping GCS

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
        "192.168.145.101:14550", # GCS PC
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
    hover_test_csv_file_name = "hover_test.csv" # Name of hover test CSV execution
    main_offboard_executer = "drone_show.py"    # Name of script that executes offboard missions from CSV
    smart_swarm_executer = "smart_swarm.py"     # Name of the smart swarm executor script
    

    # at the end of your Params class or module
    USE_GLOBAL_SETPOINTS: bool = True   # if True, send PositionGlobalYaw instead of PositionNedYaw


    # Drift configuration
    DRIFT_THRESHOLD = 0.5  # Drift threshold in seconds
    DRIFT_CHECK_PERIOD = 1  # Time between drift checks in seconds (this can match the CSV step size)

    
    # Heartbeat interval (in seconds)
    heartbeat_interval = 10  

    # The Flask endpoint path for receiving drone heartbeats on GCS
    gcs_heartbeat_endpoint = "/drone-heartbeat"

    netbird_ip_prefix = "100."
    
    REQUIRE_GLOBAL_POSITION: bool = True  # Set to False if you want to skip global position checks
    

    # Smart Swarm Parameters
    CONTROL_LOOP_FREQUENCY = 10       # Control loop frequency in Hz
    LEADER_UPDATE_FREQUENCY = 3       # Leader update frequency in Hz
    DATA_FRESHNESS_THRESHOLD = 3.0    # Data freshness threshold in seconds


    CONFIG_UPDATE_INTERVAL = 5        # Periodic time for re-checking the swarm file (s)

    ENABLE_KALMAN_FILTER = False  # Set to False to disable Kalman filter

    # Logging Configuration
    MAX_LOG_FILES = 100  # Maximum number of log files to keep

    # Fixed gRPC Port for MAVSDK Server
    DEFAULT_GRPC_PORT = 50040

    # Critical Operation Settings
    PREFLIGHT_MAX_RETRIES = 40       # Maximum number of retries for pre-flight checks
    PRE_FLIGHT_TIMEOUT = 80          # Timeout for pre-flight checks in seconds
    LANDING_TIMEOUT = 10            # Timeout during landing phase in seconds

    # Trajectory and Landing Configuration
    GROUND_ALTITUDE_THRESHOLD = 1.0        # Threshold to determine if trajectory ends at ground level
    CONTROLLED_LANDING_ALTITUDE = 2.0      # Minimum altitude to start controlled landing
    CONTROLLED_LANDING_TIME = 1.0          # Minimum time before end of trajectory to start controlled landing
    MISSION_PROGRESS_THRESHOLD = 0.5       # Minimum mission progress percentage for controlled landing
    CONTROLLED_DESCENT_SPEED = 0.5         # Descent speed during controlled landing in m/s
    CONTROLLED_LANDING_TIMEOUT = 7        # Maximum time to wait during controlled landing


    AUTO_LAUNCH_POSITION = True  # Auto start trajectories at 0,0,0


    # Initial Position Correction
    ENABLE_INITIAL_POSITION_CORRECTION = False  # Enable initial position correction to account for GPS drift

    # Initial Climb Phase Settings
    INITIAL_CLIMB_ALTITUDE_THRESHOLD = 5.0  # Altitude threshold for initial climb phase
    INITIAL_CLIMB_TIME_THRESHOLD = 5.0      # Time threshold for initial climb phase
    INITIAL_CLIMB_VZ_DEFAULT = 1.0  # m/s

    # Possible values: "BODY_VELOCITY" or "LOCAL_NED"
    INITIAL_CLIMB_MODE = "BODY_VELOCITY"

    # Feedforward Control Settings
    FEEDFORWARD_VELOCITY_ENABLED = False        # Enable feedforward velocity setpoints
    FEEDFORWARD_ACCELERATION_ENABLED = False   # Enable feedforward acceleration setpoints

    # PD Controller Gains
    PD_KP = 0.5            # Proportional gain
    PD_KD = 0.1            # Derivative gain
    MAX_VELOCITY = 3.0     # Maximum velocity in m/s

    # Low-Pass Filter Parameter
    LOW_PASS_FILTER_ALPHA = 0.2  # Smoothing factor between 0 and 1
    
    
    # New parameters for pos_id auto-detection
    auto_detection_enabled = True  # Enable or disable auto-detection
    auto_detection_interval = 15  # Interval in seconds
    max_deviation = 1.5 # Maximum allowed deviation in meters for pos_id detection

    # =========================
    # SWARM TRAJECTORY CONFIGURATION
    # =========================

    # Basic Trajectory Settings
    swarm_trajectory_dt = 0.05              # Trajectory interpolation timestep (seconds)
    swarm_trajectory_max_speed = 20.0       # Maximum allowed speed (m/s) - for safety

    # WAYPOINT ACCEPTANCE RADIUS (most important setting)
    # How close to waypoint before considering "reached" and starting turn
    swarm_waypoint_acceptance_radius = 4.0  # meters

    # TUNING GUIDE:
    # 1.0-2.0m  = Very tight turns (precision/aerobatic shows)
    # 3.0-5.0m  = Balanced turns (recommended for most shows)  ← YOU ARE HERE
    # 6.0-10.0m = Smooth turns (cinematic/large formations)
    #
    # TOO TIGHT NOW? Try: 5.0 or 6.0
    # TOO LOOSE?    Try: 3.0 or 2.0

    # FLIGHT MODE
    swarm_flyover_mode = True               # True = fly OVER waypoints exactly
                                            # False = cut corners for efficiency
                                            # Keep True for precision shows

    # ADVANCED SETTINGS (usually don't need to change)
    swarm_curve_tightness = 0.6             # 0.0-1.0 (not used in current implementation)
    swarm_speed_adaptive = True             # Auto-adjust radius based on speed

    # LED Colors for swarm trajectory mode (RGB)
    swarm_leader_led_color = (255, 0, 0)    # Red for leaders
    swarm_follower_led_color = (0, 255, 0)  # Green for followers

    # Processing configuration
    swarm_missing_leader_strategy = 'skip'  # 'skip' or 'error' when leader CSV missing

    # =========================
    # Swarm Trajectory Mode Parameters
    # =========================
    
    # File Path Configuration
    SWARM_TRAJECTORY_BASE_PATH = "swarm_trajectory/processed"
    SWARM_TRAJECTORY_FILE_PREFIX = "Drone "
    SWARM_TRAJECTORY_FILE_SUFFIX = ".csv"
    
    # End-of-Mission Behavior Options
    # Available modes: 'return_home', 'land_current', 'hold_position', 'continue_heading'
    SWARM_TRAJECTORY_END_BEHAVIOR = 'return_home'
    
    # Mission Execution Settings
    SWARM_TRAJECTORY_FORCE_GLOBAL = True       # Always use global offboard positioning
    SWARM_TRAJECTORY_REQUIRE_YAW = True        # Use yaw from CSV trajectory
    SWARM_TRAJECTORY_SYNC_TOLERANCE = 0.1      # Synchronization tolerance in seconds
    
    # Safety and Performance
    SWARM_TRAJECTORY_SAFETY_MARGIN = 2.0       # Safety margin for trajectory execution
    SWARM_TRAJECTORY_MAX_VELOCITY = 15.0       # Maximum velocity for trajectory mode
    SWARM_TRAJECTORY_TIMEOUT_MULTIPLIER = 1.2  # Timeout multiplier for mission duration
    
    # Takeoff Configuration (same as drone show)
    SWARM_TRAJECTORY_TAKEOFF_MODE = "BODY_VELOCITY"  # Use same as drone show
    SWARM_TRAJECTORY_TAKEOFF_ALT = 5.0               # Initial takeoff altitude
    
    # Logging and Debug
    SWARM_TRAJECTORY_VERBOSE_LOGGING = True     # Enable detailed trajectory logging
    SWARM_TRAJECTORY_LOG_WAYPOINTS = False      # Log each waypoint execution
    
    # React UI Integration
    swarm_trajectory_executer = "swarm_trajectory_mission.py"  # Script name for UI

    # =========================
    # SWARM TRAJECTORY INITIAL CLIMB CONFIGURATION
    # =========================

    # Dedicated climb phase parameters for swarm trajectory mode multicopter synchronization
    # These handle the gap between t=0 and first CSV waypoint time in swarm trajectory missions
    SWARM_TRAJECTORY_INITIAL_CLIMB_HEIGHT = 5.0    # meters above first setpoint altitude
    SWARM_TRAJECTORY_INITIAL_CLIMB_TIME = 5.0      # seconds for climb phase duration
    SWARM_TRAJECTORY_INITIAL_CLIMB_SPEED = 1.0     # m/s vertical climb speed (positive = up)

    @classmethod
    def get_swarm_trajectory_file_path(cls, position_id):
        """
        Returns the path to the swarm trajectory file based on position ID and mode.
        
        Args:
            position_id (int): The drone's position identifier.
            
        Returns:
            str: Full path to the trajectory CSV file
        """
        base_dir = 'shapes_sitl' if cls.sim_mode else 'shapes'
        filename = f"{cls.SWARM_TRAJECTORY_FILE_PREFIX}{position_id}{cls.SWARM_TRAJECTORY_FILE_SUFFIX}"
        
        trajectory_path = os.path.join(
            base_dir, 
            cls.SWARM_TRAJECTORY_BASE_PATH, 
            filename
        )
        
        # Debug: Print the trajectory file path
        print(f"[DEBUG] Swarm Trajectory File: {trajectory_path}")
        return trajectory_path

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
