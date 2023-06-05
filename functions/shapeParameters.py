from dataclasses import dataclass


@dataclass
class ShapeParameters:
    """Base class for shape parameters."""
    num_drones: int
    heading: float
    distance: float
    viewer_position: tuple = (0, 0, 0)  # Viewer's position (NED)
    plane: str = 'vertical'
    offset: float = 0.0  # Assign a default value to offset
    base_altitude: float = 0.0
from dataclasses import dataclass




@dataclass
class CircleParameters(ShapeParameters):
    """Circle specific parameters."""
    radius: float = 1.0  # Assign a default value to radius

@dataclass
class SevenSegmentParameters(ShapeParameters):
    """Seven segment display specific parameters."""
    digit: int = 1  # digit to be displayed
    segment_length: float = 15.0  # length of each segment, default is 15
    # Patterns for digits 0-9 on a 7-segment display
    # 0 for off, 1 for on
    SEGMENT_PATTERNS = [
    [1, 1, 1, 0, 1, 1, 1],  # 0
    [0, 0, 1, 0, 0, 1, 0],  # 1
    [1, 0, 1, 1, 1, 0, 1],  # 2
    [1, 0, 1, 1, 0, 1, 1],  # 3
    [0, 1, 1, 1, 0, 1, 0],  # 4
    [1, 1, 0, 1, 0, 1, 1],  # 5
    [1, 1, 0, 1, 1, 1, 1],  # 6
    [0, 0, 1, 0, 0, 1, 1],  # 7
    [1, 1, 1, 1, 1, 1, 1],  # 8
    [1, 1, 1, 1, 0, 1, 1]   # 9
]
