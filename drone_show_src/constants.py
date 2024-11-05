# drone_show_src/constants.py
from src.params import Params



# Fixed gRPC port for MAVSDK server
GRPC_PORT = 50040

# MAVSDK port for communication
MAVSDK_PORT = 14540

# Flag to show deviations during flight
SHOW_DEVIATIONS = False

# Maximum number of retries for critical operations
MAX_RETRIES = 3

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

MAX_LOG_FILES = Params.MAX_LOG_FILES