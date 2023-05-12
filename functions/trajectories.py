import time
import math


def sine_wave_trajectory(step, maneuver_time, diameter, direction, initial_alt , step_time, turns):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time * turns

    x = diameter * t / maneuver_time
    y = diameter * math.sin(theta)
    z = -1 * initial_alt

    vx = diameter / maneuver_time
    vy = diameter * math.cos(theta) * 2 * direction * math.pi * turns / maneuver_time
    vz = 0

    return x, y, z, vx, vy, vz



def infinity_shape_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    x = (diameter / 2) * math.sin(theta)
    y = direction * (diameter / 4) * math.sin(2 * theta)
    z = -1 * initial_alt

    vx = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi / maneuver_time
    vy = direction * (diameter / 4) * math.cos(2 * theta) * 4 * direction * math.pi / maneuver_time
    vz = 0

    return x, y, z, vx, vy, vz

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

    return x, y, z, vx, vy, vz

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

    return x, y, z, vx, vy, vz

def zigzag_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time, turns):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time * turns

    x = diameter * t / maneuver_time
    y = diameter * math.sin(theta)
    z = -1 * initial_alt

    vx = diameter / maneuver_time
    vy = diameter * math.cos(theta) * 2 * direction * math.pi * turns / maneuver_time
    vz = 0

    return x, y, z, vx, vy, vz




def heart_shape_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    x = diameter * (16 * math.sin(theta) ** 3)
    y = diameter * (13 * math.cos(theta) - 5 * math.cos(2 * theta) - 2 * math.cos(3 * theta) - math.cos(4 * theta)) / 15
    z = -1 * initial_alt

    vx = diameter * (48 * math.pi * math.sin(theta) ** 2 * math.cos(theta)) / maneuver_time
    vy = diameter * ((13 * math.sin(theta) - 10 * math.sin(2 * theta) - 6 * math.sin(3 * theta) - 4 * math.sin(4 * theta)) * 2 * math.pi / (15 * maneuver_time))
    vz = 0

    return x, y, z, vx, vy, vz




def helix_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time,end_altitude, turns):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time * turns

    x = (diameter / 2) * math.cos(theta)
    y = (diameter / 2) * math.sin(theta)
    z = -1 * (initial_alt + (end_altitude - initial_alt) * (t / maneuver_time))

    vx = -(diameter / 2) * math.sin(theta) * 2 * direction * math.pi * turns / maneuver_time
    vy = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi * turns / maneuver_time
    vz = -1 * (initial_alt - end_altitude) / maneuver_time

    return x, y, z, vx, vy, vz



def eight_shape_trajectory(step, maneuver_time, diameter, direction,initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    x = (diameter / 2) * math.sin(theta)
    y = direction * (diameter / 4) * math.sin(2 * theta)
    z = -1 * initial_alt

    vx = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi / maneuver_time
    vy = direction * (diameter / 4) * math.cos(2 * theta) * 4 * direction * math.pi / maneuver_time
    vz = 0

    return x, y, z, vx, vy, vz


def circle_trajectory(step, maneuver_time, diameter, direction, initial_alt, step_time):
    t = step * step_time
    theta = 2 * direction * math.pi * t / maneuver_time

    x = (diameter / 2) * math.cos(theta)
    y = (diameter / 2) * math.sin(theta)
    z = -1 * initial_alt

    vx = -(diameter / 2) * math.sin(theta) * 2 * direction * math.pi / maneuver_time
    vy = (diameter / 2) * math.cos(theta) * 2 * direction * math.pi / maneuver_time
    vz = 0

    return x, y, z, vx, vy, vz


def square_trajectory(step, maneuver_time, diameter, direction,initial_alt, step_time):
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

    return x, y, z, vx, vy, vz