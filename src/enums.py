# Mission Types
from enum import Enum


class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2
    TAKE_OFF = 10
    LAND = 101
    HOLD = 102
    TEST = 100
    
    
class State(Enum):
    IDLE = 0
    ARMED = 1
    TRIGGERED = 2