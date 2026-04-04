#src/enums.py
from enum import Enum

class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2
    CUSTOM_CSV_DRONE_SHOW = 3
    SWARM_TRAJECTORY = 4
    QUICKSCOUT = 5
    HOVER_TEST = 106
    TAKE_OFF = 10
    LAND = 101
    HOLD = 102
    TEST = 100
    REBOOT_FC = 6
    REBOOT_SYS = 7
    TEST_LED = 8
    UPDATE_CODE = 103
    RETURN_RTL = 104
    KILL_TERMINATE = 105
    UNKNOWN = 999

    # New Missions:
    INIT_SYSID = 110
    APPLY_COMMON_PARAMS = 111

class State(Enum):
    IDLE = 0
    MISSION_READY = 1  # Mission loaded, waiting for trigger time (was ARMED)
    MISSION_EXECUTING = 2  # Mission is executing (was TRIGGERED)
    UNKNOWN = 999


class CommandResultCategory(str, Enum):
    """
    Categorization of command results for UX-friendly feedback.

    Used to distinguish between different types of command outcomes:
    - ACCEPTED: Drone successfully accepted the command
    - OFFLINE: Drone is unreachable (timeout/connection refused) - NOT an error
    - REJECTED: Drone actively rejected the command
    - ERROR: An unexpected error occurred
    - PENDING: Awaiting response
    """
    ACCEPTED = "accepted"   # Command accepted by drone
    OFFLINE = "offline"     # Drone unreachable (neutral - not an error)
    REJECTED = "rejected"   # Drone actively rejected command
    ERROR = "error"         # Unexpected error occurred
    PENDING = "pending"     # Awaiting response


class CommandStatus(str, Enum):
    """
    Status of a tracked command in the system.

    Lifecycle:
    CREATED → SUBMITTED → EXECUTING → COMPLETED/FAILED/PARTIAL
                       ↘ TIMEOUT
                       ↘ CANCELLED
    """
    CREATED = "created"       # Command created but not yet sent
    SUBMITTED = "submitted"   # Command sent to drones, awaiting ACKs
    EXECUTING = "executing"   # All ACKs received, execution in progress
    COMPLETED = "completed"   # All drones completed successfully
    PARTIAL = "partial"       # Some drones succeeded, some failed
    FAILED = "failed"         # All drones failed
    CANCELLED = "cancelled"   # Command was cancelled
    TIMEOUT = "timeout"       # Command timed out waiting for responses


class CommandPhase(str, Enum):
    """
    Operational phase of a tracked command.

    This separates transport/acknowledgment from actual execution so operator
    interfaces do not have to infer lifecycle state from legacy status values.
    """
    AWAITING_ACK = "awaiting_ack"
    PENDING_EXECUTION = "pending_execution"
    IN_PROGRESS = "in_progress"
    TERMINAL = "terminal"


class CommandOutcome(str, Enum):
    """
    Terminal outcome of a tracked command.
    """
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SUPERSEDED = "superseded"


class CommandErrorCode(str, Enum):
    """
    Standardized error codes for command processing.

    Error Code Ranges:
    - E1xx: Validation errors (missing/invalid fields)
    - E2xx: State errors (wrong state for command)
    - E3xx: Communication errors (timeout, connection)
    - E4xx: Execution errors (MAVSDK, script failures)
    - E5xx: System errors (internal, config)
    """
    # Validation errors (1xx)
    MISSING_MISSION_TYPE = "E100"
    INVALID_MISSION_TYPE = "E101"
    MISSING_TRIGGER_TIME = "E102"
    INVALID_TRIGGER_TIME = "E103"
    INVALID_ALTITUDE = "E104"
    MISSING_ORIGIN = "E105"
    INVALID_ORIGIN = "E106"
    INVALID_FORMAT = "E107"

    # State errors (2xx)
    INVALID_STATE = "E200"
    NOT_ARMED = "E201"
    NOT_READY_TO_ARM = "E202"
    ALREADY_EXECUTING = "E203"
    GPS_NOT_READY = "E204"
    HOME_NOT_SET = "E205"

    # Communication errors (3xx)
    TIMEOUT = "E300"
    CONNECTION_REFUSED = "E301"
    NETWORK_ERROR = "E302"
    HTTP_ERROR = "E303"
    DRONE_OFFLINE = "E304"       # Drone unreachable (not an error - informational)
    DRONE_UNREACHABLE = "E305"   # Alternative code for unreachable drone

    # Execution errors (4xx)
    MAVSDK_ERROR = "E400"
    PREFLIGHT_FAILED = "E401"
    ARM_FAILED = "E402"
    TAKEOFF_FAILED = "E403"
    MISSION_SCRIPT_ERROR = "E404"
    TRAJECTORY_NOT_FOUND = "E405"
    SEARCH_AREA_INVALID = "E406"
    COVERAGE_PLAN_FAILED = "E407"
    MISSION_UPLOAD_FAILED = "E408"

    # System errors (5xx)
    INTERNAL_ERROR = "E500"
    CONFIG_ERROR = "E501"
    HARDWARE_ERROR = "E502"

    @classmethod
    def get_description(cls, code: str) -> str:
        """Get human-readable description for an error code."""
        descriptions = {
            "E100": "Missing required field: mission_type",
            "E101": "Invalid or unknown mission type",
            "E102": "Missing required field: trigger_time",
            "E103": "Invalid trigger time format",
            "E104": "Invalid altitude value",
            "E105": "Missing origin coordinates",
            "E106": "Invalid origin coordinates",
            "E107": "Invalid data format",
            "E200": "Command not valid in current state",
            "E201": "Drone is not armed",
            "E202": "Drone failed pre-arm checks",
            "E203": "Another mission is already active",
            "E204": "GPS fix not acquired",
            "E205": "Home position not set",
            "E300": "Request timed out",
            "E301": "Connection refused by drone",
            "E302": "Network error",
            "E303": "HTTP error response",
            "E304": "Drone offline/unreachable",
            "E305": "Drone unreachable (alternative)",
            "E400": "MAVSDK communication error",
            "E401": "Pre-flight checks failed",
            "E402": "Failed to arm drone",
            "E403": "Takeoff failed",
            "E404": "Mission script error",
            "E405": "Trajectory file not found",
            "E406": "Invalid search area polygon",
            "E407": "Coverage planning algorithm failed",
            "E408": "Mission upload to drone failed",
            "E500": "Internal server error",
            "E501": "Configuration error",
            "E502": "Hardware error",
        }
        return descriptions.get(code, "Unknown error")
