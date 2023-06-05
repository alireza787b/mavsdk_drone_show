import time
import math


def map_shape_to_code(shape_name):
    """
    Function to map shape names to shape codes and their respective function calls.

    Args:
    shape_name: A string that represents the name of the shape.

    Returns:
    A tuple of shape_code, shape_fcn and shape_args.
    """

    # Define a dictionary to map shape names to their enumeration or number codes and respective function calls
    shape_dict = {
        "eight_shape": (0, eight_shape_trajectory, ()),
        "circle": (1, circle_trajectory, ()),
        "square": (2, square_trajectory, ()),
        "helix": (3, helix_trajectory, (20, 3)),  # Helix trajectory requires additional arguments for end altitude and number of turns
        "heart_shape": (4, heart_shape_trajectory, ()),
        "infinity_shape": (5, infinity_shape_trajectory, ()),
        "spiral_square": (6, spiral_square_trajectory, (3,)),  # Spiral square trajectory requires additional argument for number of turns
        "star_shape": (7, star_shape_trajectory, (5,)),  # Star shape trajectory requires additional argument for number of points
        "zigzag": (8, zigzag_trajectory, (3,)),  # Zigzag trajectory requires additional argument for number of turns
        "sine_wave": (9, sine_wave_trajectory, (3,)),  # Sine wave trajectory requires additional argument for number of turns
        "stationary": (10, stationary_trajectory, ())  # Stationary trajectory requires additional arguments for position and duration

    }
    
    # Check if the shape_name exists in the dictionary
    if shape_name in shape_dict:
        shape_code, shape_fcn, shape_args = shape_dict[shape_name]
    else:
        # Raise an error for invalid shape names
        raise ValueError(f"Invalid shape name: {shape_name}")
    
    return shape_code, shape_fcn, shape_args


def sine_wave_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time, turns):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time * turns

    x = diameter * t / maneuver_time
    y = diameter * math.sin(theta)
    z = -1 * initial_alt

    vx = diameter / maneuver_time
    vy = diameter * math.cos(theta) * 2 * direction * math.pi * turns / maneuver_time
    vz = 0

    ax = -diameter * math.sin(theta) * 2 * direction * math.pi * turns / maneuver_time ** 2
    ay = diameter * math.cos(theta) * 4 * direction * math.pi * turns ** 2 / maneuver_time ** 2
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az




def infinity_shape_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    x = (diameter / 2) * math.sin(theta)
    y = direction * (diameter / 4) * math.sin(2 * theta)
    z = -1 * initial_alt

    vx = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi / maneuver_time
    vy = direction * (diameter / 4) * math.cos(2 * theta) * 4 * direction * math.pi / maneuver_time
    vz = 0

    ax = -(diameter / 2) * math.sin(theta) * 4 * direction * math.pi * math.cos(theta) / maneuver_time ** 2
    ay = -direction * (diameter / 4) * math.sin(2 * theta) * 8 * direction * math.pi * math.cos(2 * theta) / maneuver_time ** 2
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az


def spiral_square_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time, turns):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time * turns

    r = diameter * t / maneuver_time
    x = r * math.cos(theta)
    y = r * math.sin(theta)
    z = -1 * initial_alt

    vx = diameter * (math.cos(theta) - t * math.sin(theta)) / maneuver_time
    vy = diameter * (math.sin(theta) + t * math.cos(theta)) / maneuver_time
    vz = 0

    ax = -diameter * math.sin(theta) * 2 * direction * math.pi * turns / maneuver_time ** 2
    ay = diameter * math.cos(theta) * 4 * direction * math.pi * turns ** 2 / maneuver_time ** 2
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az

def star_shape_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time, points):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    r = diameter * (1 - math.sin(points * theta))
    x = r * math.cos(theta)
    y = r * math.sin(theta)
    z = -1 * initial_alt

    vx = diameter * (math.cos(theta) - points * math.cos(points * theta)) / maneuver_time
    vy = diameter * (math.sin(theta) - points * math.sin(points * theta)) / maneuver_time
    vz = 0

    ax = -diameter * math.sin(theta) * 4 * direction * math.pi * points * math.cos(theta) / maneuver_time ** 2
    ay = -diameter * math.sin(2 * theta) * 8 * direction * math.pi * points * math.cos(2 * theta) / maneuver_time ** 2
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az


def zigzag_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time, turns):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time * turns

    x = diameter * t / maneuver_time
    y = diameter * math.sin(theta)
    z = -1 * initial_alt

    vx = diameter / maneuver_time
    vy = diameter * math.cos(theta) * 2 * direction * math.pi * turns / maneuver_time
    vz = 0

    ax = -diameter * math.sin(theta) * 2 * direction * math.pi * turns / maneuver_time ** 2
    ay = diameter * math.cos(theta) * 4 * direction * math.pi * turns ** 2 / maneuver_time ** 2
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az

