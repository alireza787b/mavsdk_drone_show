# src/params.py

import os
import struct
from enum import Enum
from pathlib import Path

from mds_logging import get_logger

logger = get_logger("params")

# ===================================================================================
# LOCAL CONFIGURATION LOADING
# ===================================================================================
# Load local overrides from /etc/mds/local.env if it exists.
# This allows per-drone configuration without modifying the repository.
#
# Priority: local.env settings > environment variables > hardcoded defaults
#
# See tools/local.env.template for available settings.
# ===================================================================================
_local_env_path = Path('/etc/mds/local.env')
if _local_env_path.exists():
    try:
        with open(_local_env_path) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Only set if not already set (allows env vars to override)
                    if key not in os.environ:
                        os.environ[key] = value
        logger.debug(f"Loaded local config from {_local_env_path}")
    except Exception as e:
        logger.warning(f"Failed to load local config from {_local_env_path}: {e}")


def _safe_int(value: str, default: int) -> int:
    """Safely convert string to int with fallback to default."""
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer value '{value}', using default {default}")
        return default


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean feature flag from environment or local.env."""
    value = os.environ.get(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False

    logger.warning(f"Invalid boolean value for {name!r}: {value!r}. Using default {default}.")
    return default


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
        config_file_name (str): Filename for the configuration file (JSON).
        swarm_file_name (str): Filename for the swarm file (JSON).
        GIT_BRANCH (str): Git branch name used for synchronization.
        (Other attributes as per project requirements.)
    """

    # Path to the 'real.mode' file relative to the current directory
    real_mode_file = 'real.mode'

    # Determine simulation mode based on the existence of 'real.mode'
    # If 'real.mode' exists, sim_mode is False (real-life mode)
    sim_mode = not os.path.exists(real_mode_file)

    # Configuration CSV filenames (determined by mode)
    # URLs for configuration files (not used in current implementation)
    config_url = 'https://nb1.joomtalk.ir/download/config.json'
    swarm_url = 'https://nb1.joomtalk.ir/download/swarm.json'

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
    #   MDS_REPO_URL       - Git repository URL (SSH or HTTPS)
    #   MDS_BRANCH         - Git branch name
    #   MDS_GIT_AUTO_PUSH  - Enable/disable automatic commit+push from GCS workflows
    # ===================================================================================
    GIT_AUTO_PUSH = _env_flag('MDS_GIT_AUTO_PUSH', True)
    GIT_REPO_URL = os.environ.get('MDS_REPO_URL', 'git@github.com:alireza787b/mavsdk_drone_show.git')
    GIT_BRANCH = os.environ.get('MDS_BRANCH', 'main-candidate')

    # ===================================================================================
    # GCS (Ground Control Station) CONFIGURATION
    # ===================================================================================
    # Central GCS IP address used by all drones for:
    #   - Heartbeat sending
    #   - MAVLink routing
    #   - Telemetry reporting
    #   - API communication
    #   - Origin coordinate fetching
    #
    # Mode-specific GCS IP configuration:
    #   - SITL: Uses Docker gateway (172.18.0.1)
    #   - Real: Uses Tailscale/physical network IP
    #
    # Override via MDS_GCS_IP environment variable or /etc/mds/local.env
    # ===================================================================================
    if sim_mode:
        GCS_IP = os.environ.get('MDS_GCS_IP', "172.18.0.1")  # SITL: Docker gateway IP
    else:
        GCS_IP = os.environ.get('MDS_GCS_IP', "100.96.32.75")  # Real mode: default GCS IP

    gcs_api_port = _safe_int(os.environ.get('MDS_GCS_API_PORT', '5000'), 5000)
    connectivity_check_ip = os.environ.get('MDS_CONNECTIVITY_IP', GCS_IP)
    connectivity_check_port = _safe_int(os.environ.get('MDS_CONNECTIVITY_PORT', str(gcs_api_port)), gcs_api_port)
    connectivity_check_interval = 10       # Interval in seconds between connectivity checks

    # Conditional Configuration File Names based on sim_mode
    if sim_mode:
        config_file_name = "config_sitl.json"
        swarm_file_name = "swarm_sitl.json"
    else:
        config_file_name = "config.json"
        swarm_file_name = "swarm.json"

    # General Settings
    enable_drones_http_server = True  # Enable HTTP server on drones
    single_drone = False              # Enable single drone mode
    offline_config = True             # Use offline configuration (not used!)
    offline_swarm = True              # Use offline swarm (not used!)
    default_sitl = True               # Use default 14550 port for single drone simulation
    online_sync_time = True           # Sync time from Internet Time Servers
    MAX_STALE_DURATION = 10           # Max time delay follower would still use the leader data
    SMART_SWARM_LEADER_STATE_TIMEOUT_SEC = 1.0   # Per-request timeout for follower -> leader state fetches
    SMART_SWARM_GCS_CONFIG_TIMEOUT_SEC = 2.0     # Per-request timeout for follower -> GCS swarm config refresh
    SMART_SWARM_GCS_NOTIFY_TIMEOUT_SEC = 2.0     # Per-request timeout for follower -> GCS leader-change notify
    
    reboot_after_params = True
    

    # how many failed polls before we elect
    MAX_LEADER_UNREACHABLE_ATTEMPTS = 15

    # minimum seconds between successive elections
    LEADER_ELECTION_COOLDOWN = 30
    SMART_SWARM_LEADER_LOSS_STRATEGY = "upstream_or_hold"

    
    csv_dt = 0.05                     # default step time of the processed CSV file to generate (s)



    # API Server Configuration
    drone_api_port = 7070                   # Port for the drone's API server
    polling_interval = 1                    # Polling interval in seconds (legacy, used by standalone git_status.py)
    telem_poll_interval = 1                 # GCS telemetry polling interval in seconds
    git_poll_interval = 10                  # GCS git status polling interval in seconds
    GCS_TELEMETRY_REQUEST_TIMEOUT_SEC = 2.0 # Per-request timeout for GCS -> drone telemetry pulls
    GCS_GIT_STATUS_REQUEST_TIMEOUT_SEC = 5.0  # Per-request timeout for GCS -> drone git-status pulls
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

    # GCS Server Port Configuration (Legacy Aliases)
    GCS_PORT = gcs_api_port                 # DEPRECATED: Use gcs_api_port instead
    gcs_server_port = gcs_api_port          # DEPRECATED: Use gcs_api_port instead
    flask_telem_socket_port = gcs_api_port  # DEPRECATED: Use gcs_api_port instead
    GCS_FLASK_PORT = gcs_api_port           # DEPRECATED: Use gcs_api_port instead

    get_position_deviation_URI = 'get-position-deviation'
    acceptable_deviation = 3.0              # Acceptable deviation in meters

    TELEMETRY_POLLING_TIMEOUT = 10  # Threshold in seconds to check for telemetry timeout
    HTTP_REQUEST_TIMEOUT = 5        # Timeout in seconds for HTTP requests

    enable_default_subscriptions = True  # All drones subscribe to each other for continuous polling
    
    enable_connectivity_check  = True # Enable Connectivity check Thread to ping GCS

    # Environment Mode - controls logging verbosity
    # Set ENV_MODE environment variable to 'production' for cleaner logs
    env_mode = os.getenv('ENV_MODE', 'production')  # Default to production (less verbose)

    # UDP Telemetry Configuration
    enable_udp_telemetry = False         # Enable/disable UDP telemetry
    TELEM_SEND_INTERVAL = 0.5            # Send telemetry data every TELEM_SEND_INTERVAL seconds
    local_mavlink_refresh_interval = 0.1 # Refresh interval for local MAVLink connection
    broadcast_mode = True                # Enable broadcast mode
    extra_swarm_telem = []               # Extra swarm telemetry IPs
    income_packet_check_interval = 0.1   # Interval for checking incoming packets

    # -------------------------------------------------------------------------
    # MAVLink Ports Configuration
    # -------------------------------------------------------------------------
    # MAVLink routing is EXTERNAL (not managed by this application):
    #   - SITL: tools/run_mavlink_router.sh (started by startup_sitl.sh)
    #   - Real hardware: mavlink-anywhere systemd service
    # See docs/guides/mavlink-routing-setup.md for setup instructions.
    #
    # These ports must match the external router configuration:
    mavsdk_port = 14540                # MAVSDK SDK connection
    local_mavlink_port = 12550         # LocalMavlinkController (pymavlink telemetry)
    LOCAL_MAVLINK_TIMEOUT_SEC = 5      # Per-read timeout for local pymavlink listener
    LOCAL_MAVLINK_RECONNECT_AFTER_TIMEOUTS = 3  # Re-open listener after repeated silence
    local_mavlink2rest_port = 14569    # mavlink2rest REST API bridge
    gcs_mavlink_port = 14550           # Ground Control Station (QGC)

    # Serial port defaults (used as fallback in drone_config if not specified in config)
    # These are reference values for mavlink-anywhere configuration on real hardware
    serial_mavlink_port = '/dev/ttyS0' # Default serial port (Raspberry Pi UART)
    serial_baudrate = 57600            # Default serial baudrate

    hard_reboot_command_enabled = True  # Allow hard reboot commands (ensure root privileges)
    force_reboot = True

    schedule_mission_frequency = 2  # Frequency for scheduling missions

    # Sleep Interval for Main Loop
    sleep_interval = 0.1           # Sleep interval for the main loop in seconds
    trigger_sooner_seconds = 4     # Trigger mission a bit early to compensate for initialization

    max_takeoff_alt = 100          # Maximum allowable takeoff altitude
    default_takeoff_alt = 10       # Default takeoff altitude
    TAKEOFF_PREFLIGHT_TIMEOUT_SEC = 30  # MAVSDK GPS/home readiness wait before takeoff
    TAKEOFF_ALTITUDE_CONFIRM_TIMEOUT_SEC = 60  # Allow slower multi-drone SITL climbs before declaring takeoff failure
    LAND_ACTION_MIN_DISARM_WAIT_SEC = 45       # Minimum wait budget for LAND action to fully disarm
    LAND_ACTION_ASSUMED_DESCENT_RATE_MPS = 1.5 # Conservative PX4 autonomous descent-rate estimate for high-altitude LAND/RTL flows
    LAND_ACTION_DISARM_BUFFER_SEC = 30         # Extra landing/disarm buffer above the estimated descent time
    LAND_ACTION_MAX_DISARM_WAIT_SEC = 900      # Cap LAND action wait time for very high-altitude recoveries
    LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC = 20  # Extra wait after touchdown before forcing explicit disarm
    RTL_ACTION_COMPLETION_TIMEOUT = 300        # Minimum wait budget for standalone RTL to return home, land, and disarm
    RTL_ACTION_COMPLETION_BUFFER_SEC = 120     # Extra travel-home buffer above the estimated landing/disarm time
    RTL_ACTION_COMPLETION_MAX_TIMEOUT = 1200   # Hard cap for very long standalone RTL recoveries
    COMMAND_TRACKING_DEFAULT_TIMEOUT_MS = 60000  # Fallback tracker timeout when no mission-specific estimate is available
    COMMAND_TRACKING_ACTION_BUFFER_SEC = 30      # Extra tracker slack for short actions after expected completion
    COMMAND_TRACKING_MISSION_BUFFER_SEC = 120    # Extra tracker slack for show/trajectory mission playback
    COMMAND_TRACKING_HOVER_TEST_TIMEOUT_SEC = 180  # Conservative tracker budget for hover-test workflows
    COMMAND_TRACKING_QUICKSCOUT_TIMEOUT_SEC = 900  # Fallback tracker budget until QuickScout duration is estimator-backed
    COMMAND_TRACKING_CHECK_INTERVAL_SEC = 1.0     # Background cadence for promoting stale commands to terminal timeout state
    COMMAND_REPORT_HTTP_TIMEOUT_SEC = 5           # Per-attempt HTTP timeout for drone -> GCS execution callbacks
    COMMAND_REPORT_RETRY_BASE_DELAY_SEC = 2       # Initial backoff for queued execution callback retries
    COMMAND_REPORT_RETRY_MAX_DELAY_SEC = 60       # Maximum backoff between queued execution callback retries
    COMMAND_REPORT_RETRY_MAX_AGE_SEC = 1800       # Drop queued execution callbacks after this age if GCS never returns
    COMMAND_REPORT_RETRY_LOOP_INTERVAL_SEC = 1.0  # Retry worker wake interval for queued execution callbacks

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

    # The API endpoint path for receiving drone heartbeats on GCS
    gcs_heartbeat_endpoint = "/drone-heartbeat"

    netbird_ip_prefix = "100."

    # GPS 3D Fix Requirement
    # When True, waits for GPS 3D fix and home position before starting mission
    # When False, skips GPS health checks (useful for LOCAL mode or future non-GPS modes)
    # Default: False (allows LOCAL mode operation without GPS)
    # Note: GLOBAL mode requires GPS regardless of this setting
    REQUIRE_GLOBAL_POSITION: bool = False

    # Phase 2: Auto Global Origin Correction Mode
    # When enabled, drones fetch shared origin from GCS and apply intelligent position correction
    # Default: True for new deployments (maximum precision)
    # Set to False to use legacy operator-placement mode (v3.7 behavior)
    AUTO_GLOBAL_ORIGIN_MODE = True

    # Safety threshold: Abort flight if drone position deviates more than this from expected position
    # Default: 20.0 meters (catches major operator placement errors)
    ORIGIN_DEVIATION_ABORT_THRESHOLD_M = 20.0

    # Duration of smooth transition from current position to corrected trajectory after initial climb
    # Default: 3.0 seconds (prevents abrupt movements)
    BLEND_TRANSITION_DURATION_SEC = 3.0

    # Minimum altitude safety margin during blend phase (Phase 2)
    # Prevents sinking by ensuring blend target altitude is never below current altitude minus this margin
    # Set to 0.0 to allow descent, or positive value to force upward bias during blend
    # Default: 0.5 meters (ensures slight upward movement, preventing any sinking)
    MIN_BLEND_ALTITUDE_MARGIN_M = 0.5

    # Warn if cached origin is older than this (in seconds)
    # Default: 3600 seconds (1 hour)
    ORIGIN_CACHE_STALENESS_WARNING_SEC = 3600

    # Timeout for fetching origin from GCS server
    # Default: 5.0 seconds
    ORIGIN_FETCH_TIMEOUT_SEC = 5.0

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
    OFFBOARD_ARM_HEALTH_TIMEOUT_SEC = 15.0   # Wait budget for PX4 armability after preflight already passed
    OFFBOARD_ARM_HEALTH_POLL_SEC = 0.5       # Max wait between MAVSDK health samples during mission startup
    OFFBOARD_ARM_HEALTH_STABLE_SAMPLES = 1   # Consecutive healthy samples required before arming
    OFFBOARD_ARM_MAX_ATTEMPTS = 3            # Bounded arm retries for transient PX4 pre-arm denials
    OFFBOARD_ARM_RETRY_DELAY_SEC = 2.0       # Delay between arm retries after COMMAND_DENIED
    OFFBOARD_START_MAX_ATTEMPTS = 3          # Bounded retries when starting offboard mode
    OFFBOARD_START_RETRY_DELAY_SEC = 1.0     # Delay between offboard-start retries
    LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC = 5.0  # Local MAVSDK connect wait for on-demand launch probes
    LIVE_ARMABILITY_PROBE_TIMEOUT_SEC = 6.0          # Bounded wait for live MAVSDK armability probes
    LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC = 2.0      # Extra transport margin for the HTTP caller wrapping the probe

    # Trajectory and Landing Configuration
    GROUND_ALTITUDE_THRESHOLD = 1.0        # Threshold to determine if trajectory ends at ground level
    CONTROLLED_LANDING_ALTITUDE = 2.0      # Minimum altitude to start controlled landing
    CONTROLLED_LANDING_TIME = 1.0          # Minimum time before end of trajectory to start controlled landing
    MISSION_PROGRESS_THRESHOLD = 0.5       # Minimum mission progress percentage for controlled landing
    CONTROLLED_DESCENT_SPEED = 0.5         # Descent speed during controlled landing in m/s
    CONTROLLED_LANDING_TIMEOUT = 7        # Maximum time to wait during controlled landing
    CONTROLLED_LANDING_BUFFER_SEC = 5      # Extra touchdown margin for low-altitude precision descent
    CONTROLLED_LANDING_MAX_TIMEOUT_SEC = 120  # Hard cap for controlled landing fallback wait


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
    SMART_SWARM_LEADER_VELOCITY_FEEDFORWARD = 1.0  # Scale factor for leader velocity feedforward

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
    SWARM_TRAJECTORY_RTL_COMPLETION_TIMEOUT = 600  # Max time to wait for RTL end behavior to land/disarm
    SWARM_TRAJECTORY_RTL_COMPLETION_BUFFER_SEC = 180  # Extra RTL leg time before touchdown/disarm should complete
    SWARM_TRAJECTORY_RTL_COMPLETION_MAX_TIMEOUT = 1800  # Hard cap for very long RTL recoveries
    SWARM_TRAJECTORY_RTL_DISARM_GRACE_SEC = 15    # Grace period to auto-disarm after RTL touchdown if PX4 remains armed
    SWARM_TRAJECTORY_RTL_HOME_STALL_RADIUS_M = 25.0  # Treat the drone as "back home" when within this horizontal radius
    SWARM_TRAJECTORY_RTL_STALL_DESCENT_EPS_MPS = 0.3  # Smaller descent rates are treated as effectively stalled
    SWARM_TRAJECTORY_RTL_HOME_STALL_TRIGGER_SEC = 20  # Time to tolerate home-hover stall before forcing LAND fallback
    SWARM_TRAJECTORY_RTL_NEAR_GROUND_ALTITUDE_M = 0.75  # Treat RTL as effectively down once relative altitude is near ground
    SWARM_TRAJECTORY_RTL_NEAR_GROUND_SPEED_EPS_MPS = 1.5  # Horizontal motion below this starts the near-ground RTL cleanup timer
    SWARM_TRAJECTORY_RTL_NEAR_GROUND_STALL_TRIGGER_SEC = 10  # Time to tolerate a near-ground low-motion RTL state before forcing LAND fallback
    SWARM_TRAJECTORY_RTL_NEAR_GROUND_RELEASE_ALTITUDE_M = 1.5  # Once the timer starts, keep it armed until the aircraft climbs well clear of the ground again
    SWARM_TRAJECTORY_RTL_NEAR_GROUND_RELEASE_SPEED_EPS_MPS = 2.5  # Near-ground cleanup tolerates some skid/drift before resetting the timer
    SWARM_TRAJECTORY_RTL_NEAR_GROUND_RELEASE_DESCENT_EPS_MPS = 0.6  # Release the timer only when vertical motion meaningfully departs from the near-ground state
    SWARM_TRAJECTORY_ACTION_COMMAND_TIMEOUT_SEC = 10  # Bound MAVSDK action RPCs so cleanup cannot hang indefinitely
    SWARM_TRAJECTORY_RTL_MODE_TRANSITION_TIMEOUT_SEC = 15  # PX4 should enter RTL promptly after command acceptance
    SWARM_TRAJECTORY_RTL_ENGAGE_MAX_ATTEMPTS = 2  # Retry RTL once before degrading to LAND fallback
    SWARM_TRAJECTORY_LAND_TRANSITION_TIMEOUT_SEC = 15  # LAND should reach a landing/touchdown state promptly once commanded
    
    # Takeoff Configuration (same as drone show)
    SWARM_TRAJECTORY_TAKEOFF_MODE = "BODY_VELOCITY"  # Use same as drone show
    SWARM_TRAJECTORY_TAKEOFF_ALT = 5.0               # Initial takeoff altitude
    
    # Logging and Debug
    SWARM_TRAJECTORY_VERBOSE_LOGGING = True     # Enable detailed trajectory logging
    SWARM_TRAJECTORY_LOG_WAYPOINTS = False      # Log each waypoint execution
    SWARM_TRAJECTORY_PROGRESS_LOG_INTERVAL_WAYPOINTS = 200  # Regular progress-log cadence during long missions
    
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
    SWARM_TRAJECTORY_SHARED_DIR = os.getenv("MDS_SITL_SHARED_SWARM_TRAJECTORY_DIR", "").strip()

    @classmethod
    def get_swarm_trajectory_file_path(cls, position_id):
        """
        Returns the path to the swarm trajectory file based on position ID and mode.
        
        Args:
            position_id (int): The drone's position identifier.
            
        Returns:
            str: Full path to the trajectory CSV file
        """
        filename = f"{cls.SWARM_TRAJECTORY_FILE_PREFIX}{position_id}{cls.SWARM_TRAJECTORY_FILE_SUFFIX}"

        if cls.sim_mode and cls.SWARM_TRAJECTORY_SHARED_DIR:
            shared_path = os.path.join(
                cls.SWARM_TRAJECTORY_SHARED_DIR,
                "processed",
                filename,
            )
            if os.path.exists(shared_path):
                logger.debug(f"Swarm Trajectory File: {shared_path} (shared SITL workspace)")
                return shared_path

        base_dir = 'shapes_sitl' if cls.sim_mode else 'shapes'
        trajectory_path = os.path.join(
            base_dir,
            cls.SWARM_TRAJECTORY_BASE_PATH,
            filename
        )

        logger.debug(f"Swarm Trajectory File: {trajectory_path}")
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

        logger.debug(f"Drone Trajectory File: {drone_show_trajectory_filename}")
        logger.debug(f"Custom Trajectory File: {custom_show_trajectory_filename}")

        return (drone_show_trajectory_filename, custom_show_trajectory_filename)
