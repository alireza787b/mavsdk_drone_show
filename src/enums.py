#src/enums.py
from enum import Enum

class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2
    CUSTOM_CSV_DRONE_SHOW = 3
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
