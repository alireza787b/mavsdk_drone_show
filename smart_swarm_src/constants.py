from src.params import Params

# MAVSDK Server Ports
GRPC_PORT = 50041
MAVSDK_PORT = 14541

# Frequencies
CONTROL_LOOP_FREQUENCY = Params.swarm_control_frequency
LEADER_UPDATE_FREQUENCY = Params.leader_update_frequency

# Data Freshness Threshold
DATA_FRESHNESS_THRESHOLD = Params.data_freshness_threshold

# Maximum Retries
MAX_RETRIES = Params.max_connection_retries
FEEDFORWARD_VELOCITY_ENABLED = Params.swarm_velocity_feedforward

MAX_LOG_FILES = Params.MAX_LOG_FILES