def heart_shape_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    radius = diameter / 2
    scale_factor = 30 / 400  # Adjust the scale factor to match the desired ratio

    x = scale_factor * radius * 16 * math.sin(theta) ** 3
    y = radius * (13 * math.cos(theta) - 5 * math.cos(2 * theta) - 2 * math.cos(3 * theta) - math.cos(4 * theta)) / 13
    z = -1 * initial_alt

    vx = scale_factor * radius * 48 * math.pi * math.sin(theta) ** 2 * math.cos(theta) / maneuver_time
    vy = radius * (13 * math.sin(theta) - 10 * math.sin(2 * theta) - 6 * math.sin(3 * theta) - 4 * math.sin(4 * theta)) * 2 * math.pi / (13 * maneuver_time)
    vz = 0

    ax = -scale_factor * radius * 48 * math.pi * math.sin(theta) ** 3 * math.cos(theta) / maneuver_time ** 2
    ay = -radius * (13 * math.cos(theta) - 10 * math.cos(2 * theta) - 6 * math.cos(3 * theta) - 4 * math.cos(4 * theta)) * 4 * math.pi ** 2 / (13 * maneuver_time ** 2)
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az


def stationary_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):

    x = 0
    y = 0
    z = -1 * initial_alt

    vx =0
    vy =0
    vz = 0

    ax = 0
    ay =0
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az






def helix_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time, end_altitude, turns):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time * turns

    x = (diameter / 2) * math.cos(theta)
    y = (diameter / 2) * math.sin(theta)
    z = -1 * (initial_alt + (end_altitude - initial_alt) * (t / maneuver_time))

    vx = -(diameter / 2) * math.sin(theta) * 2 * direction * math.pi * turns / maneuver_time
    vy = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi * turns / maneuver_time
    vz = -1 * (initial_alt - end_altitude) / maneuver_time

    ax = -(diameter / 2) * math.cos(theta) * 4 * direction * math.pi * turns ** 2 / maneuver_time ** 2
    ay = -(diameter / 2) * math.sin(theta) * 4 * direction * math.pi * turns ** 2 / maneuver_time ** 2
    az = -1 * (initial_alt - end_altitude) / maneuver_time ** 2

    return x, y, z, vx, vy, vz, ax, ay, az




def eight_shape_trajectory(step, maneuver_time, diameter, direction,initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    x = (diameter / 2) * math.sin(theta)
    y = direction * (diameter / 4) * math.sin(2 * theta)
    z = -1 * initial_alt

    vx = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi / maneuver_time
    vy = direction * (diameter / 4) * math.cos(2 * theta) * 4 * direction * math.pi / maneuver_time
    vz = 0

    ax = -(diameter / 2) * math.sin(theta) * 4 * direction * math.pi **2 / maneuver_time **2
    ay = -direction * (diameter / 4) * math.sin(2 * theta) * 8 * direction * math.pi **2 / maneuver_time **2
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az


def circle_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    x = (diameter / 2) * math.cos(theta)
    y = (diameter / 2) * math.sin(theta)
    z = -1 * initial_alt

    vx = -(diameter / 2) * math.sin(theta) * 2 * direction * math.pi / maneuver_time
    vy = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi / maneuver_time
    vz = 0

    ax = -(diameter / 2) * math.cos(theta) * 4 * direction * math.pi ** 2 / maneuver_time ** 2
    ay = -(diameter / 2) * math.sin(theta) * 4 * direction * math.pi ** 2 / maneuver_time ** 2
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az

def square_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):
    t = step * step_time
    side_length = diameter / math.sqrt(2)
    side_time = maneuver_time / 4
    side_steps = int(maneuver_time / (4 * step_time))

    current_side = step // side_steps
    side_progress = (step % side_steps) / side_steps

    if current_side == 0:
        x = side_length * side_progress
        y = 0
    elif current_side == 1:
        x = side_length
        y = side_length * side_progress
    elif current_side == 2:
        x = side_length * (1 - side_progress)
        y = side_length
    else:
        x = 0
        y = side_length * (1 - side_progress)

    if direction == -1:
        x, y = y, x

    z = -1 * initial_alt

    vx = side_length / side_time if (current_side == 0 or current_side == 2) else 0
    vy = side_length / side_time if (current_side == 1 or current_side == 3) else 0
    vz = 0

    if direction == -1:
        vx, vy = vy, vx

    ax = -side_length / side_time ** 2 * math.sin(2 * direction * math.pi * t / maneuver_time) if (current_side == 0 or current_side == 2) else 0
    ay = -side_length / side_time ** 2 * math.cos(2 * direction * math.pi * t / maneuver_time) if (current_side == 1 or current_side == 3) else 0
    az = 0

    return x, y, z, vx, vy, vz, ax, ay, az
