#src/enums.py
from enum import Enum

class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2
    CUSTOM_CSV_DRONE_SHOW = 3 
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
    UNKNOWN = 999  # Ensure UNKNOWN is included

class State(Enum):
    IDLE = 0
    ARMED = 1
    TRIGGERED = 2
    UNKNOWN = 999  # Added UNKNOWN to State enum
