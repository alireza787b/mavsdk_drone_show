#!/usr/bin/env python3
"""
Drone Show Script (drone_show.py)

----------------------------------------
Author: Alireza Ghaderi
Date: 2025-1-29
Version: 2.6.3
----------------------------------------

Description:
    This script controls a drone during a coordinated show by executing predefined trajectories
    with precise timing. It uses MAVSDK to manage operations (arming, offboard mode, landing) and
    provides visual feedback via LED indicators to signal various drone states.

Features:
    - Reads predefined trajectories from CSV files.
    - Supports both automatic and manual initial position settings.
    - Allows overriding auto launch position via command-line.
    - Provides clear logging:
          * When --debug is enabled, detailed debug logs are output.
          * Otherwise, summary logs are provided (e.g. every 5th waypoint in the trajectory loop).
    - Continuous setpoint transmission to keep offboard mode active (even when ahead-of-schedule).
    - Robust error handling to ensure safe drone operations.
    - LED indicators to reflect various states (blue: init, yellow: pre-flight, green: ready/complete, white: ready, red: error/disarmed).

Usage:
    python drone_show.py [--start_time START_TIME] [--custom_csv CUSTOM_CSV]
                           [--auto_launch_position {True,False}] [--debug]

Dependencies:
    - Python 3.7+
    - MAVSDK (pip install mavsdk)
    - psutil (pip install psutil)
    - tenacity (pip install tenacity)
    - Other dependencies as specified.
    
Note:
    Ensure that the 'mavsdk_server' executable is present in the specified directory and has the
    necessary execution permissions.
"""

import os
import sys
import time
import asyncio
import csv
import subprocess
import logging
import socket
import psutil
import requests
import argparse
from collections import namedtuple

from mavsdk import System
import mavsdk
from mavsdk.offboard import (
    PositionNedYaw,
    VelocityBodyYawspeed,
    VelocityNedYaw,
    AccelerationNed,
    OffboardError,
)
from mavsdk.telemetry import LandedState
from mavsdk.action import ActionError
from tenacity import retry, stop_after_attempt, wait_fixed

from src.led_controller import LEDController
from src.params import Params

from drone_show_src.utils import (
    configure_logging,
    read_hw_id,
    clamp_led_value,
    global_to_local,
)

# ----------------------------- #
#        Data Structures        #
# ----------------------------- #

# Drone configuration structure read from CSV.
Drone = namedtuple(
    "Drone",
    "hw_id pos_id initial_x initial_y ip mavlink_port debug_port gcs_ip",
)

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

HW_ID = None                      # Hardware ID of the drone (set from config)
position_id = None                # Position ID of the drone
global_synchronized_start_time = None  # Global synchronized start time (UNIX timestamp)
initial_position_drift = None     # Drift correction offset (PositionNedYaw)
drift_delta = 0.0                 # Time drift between scheduled waypoint time and actual elapsed time
DEBUG_MODE = False                # Flag indicating if detailed debug logs should be output

CONFIG_CSV_NAME = os.path.join(Params.config_csv_name)  # Path to drone configuration CSV

# ----------------------------- #
#         Helper Functions      #
# ----------------------------- #

def str2bool(v):
    """
    Convert a string to a boolean.

    Args:
        v (str): Input string.

    Returns:
        bool: Converted boolean value.
        
    Raises:
        argparse.ArgumentTypeError: If input is not a valid boolean.
    """
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

def blender_north_west_up_to_ned(x_b, y_b, z_b=0.0):
    """
    Convert a 3D vector from a Blender-like coordinate system to NED coordinates.
    
    In Blender:
      - X is North
      - Y is West
      - Z is Up
    In NED:
      - X is North (unchanged)
      - Y is East (i.e. negative of Blender Y)
      - Z is Down (i.e. negative of Blender Z)
    
    Args:
        x_b (float): Blender X coordinate.
        y_b (float): Blender Y coordinate.
        z_b (float): Blender Z coordinate (default 0.0).
        
    Returns:
        tuple: (North, East, Down)
    """
    n = x_b
    e = -y_b
    d = -z_b
    return (n, e, d)

def read_config(filename: str) -> Drone:
    """
    Read drone configuration from a CSV file. The CSV stores NED coordinates directly.
    
    Args:
        filename (str): Path to the config CSV file.
        
    Returns:
        Drone: Namedtuple with configuration data, or None if not found.
    """
    logger = logging.getLogger(__name__)
    try:
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    hw_id = int(row["hw_id"])
                    if hw_id == HW_ID:
                        pos_id = int(row["pos_id"])
                        # No transformation needed for config.csv (already in NED)
                        initial_x = float(row["x"])  # North
                        initial_y = float(row["y"])  # East
                        ip = row["ip"]
                        mavlink_port = int(row["mavlink_port"])
                        debug_port = int(row["debug_port"])
                        gcs_ip = row["gcs_ip"]
                        drone = Drone(hw_id, pos_id, initial_x, initial_y, ip, mavlink_port, debug_port, gcs_ip)
                        logger.info(f"Drone configuration found: {drone}")
                        return drone
                except ValueError as ve:
                    logger.error(f"Invalid data type in config file row: {row}. Error: {ve}")
            logger.error(f"No configuration found for HW_ID {HW_ID}.")
            return None
    except FileNotFoundError:
        logger.exception("Config file not found.")
        return None
    except Exception:
        logger.exception(f"Error reading config file {filename}")
        return None

def extract_initial_positions(first_waypoint: dict) -> tuple:
    """
    Extract the initial position (X, Y, Z in NED) from the first waypoint in the trajectory CSV.
    
    Args:
        first_waypoint (dict): First row from the CSV as a dictionary.
    
    Returns:
        tuple: (initial_x, initial_y, initial_z)
        
    Raises:
        KeyError or ValueError if the necessary keys or values are missing/invalid.
    """
    try:
        initial_x = float(first_waypoint["px"])
        initial_y = float(first_waypoint["py"])
        initial_z = float(first_waypoint.get("pz", 0.0))  # Default Z to 0.0 if not provided
        return initial_x, initial_y, initial_z
    except KeyError as ke:
        raise KeyError(f"Missing key in first waypoint: {ke}")
    except ValueError as ve:
        raise ValueError(f"Invalid value in first waypoint: {ve}")

def adjust_waypoints(waypoints: list, initial_x: float, initial_y: float, initial_z: float = 0.0) -> list:
    """
    Adjust all waypoints so that the trajectory starts at the origin (0,0,0) in NED coordinates.
    This is done by subtracting the initial position values from each waypoint's position.
    
    Args:
        waypoints (list): List of waypoint tuples.
        initial_x (float): X offset to subtract (North).
        initial_y (float): Y offset to subtract (East).
        initial_z (float): Z offset to subtract (Down).
        
    Returns:
        list: Adjusted list of waypoints.
    """
    adjusted_waypoints = []
    logger = logging.getLogger(__name__)
    for idx, waypoint in enumerate(waypoints):
        try:
            t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode, ledr, ledg, ledb = waypoint
            adjusted_px = px - initial_x
            adjusted_py = py - initial_y
            adjusted_pz = pz - initial_z
            adjusted_waypoints.append((t, adjusted_px, adjusted_py, adjusted_pz, vx, vy, vz, ax, ay, az, yaw, mode, ledr, ledg, ledb))
        except ValueError as ve:
            logger.error(f"Error adjusting waypoint at index {idx}: {ve}")
        except Exception as e:
            logger.error(f"Unexpected error adjusting waypoint at index {idx}: {e}")
    return adjusted_waypoints

def read_trajectory_file(filename: str, auto_launch_position: bool = False,
                           initial_x: float = 0.0, initial_y: float = 0.0) -> list:
    """
    Read and adjust trajectory waypoints from a CSV file.
    
    The CSV file is assumed to use a Blender-like coordinate system:
      - X = North, Y = West, Z = Up.
    It is first converted to NED (North, East, Down). If auto_launch_position is enabled,
    the initial waypoint's coordinates are used to re-center the trajectory (i.e. the first waypoint becomes 0,0,0).
    Otherwise, the configuration offsets (initial_x, initial_y) are subtracted.
    
    Args:
        filename (str): Path to the trajectory CSV file.
        auto_launch_position (bool): Whether to use the first waypoint for origin re-centering.
        initial_x (float): X offset from config (if auto_launch_position is False).
        initial_y (float): Y offset from config (if auto_launch_position is False).
        
    Returns:
        list: List of adjusted waypoints in NED.
    """
    logger = logging.getLogger(__name__)
    waypoints = []
    try:
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            rows = list(reader)
            if not rows:
                logger.error(f"Trajectory file '{filename}' is empty.")
                sys.exit(1)
            if auto_launch_position:
                try:
                    init_n, init_e, init_d = extract_initial_positions(rows[0])
                    logger.info(f"Auto Launch Position ENABLED. NED for first waypoint: (N={init_n:.2f}, E={init_e:.2f}, D={init_d:.2f})")
                except (KeyError, ValueError) as e:
                    logger.error(f"Failed to extract initial positions: {e}")
                    sys.exit(1)
                # Process each row in the CSV and convert values
                for idx, row in enumerate(rows):
                    try:
                        t = float(row["t"])
                        px = float(row["px"])
                        py = float(row["py"])
                        pz = float(row.get("pz", 0.0))
                        vx = float(row["vx"])
                        vy = float(row["vy"])
                        vz = float(row["vz"])
                        ax = float(row["ax"])
                        ay = float(row["ay"])
                        az = float(row["az"])
                        yaw = float(row["yaw"])
                        ledr = clamp_led_value(row.get("ledr", 0))
                        ledg = clamp_led_value(row.get("ledg", 0))
                        ledb = clamp_led_value(row.get("ledb", 0))
                        mode = row.get("mode", "0")
                        waypoints.append((t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode, ledr, ledg, ledb))
                    except ValueError as ve:
                        logger.error(f"Invalid data type in row {idx}: {row}. Error: {ve}")
                    except KeyError as ke:
                        logger.error(f"Missing key in row {idx}: {row}. Error: {ke}")
                # Adjust using the first waypoint as origin.
                waypoints = adjust_waypoints(waypoints, init_n, init_e, init_d)
                logger.info("Trajectory waypoints adjusted to start from NED (0, 0, 0).")
            else:
                # Use provided initial_x, initial_y from config; assume init_d = 0.0
                init_d = 0.0
                for idx, row in enumerate(rows):
                    try:
                        t = float(row["t"])
                        px = float(row["px"])
                        py = float(row["py"])
                        pz = float(row["pz"])
                        vx = float(row["vx"])
                        vy = float(row["vy"])
                        vz = float(row["vz"])
                        ax = float(row["ax"])
                        ay = float(row["ay"])
                        az = float(row["az"])
                        yaw = float(row["yaw"])
                        ledr = clamp_led_value(row.get("ledr", 0))
                        ledg = clamp_led_value(row.get("ledg", 0))
                        ledb = clamp_led_value(row.get("ledb", 0))
                        mode = row.get("mode", "0")
                        waypoints.append((t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode, ledr, ledg, ledb))
                    except ValueError as ve:
                        logger.error(f"Invalid data type in row {idx}: {row}. Error: {ve}")
                    except KeyError as ke:
                        logger.error(f"Missing key in row {idx}: {row}. Error: {ke}")
                logger.info(f"Trajectory file '{filename}' read successfully with {len(waypoints)} waypoints.")
                waypoints = adjust_waypoints(waypoints, initial_x, initial_y, init_d)
                logger.info(f"Trajectory waypoints adjusted using config initial positions (N={initial_x}, E={initial_y}, D={init_d}).")
    except FileNotFoundError:
        logger.exception(f"Trajectory file '{filename}' not found.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Error reading trajectory file '{filename}': {e}")
        sys.exit(1)
    return waypoints

# ----------------------------- #
#        Core Functionalities   #
# ----------------------------- #

async def perform_trajectory(drone: System, waypoints: list, home_position, start_time):
    """
    Execute the drone's trajectory with an initial climb phase and subsequent drift correction.
    
    During the initial climb phase (to avoid abrupt movements), drift correction is not applied.
    Once the climb phase is complete (based on altitude and time thresholds), the drone follows the
    trajectory while correcting for any time drift by skipping waypoints if necessary. Additionally,
    if the drone is ahead of schedule, the current setpoint is continuously re-sent to maintain offboard mode.
    
    Args:
        drone (System): MAVSDK drone system instance.
        waypoints (list): List of trajectory waypoints (tuples).
        home_position (dict): Home position telemetry data.
        start_time (float): Synchronized start time (UNIX timestamp).
    """
    global drift_delta
    global initial_position_drift
    logger = logging.getLogger(__name__)

    # Expert Parameters for Time-Drift Handling
    DRIFT_CATCHUP_MAX_SEC = 0.5      # Maximum time (seconds) for drift correction per iteration
    AHEAD_SLEEP_STEP_SEC = 0.1       # Sleep duration (seconds) when ahead of schedule

    # Basic Setup
    total_waypoints = len(waypoints)
    waypoint_index = 0
    landing_detected = False
    led_controller = LEDController.get_instance()

    # Initial Climb Phase Variables
    in_initial_climb = True
    initial_climb_completed = False   # Once set, the drone will not re-enter the climb phase
    initial_climb_start_time = time.time()  # Record when offboard/climb started
    initial_climb_yaw = None          # To store the chosen initial yaw during climb

    # Determine the time interval between waypoints from the CSV (CSV step)
    csv_step = waypoints[1][0] - waypoints[0][0] if total_waypoints > 1 else Params.DRIFT_CHECK_PERIOD

    # Determine final altitude (to decide landing mode)
    final_altitude = -waypoints[-1][3]  # Convert NED down value to altitude
    trajectory_ends_high = final_altitude > Params.GROUND_ALTITUDE_THRESHOLD

    logger.info(f"Trajectory ends {'high' if trajectory_ends_high else 'low'}. "
                f"{'PX4 landing' if trajectory_ends_high else 'Controlled landing'} will be used.")

    if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift is not None:
        logger.debug(f"Initial Position Correction enabled. Offsets - North: {initial_position_drift.north_m}, "
                     f"East: {initial_position_drift.east_m}, Down: {initial_position_drift.down_m}")

    # Main Trajectory Execution Loop
    while waypoint_index < total_waypoints:
        try:
            current_time = time.time()
            elapsed_time = current_time - start_time
            waypoint = waypoints[waypoint_index]
            t_wp = waypoint[0]
            drift_delta = elapsed_time - t_wp  # Positive if behind schedule, negative if ahead

            # --------------------------
            # CASE A: Behind schedule or on time (drift_delta >= 0)
            # --------------------------
            if drift_delta >= 0:
                # Destructure the waypoint values
                _, raw_px, raw_py, raw_pz, vx, vy, vz, ax, ay, az, raw_yaw, mode, ledr, ledg, ledb = waypoint

                # Apply initial position correction if enabled
                if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift is not None:
                    px = raw_px + initial_position_drift.north_m
                    py = raw_py + initial_position_drift.east_m
                    pz = raw_pz + initial_position_drift.down_m
                else:
                    px, py, pz = raw_px, raw_py, raw_pz

                # (1) Check if still in initial climb phase
                time_in_climb = time.time() - initial_climb_start_time
                if not initial_climb_completed:
                    actual_altitude = -pz  # Corrected altitude from NED
                    still_under_alt = actual_altitude < Params.INITIAL_CLIMB_ALTITUDE_THRESHOLD
                    still_under_time = time_in_climb < Params.INITIAL_CLIMB_TIME_THRESHOLD
                    in_initial_climb = still_under_alt or still_under_time
                    if not in_initial_climb:
                        initial_climb_completed = True
                else:
                    in_initial_climb = False

                # Update LED color to reflect current waypoint state
                led_controller.set_color(ledr, ledg, ledb)

                # (2) Initial Climb Branch: No drift correction during climb phase
                if in_initial_climb:
                    actual_altitude = -pz
                    # Determine the desired climb mode
                    if Params.INITIAL_CLIMB_MODE == "BODY_VELOCITY":
                        # Use body-frame velocity for climbing
                        vz_climb = vz if abs(vz) > 1e-6 else Params.INITIAL_CLIMB_VZ_DEFAULT
                        if initial_climb_yaw is None:
                            initial_climb_yaw = raw_yaw if isinstance(raw_yaw, float) else 0.0
                        velocity_body = VelocityBodyYawspeed(
                            forward_m_s=0.0,
                            right_m_s=0.0,
                            down_m_s=-vz_climb,  # Negative indicates upward motion
                            yawspeed_deg_s=0.0   # Maintain current heading
                        )
                        await drone.offboard.set_velocity_body(velocity_body)
                        logger.info(f"[Initial Climb - BODY] TimeInClimb={time_in_climb:.2f}s, "
                                    f"Alt={actual_altitude:.1f}m (<{Params.INITIAL_CLIMB_ALTITUDE_THRESHOLD}m), "
                                    f"ClimbSpeed={-vz_climb:.2f} m/s upward. (Drift correction NOT applied)")
                    else:
                        # Use local NED setpoint based on current telemetry yaw
                        if initial_climb_yaw is None:
                            yaw_deg = 0.0
                            try:
                                async for euler in drone.telemetry.attitude_euler():
                                    yaw_deg = euler.yaw_deg
                                    break
                            except Exception as ex:
                                logger.warning(f"Failed to get current yaw from telemetry, defaulting to 0.0 deg. Error: {ex}")
                            initial_climb_yaw = yaw_deg
                        position_setpoint = PositionNedYaw(px, py, pz, initial_climb_yaw)
                        await drone.offboard.set_position_ned(position_setpoint)
                        logger.info(f"[Initial Climb - LOCAL NED] TimeInClimb={time_in_climb:.2f}s, "
                                    f"Alt={actual_altitude:.1f}m (<{Params.INITIAL_CLIMB_ALTITUDE_THRESHOLD}m), "
                                    f"Using NED setpoint=({px:.2f}, {py:.2f}, {pz:.2f}), "
                                    f"Yaw={initial_climb_yaw:.2f} deg. (Drift correction NOT applied)")
                    waypoint_index += 1
                    continue  # Skip further processing during initial climb

                # (3) Normal Flight: Apply drift correction if not in climb phase
                safe_drift_delta = min(drift_delta, DRIFT_CATCHUP_MAX_SEC)
                skip_count = int(safe_drift_delta / csv_step)
                if skip_count > 0:
                    logger.debug(f"Behind schedule by {drift_delta:.2f}s. "
                                 f"Skipping approximately {skip_count} waypoint(s) (limit: {DRIFT_CATCHUP_MAX_SEC:.2f}s).")
                    waypoint_index += skip_count
                    if waypoint_index >= total_waypoints:
                        logger.warning("Waypoint index exceeded total waypoints; clamping to last waypoint.")
                        waypoint_index = total_waypoints - 1
                    waypoint = waypoints[waypoint_index]
                    t_wp = waypoint[0]
                    # Re-read the waypoint with updated index and apply correction
                    _, raw_px, raw_py, raw_pz, vx, vy, vz, ax, ay, az, raw_yaw, mode, ledr, ledg, ledb = waypoint
                    if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift is not None:
                        px = raw_px + initial_position_drift.north_m
                        py = raw_py + initial_position_drift.east_m
                        pz = raw_pz + initial_position_drift.down_m
                    else:
                        px, py, pz = raw_px, raw_py, raw_pz
                else:
                    logger.debug(f"Drift ({drift_delta:.2f}s) is within acceptable threshold; using current waypoint.")

                current_altitude_setpoint = -pz

                # (4) Issue the Normal Flight Setpoint Command
                position_setpoint = PositionNedYaw(px, py, pz, raw_yaw)
                # Log detailed information in debug mode or every 5th waypoint in summary mode
                if DEBUG_MODE or (waypoint_index % 5 == 0):
                    logger.info(f"Executing Normal WP {waypoint_index + 1}/{total_waypoints}: "
                                f"t={t_wp:.2f}s, Pos=({px:.2f}, {py:.2f}, {pz:.2f}) NED, Yaw={raw_yaw:.2f}°")
                led_controller.set_color(ledr, ledg, ledb)
                if Params.FEEDFORWARD_VELOCITY_ENABLED and Params.FEEDFORWARD_ACCELERATION_ENABLED:
                    velocity_setpoint = VelocityNedYaw(vx, vy, vz, raw_yaw)
                    acceleration_setpoint = AccelerationNed(ax, ay, az)
                    await drone.offboard.set_position_velocity_acceleration_ned(
                        position_setpoint, velocity_setpoint, acceleration_setpoint
                    )
                elif Params.FEEDFORWARD_VELOCITY_ENABLED:
                    velocity_setpoint = VelocityNedYaw(vx, vy, vz, raw_yaw)
                    await drone.offboard.set_position_velocity_ned(position_setpoint, velocity_setpoint)
                else:
                    await drone.offboard.set_position_ned(position_setpoint)

                # (5) Mission Progress Tracking & Landing Trigger
                time_to_end = waypoints[-1][0] - t_wp
                mission_progress = (waypoint_index + 1) / total_waypoints
                if DEBUG_MODE or (waypoint_index % 5 == 0):
                    logger.info(f"Progress: {mission_progress:.2%}, ETA: {time_to_end:.2f}s, Drift: {drift_delta:.2f}s")
                # Trigger landing if mission progress reaches threshold and conditions are met
                if (not trajectory_ends_high) and (mission_progress >= Params.MISSION_PROGRESS_THRESHOLD):
                    if (time_to_end <= Params.CONTROLLED_LANDING_TIME) or (current_altitude_setpoint < Params.CONTROLLED_LANDING_ALTITUDE):
                        logger.info("Initiating controlled landing due to mission progress or low altitude.")
                        await controlled_landing(drone)
                        landing_detected = True
                        break

                waypoint_index += 1

            # --------------------------
            # CASE B: Ahead of schedule (drift_delta < 0)
            # --------------------------
            else:
                # When ahead of schedule, continuously re-send the current setpoint command
                # to keep offboard mode active.
                _, raw_px, raw_py, raw_pz, vx, vy, vz, ax, ay, az, raw_yaw, mode, ledr, ledg, ledb = waypoint
                if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift is not None:
                    px = raw_px + initial_position_drift.north_m
                    py = raw_py + initial_position_drift.east_m
                    pz = raw_pz + initial_position_drift.down_m
                else:
                    px, py, pz = raw_px, raw_py, raw_pz

                position_setpoint = PositionNedYaw(px, py, pz, raw_yaw)
                logger.debug(f"Ahead of schedule by {abs(drift_delta):.2f}s. Re-sending current waypoint setpoint: "
                             f"t={t_wp:.2f}s, Pos=({px:.2f}, {py:.2f}, {pz:.2f}), Yaw={raw_yaw:.2f}°.")
                if Params.FEEDFORWARD_VELOCITY_ENABLED and Params.FEEDFORWARD_ACCELERATION_ENABLED:
                    velocity_setpoint = VelocityNedYaw(vx, vy, vz, raw_yaw)
                    acceleration_setpoint = AccelerationNed(ax, ay, az)
                    await drone.offboard.set_position_velocity_acceleration_ned(
                        position_setpoint, velocity_setpoint, acceleration_setpoint
                    )
                elif Params.FEEDFORWARD_VELOCITY_ENABLED:
                    velocity_setpoint = VelocityNedYaw(vx, vy, vz, raw_yaw)
                    await drone.offboard.set_position_velocity_ned(position_setpoint, velocity_setpoint)
                else:
                    await drone.offboard.set_position_ned(position_setpoint)

                # Determine a short sleep duration (to re-send the setpoint continuously)
                sleep_duration = t_wp - elapsed_time
                step_sleep = min(sleep_duration, AHEAD_SLEEP_STEP_SEC) if sleep_duration > 0 else AHEAD_SLEEP_STEP_SEC
                logger.debug(f"Sleeping for {step_sleep:.2f}s while ahead of schedule.")
                await asyncio.sleep(step_sleep)
                # Do not increment waypoint_index; the same waypoint will be used in the next iteration.

        except OffboardError as e:
            logger.error(f"Offboard error: {e}")
            led_controller.set_color(255, 0, 0)
            break
        except Exception:
            logger.exception("Unexpected error in trajectory execution.")
            led_controller.set_color(255, 0, 0)
            break

    # --------------------------
    # Post-Trajectory Landing Handling
    # --------------------------
    if not landing_detected:
        if trajectory_ends_high:
            logger.info("Initiating PX4 native landing...")
            await stop_offboard_mode(drone)
            await perform_landing(drone)
            await wait_for_landing(drone)
        else:
            logger.warning("Falling back to controlled landing at end of trajectory.")
            await controlled_landing(drone)

    logger.info("Mission complete.")
    led_controller.set_color(0, 255, 0)

async def controlled_landing(drone: System):
    """
    Perform controlled landing by sending descent commands and monitoring the landing state.
    
    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    logger.info("Initiating controlled landing.")
    led_controller = LEDController.get_instance()
    landing_detected = False
    landing_start_time = time.time()

    logger.info("Switching to controlled descent mode.")
    try:
        # Set descent setpoint and velocity for controlled landing.
        await drone.offboard.set_position_velocity_ned(
            PositionNedYaw(0.0, 0.0, 0.0, 0.0),
            VelocityNedYaw(0.0, 0.0, Params.CONTROLLED_DESCENT_SPEED, 0.0),
        )
    except OffboardError as e:
        logger.error(f"Offboard error during controlled landing setup: {e}")
        led_controller.set_color(255, 0, 0)
        return

    while not landing_detected:
        try:
            velocity_setpoint = VelocityNedYaw(0.0, 0.0, Params.CONTROLLED_DESCENT_SPEED, 0.0)
            await drone.offboard.set_velocity_ned(velocity_setpoint)
            logger.debug(f"Controlled Landing: Descending at {Params.CONTROLLED_DESCENT_SPEED:.2f} m/s.")
            async for landed_state in drone.telemetry.landed_state():
                if landed_state == LandedState.ON_GROUND:
                    landing_detected = True
                    logger.info("Landing detected during controlled landing.")
                    break
                break
            if (time.time() - landing_start_time) > Params.LANDING_TIMEOUT:
                logger.warning("Controlled landing timed out. Initiating PX4 native landing.")
                await stop_offboard_mode(drone)
                await perform_landing(drone)
                break
            await asyncio.sleep(0.1)
        except OffboardError as e:
            logger.error(f"Offboard error during controlled landing: {e}")
            led_controller.set_color(255, 0, 0)
            break
        except Exception:
            logger.exception("Unexpected error during controlled landing.")
            led_controller.set_color(255, 0, 0)
            break

    if landing_detected:
        await stop_offboard_mode(drone)
        await disarm_drone(drone)
    else:
        logger.warning("Landing not detected. Initiating PX4 native landing as fallback.")
        await stop_offboard_mode(drone)
        await perform_landing(drone)

    led_controller.set_color(0, 255, 0)

async def wait_for_landing(drone: System):
    """
    Wait for the drone to confirm landing after initiating the landing sequence.
    
    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    start_time = time.time()
    logger.info("Waiting for drone to confirm landing...")
    while True:
        async for landed_state in drone.telemetry.landed_state():
            if landed_state == LandedState.ON_GROUND:
                logger.info("Drone has landed successfully.")
                return
            break
        if time.time() - start_time > Params.LANDING_TIMEOUT:
            logger.error("Landing confirmation timed out.")
            break
        await asyncio.sleep(1)

@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(5))
async def initial_setup_and_connection():
    """
    Perform the initial setup and establish connection with the drone via MAVSDK.
    
    Returns:
        drone (System): Connected MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        led_controller = LEDController.get_instance()
        # Set LED to blue to indicate initialization phase.
        led_controller.set_color(0, 0, 255)
        logger.info("LED set to blue: Initialization in progress.")

        grpc_port = Params.DEFAULT_GRPC_PORT  # Fixed gRPC port for MAVSDK server
        mavsdk_server_address = "127.0.0.1"     # Assume local server

        drone = System(mavsdk_server_address=mavsdk_server_address, port=grpc_port)
        await drone.connect(system_address=f"udp://:{Params.mavsdk_port}")

        logger.info(f"Connecting to drone via MAVSDK server at {mavsdk_server_address}:{grpc_port} on UDP port {Params.mavsdk_port}.")

        # Wait for the connection to be established (with a timeout)
        start_time = time.time()
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(f"Drone connected via MAVSDK server at {mavsdk_server_address}:{grpc_port}.")
                break
            if time.time() - start_time > 10:
                logger.error("Timeout while waiting for drone connection.")
                led_controller.set_color(255, 0, 0)
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        logger.info("Initial setup and connection successful.")
        return drone
    except Exception:
        logger.exception("Error during initial setup and connection.")
        led_controller.set_color(255, 0, 0)
        raise

async def pre_flight_checks(drone: System):
    """
    Perform pre-flight checks to verify the drone's readiness, including health checks and GPS origin retrieval.
    
    The procedure involves:
      1. Waiting for the global and home position health checks to pass (with a timeout).
      2. Retrieving the GPS global origin. If the primary request fails, a fallback using a single
         position update is attempted.
    
    Args:
        drone (System): MAVSDK drone system instance.
    
    Returns:
        dict: GPS global origin containing latitude, longitude, and altitude.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting pre-flight checks.")

    led_controller = LEDController.get_instance()
    # Set LED to yellow to indicate that pre-flight checks are in progress.
    led_controller.set_color(255, 255, 0)

    start_time = time.time()
    gps_origin = None
    health_checks_passed = False

    try:
        if Params.REQUIRE_GLOBAL_POSITION:
            logger.info("Waiting for health checks...")
            async for health in drone.telemetry.health():
                # Check for timeout during health verification
                if time.time() - start_time > Params.PRE_FLIGHT_TIMEOUT:
                    logger.error("Pre-flight checks timed out during health verification")
                    led_controller.set_color(255, 0, 0)
                    raise TimeoutError("Health check phase timed out")
                if health.is_global_position_ok and health.is_home_position_ok:
                    logger.info("Global position and home position checks passed")
                    health_checks_passed = True
                    break
                # Log any missing requirements
                if not health.is_global_position_ok:
                    logger.warning("Waiting for global position estimate...")
                if not health.is_home_position_ok:
                    logger.warning("Waiting for home position initialization...")
                await asyncio.sleep(1)
            if not health_checks_passed:
                raise RuntimeError("Failed to pass health checks")

            # Attempt to retrieve GPS origin; use fallback if necessary.
            try:
                origin = await drone.telemetry.get_gps_global_origin()
                gps_origin = {
                    'latitude': origin.latitude_deg,
                    'longitude': origin.longitude_deg,
                    'altitude': origin.altitude_m
                }
                logger.info(f"Retrieved GPS global origin: {gps_origin}")
            except mavsdk.telemetry.TelemetryError as e:
                logger.warning(f"GPS origin request failed: {e}, using fallback...")
                async for position in drone.telemetry.position():
                    gps_origin = {
                        'latitude': position.latitude_deg,
                        'longitude': position.longitude_deg,
                        'altitude': position.absolute_altitude_m
                    }
                    logger.info(f"Using fallback position: {gps_origin}")
                    break
            if not gps_origin:
                logger.error("Failed to obtain GPS origin")
                led_controller.set_color(255, 0, 0)
                raise ValueError("No GPS origin available")
            logger.info("Pre-flight checks completed successfully")
            led_controller.set_color(0, 255, 0)  # Set LED to green on success
            return gps_origin
        else:
            logger.info("Skipping global position check per configuration")
            led_controller.set_color(0, 255, 0)
            return None
    except Exception as e:
        logger.exception("Critical error in pre-flight checks")
        led_controller.set_color(255, 0, 0)
        raise

@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(2))
async def arming_and_starting_offboard_mode(drone: System, home_position: dict):
    """
    Arm the drone and start offboard mode, while computing the initial position offset in NED coordinates.
    
    The procedure involves:
      1. Computing the initial position drift (if required) using local position data.
      2. Setting the drone to a safe Hold mode.
      3. Arming the drone.
      4. Setting an initial offboard velocity setpoint.
      5. Starting offboard mode.
    
    Args:
        drone (System): MAVSDK drone system instance.
        home_position (dict): Home position telemetry data in global coordinates.
    
    Returns:
        None
    """
    logger = logging.getLogger(__name__)
    try:
        led_controller = LEDController.get_instance()
        led_controller.set_color(0, 255, 0)  # Green indicates arming is in progress
        logger.info("LED set to green: Arming in progress.")

        global initial_position_drift
        if Params.REQUIRE_GLOBAL_POSITION and home_position:
            logger.info("Computing initial position offset in NED coordinates.")
            initial_position_drift = await compute_position_drift()
            logger.info(f"Initial position drift computed: {initial_position_drift}")
        else:
            logger.info("Skipping position offset computation (global position check disabled or no home position).")

        logger.info("Setting Hold flight mode.")
        await drone.action.hold()

        logger.info("Arming the drone.")
        await drone.action.arm()

        logger.info("Setting initial velocity setpoint for offboard mode.")
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))

        logger.info("Starting offboard mode.")
        await drone.offboard.start()

        led_controller.set_color(255, 255, 255)  # White indicates readiness to fly
        logger.info("LED set to white: Drone is ready to fly.")
    except OffboardError as error:
        logger.error(f"Offboard error encountered: {error}")
        await drone.action.disarm()
        led_controller.set_color(255, 0, 0)
        raise
    except Exception as e:
        logger.exception("Unexpected error during arming and starting offboard mode.")
        await drone.action.disarm()
        led_controller.set_color(255, 0, 0)
        raise e

async def compute_position_drift():
    """
    Compute the initial position drift using the drone's local NED position data.
    The NED origin is set automatically when the drone arms (it matches GPS_GLOBAL_ORIGIN).
    
    Returns:
        PositionNedYaw: Drift offset in NED coordinates, or None if unavailable.
    """
    logger = logging.getLogger(__name__)
    default_drift = PositionNedYaw(0.0, 0.0, 0.0, 0.0)  # Default: no drift
    try:
        response = requests.get(f"http://localhost:{Params.drones_flask_port}/get-local-position-ned", timeout=2)
        if response.status_code == 200:
            ned_data = response.json()
            drift = PositionNedYaw(
                north_m=ned_data['x'],
                east_m=ned_data['y'],
                down_m=ned_data['z'],
                yaw_deg=0.0  # Yaw is set to 0 if not needed
            )
            logger.info(f"Initial NED drift from origin: {drift}")
            return drift
        else:
            logger.warning(f"Failed to get NED data: HTTP {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API connection failed: {str(e)}")
        return None
    except KeyError as e:
        logger.error(f"Malformed NED data: Missing field {str(e)}")
        return None

async def perform_landing(drone: System):
    """
    Perform landing for the drone.
    
    This function commands the drone to land and waits until landing is confirmed.
    
    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Initiating landing.")
        await drone.action.land()

        start_time = time.time()
        # Wait for the drone to confirm landing (or timeout)
        while True:
            async for landed_state in drone.telemetry.landed_state():
                if landed_state == LandedState.ON_GROUND:
                    logger.info("Drone has landed successfully.")
                    return
                break
            if time.time() - start_time > Params.LANDING_TIMEOUT:
                logger.error("Landing confirmation timed out.")
                break
            await asyncio.sleep(1)
    except ActionError as e:
        logger.error(f"Action error during landing: {e}")
    except Exception:
        logger.exception("Unexpected error during landing.")

async def stop_offboard_mode(drone: System):
    """
    Stop offboard mode for the drone.
    
    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Stopping offboard mode.")
        await drone.offboard.stop()
    except OffboardError as error:
        logger.error(f"Error stopping offboard mode: {error}")
    except Exception:
        logger.exception("Unexpected error stopping offboard mode.")

async def disarm_drone(drone: System):
    """
    Disarm the drone.
    
    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Disarming drone.")
        await drone.action.disarm()
        led_controller = LEDController.get_instance()
        led_controller.set_color(255, 0, 0)  # Set LED to red to indicate disarm status
        logger.info("LED set to red: Drone disarmed.")
    except ActionError as e:
        logger.error(f"Error disarming drone: {e}")
    except Exception:
        logger.exception("Unexpected error disarming drone.")

# ----------------------------- #
#       MAVSDK Server Control   #
# ----------------------------- #

def get_mavsdk_server_path():
    """
    Constructs the absolute path to the mavsdk_server executable.
    
    Returns:
        str: The full path to mavsdk_server.
    """
    home_dir = os.path.expanduser("~")
    mavsdk_drone_show_dir = os.path.join(home_dir, "mavsdk_drone_show")
    mavsdk_server_path = os.path.join(mavsdk_drone_show_dir, "mavsdk_server")
    return mavsdk_server_path

def start_mavsdk_server(udp_port: int):
    """
    Start the MAVSDK server as a subprocess.
    
    This function checks if an instance is already running (and terminates it if so),
    sets the proper executable permissions if necessary, and starts a new instance.
    
    Args:
        udp_port (int): UDP port for MAVSDK server communication.
        
    Returns:
        subprocess.Popen: The MAVSDK server subprocess if successfully started, else None.
    """
    logger = logging.getLogger(__name__)
    try:
        is_running, pid = check_mavsdk_server_running(Params.DEFAULT_GRPC_PORT)
        if is_running:
            logger.info(f"MAVSDK server already running on port {Params.DEFAULT_GRPC_PORT}. Terminating existing server (PID: {pid})...")
            try:
                psutil.Process(pid).terminate()
                psutil.Process(pid).wait(timeout=5)
                logger.info(f"Terminated existing MAVSDK server with PID: {pid}.")
            except psutil.NoSuchProcess:
                logger.warning(f"No process found with PID: {pid} to terminate.")
            except psutil.TimeoutExpired:
                logger.warning(f"Process with PID: {pid} did not terminate gracefully. Killing it.")
                psutil.Process(pid).kill()
                psutil.Process(pid).wait()
                logger.info(f"Killed MAVSDK server with PID: {pid}.")

        mavsdk_server_path = get_mavsdk_server_path()
        logger.debug(f"Constructed MAVSDK server path: {mavsdk_server_path}")

        if not os.path.isfile(mavsdk_server_path):
            logger.error(f"mavsdk_server executable not found at '{mavsdk_server_path}'.")
            sys.exit(1)
        if not os.access(mavsdk_server_path, os.X_OK):
            logger.info(f"Setting executable permissions for '{mavsdk_server_path}'.")
            os.chmod(mavsdk_server_path, 0o755)

        # Start the MAVSDK server with the specified UDP port.
        mavsdk_server = subprocess.Popen(
            [mavsdk_server_path, "-p", str(Params.DEFAULT_GRPC_PORT), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(f"MAVSDK server started with gRPC port {Params.DEFAULT_GRPC_PORT} and UDP port {udp_port}.")
        asyncio.create_task(log_mavsdk_output(mavsdk_server))
        # Wait until the server starts listening on the gRPC port.
        if not wait_for_port(Params.DEFAULT_GRPC_PORT, timeout=Params.PRE_FLIGHT_TIMEOUT):
            logger.error(f"MAVSDK server did not start listening on port {Params.DEFAULT_GRPC_PORT} within timeout.")
            mavsdk_server.terminate()
            return None
        logger.info("MAVSDK server is now listening on gRPC port.")
        return mavsdk_server
    except FileNotFoundError:
        logger.error("mavsdk_server executable not found. Ensure it is present in the specified directory.")
        return None
    except Exception:
        logger.exception("Error starting MAVSDK server.")
        return None

def check_mavsdk_server_running(port):
    """
    Check if the MAVSDK server is running on the specified gRPC port.
    
    Args:
        port (int): The gRPC port to check.
        
    Returns:
        tuple: (is_running (bool), pid (int or None))
    """
    logger = logging.getLogger(__name__)
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            for conn in proc.net_connections(kind="inet"):
                if conn.laddr.port == port:
                    return True, proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def wait_for_port(port, host="localhost", timeout=Params.PRE_FLIGHT_TIMEOUT):
    """
    Wait until a TCP port is accepting connections.
    
    Args:
        port (int): The port to check.
        host (str): The hostname (default: localhost).
        timeout (float): Maximum time to wait in seconds.
        
    Returns:
        bool: True if the port is open within timeout, otherwise False.
    """
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            if time.time() - start_time >= timeout:
                return False
            time.sleep(0.1)

async def log_mavsdk_output(mavsdk_server):
    """
    Asynchronously log the MAVSDK server's stdout and stderr.
    
    Args:
        mavsdk_server (subprocess.Popen): The MAVSDK server subprocess.
    """
    logger = logging.getLogger(__name__)
    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stdout.readline)
            if not line:
                break
            logger.debug(f"MAVSDK Server: {line.decode().strip()}")
    except Exception:
        logger.exception("Error while reading MAVSDK server stdout.")
    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stderr.readline)
            if not line:
                break
            logger.error(f"MAVSDK Server Error: {line.decode().strip()}")
    except Exception:
        logger.exception("Error while reading MAVSDK server stderr.")

def stop_mavsdk_server(mavsdk_server):
    """
    Stop the MAVSDK server subprocess.
    
    Args:
        mavsdk_server (subprocess.Popen): The MAVSDK server subprocess.
    """
    logger = logging.getLogger(__name__)
    try:
        if mavsdk_server.poll() is None:
            logger.info("Stopping MAVSDK server...")
            mavsdk_server.terminate()
            try:
                mavsdk_server.wait(timeout=5)
                logger.info("MAVSDK server terminated gracefully.")
            except subprocess.TimeoutExpired:
                logger.warning("MAVSDK server did not terminate gracefully. Killing it.")
                mavsdk_server.kill()
                mavsdk_server.wait()
                logger.info("MAVSDK server killed forcefully.")
        else:
            logger.debug("MAVSDK server has already terminated.")
    except Exception:
        logger.exception("Error stopping MAVSDK server.")

# ----------------------------- #
#         Main Drone Runner     #
# ----------------------------- #

async def run_drone(synchronized_start_time, custom_csv=None, auto_launch_position=False):
    """
    Main function to run the drone's mission.
    
    Steps:
      1. Start the MAVSDK server.
      2. Perform initial setup and connect to the drone.
      3. Conduct pre-flight checks.
      4. Synchronize start time.
      5. Arm the drone and start offboard mode.
      6. Read and adjust the trajectory waypoints.
      7. Execute the trajectory (including handling drift and landing).
    
    Args:
        synchronized_start_time (float): Synchronized start time (UNIX timestamp).
        custom_csv (str): Custom trajectory CSV filename (if provided).
        auto_launch_position (bool): Flag to enable auto extraction of the initial position from the CSV.
    """
    logger = logging.getLogger(__name__)
    mavsdk_server = None
    try:
        global HW_ID

        # Step 1: Start MAVSDK Server
        udp_port = Params.mavsdk_port
        mavsdk_server = start_mavsdk_server(udp_port)
        if mavsdk_server is None:
            logger.error("Failed to start MAVSDK server. Exiting program.")
            sys.exit(1)
        await asyncio.sleep(2)  # Brief wait for server initialization

        # Step 2: Initial Setup and Connection
        drone = await initial_setup_and_connection()

        # Step 3: Pre-flight Checks
        home_position = await pre_flight_checks(drone)

        # Step 4: Handle Synchronized Start Time
        if synchronized_start_time is None:
            synchronized_start_time = time.time()  # Use current time if not provided
            logger.info(f"No synchronized start time provided. Using current time: {time.ctime(synchronized_start_time)}.")
        current_time = time.time()
        if synchronized_start_time > current_time:
            sleep_duration = synchronized_start_time - current_time
            logger.info(f"Waiting {sleep_duration:.2f}s until synchronized start time.")
            await asyncio.sleep(sleep_duration)
        elif synchronized_start_time < current_time:
            logger.warning(f"Synchronized start time was {current_time - synchronized_start_time:.2f}s ago.")
        else:
            logger.info("Synchronized start time is now.")

        # Step 5: Arm and Start Offboard Mode
        await arming_and_starting_offboard_mode(drone, home_position)

        # Step 6: Read and Adjust Trajectory Waypoints
        if custom_csv:
            # Use custom CSV file if provided.
            trajectory_filename = os.path.join('shapes_sitl' if Params.sim_mode else 'shapes', custom_csv)
            waypoints = read_trajectory_file(filename=trajectory_filename, auto_launch_position=auto_launch_position)
            logger.info(f"Custom trajectory file '{custom_csv}' loaded successfully.")
        else:
            # Drone Show mode: read HW_ID and configuration from CSV.
            HW_ID = read_hw_id()
            if HW_ID is None:
                logger.error("Failed to read HW ID. Exiting program.")
                sys.exit(1)
            drone_config = read_config(CONFIG_CSV_NAME)
            if drone_config is None:
                logger.error("Drone configuration not found. Exiting program.")
                sys.exit(1)
            position_id = drone_config.pos_id
            trajectory_filename = os.path.join(
                'shapes_sitl' if Params.sim_mode else 'shapes',
                'swarm',
                'processed',
                f"Drone {position_id}.csv"
            )
            waypoints = read_trajectory_file(filename=trajectory_filename, auto_launch_position=auto_launch_position,
                                             initial_x=drone_config.initial_x, initial_y=drone_config.initial_y)
            logger.info(f"Drone show trajectory file 'Drone {position_id}.csv' loaded successfully.")

        # Log initial position details based on auto_launch_position setting.
        if auto_launch_position:
            logger.info("Auto Launch Position is ENABLED. Waypoints will be re-centered so the first waypoint becomes (0,0,0) in NED.")
        else:
            logger.info(f"Auto Launch Position is DISABLED. Initial Position from Config: X={drone_config.initial_x}, Y={drone_config.initial_y}, Z=0.0 (NED)")

        # Step 7: Execute Trajectory
        await perform_trajectory(drone, waypoints, home_position, synchronized_start_time)

        logger.info("Drone mission completed successfully.")
        sys.exit(0)
    except Exception:
        logger.exception("Error running drone.")
        sys.exit(1)
    finally:
        if mavsdk_server:
            stop_mavsdk_server(mavsdk_server)

# ----------------------------- #
#             Main              #
# ----------------------------- #

def main():
    """
    Main entry point for the drone show script.
    
    This function parses command-line arguments, configures logging (based on the --debug flag),
    and initiates the drone mission by calling run_drone().
    """
    # Configure logging (this function is assumed to set up logging formatting, etc.)
    configure_logging()
    logger = logging.getLogger(__name__)
    parser = argparse.ArgumentParser(description='Drone Show Script')
    parser.add_argument('--start_time', type=float, help='Synchronized start UNIX time')
    parser.add_argument('--custom_csv', type=str, help='Name of the custom trajectory CSV file, e.g., active.csv')
    parser.add_argument('--auto_launch_position', type=str2bool, nargs='?', const=True, default=None,
                        help='Explicitly enable (True) or disable (False) automated initial position extraction from trajectory CSV.')
    parser.add_argument('--debug', action='store_true', help='Enable detailed debug logging.')
    args = parser.parse_args()

    # Adjust logging level based on the --debug flag.
    global DEBUG_MODE
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        DEBUG_MODE = True
        logger.debug("Debug mode ENABLED: Detailed logging is active.")
    else:
        logging.getLogger().setLevel(logging.INFO)
        DEBUG_MODE = False
        logger.info("Debug mode DISABLED: Standard logging level set to INFO.")

    # Determine the synchronized start time.
    if args.start_time:
        synchronized_start_time = args.start_time
        formatted_time = time.ctime(synchronized_start_time)
        logger.info(f"Synchronized start time provided: {formatted_time}.")
    else:
        synchronized_start_time = time.time()
        formatted_time = time.ctime(synchronized_start_time)
        logger.info(f"No synchronized start time provided. Using current time: {formatted_time}.")

    global global_synchronized_start_time
    global_synchronized_start_time = synchronized_start_time

    # Determine if auto launch position is enabled.
    if args.auto_launch_position is not None:
        auto_launch_position = args.auto_launch_position
        logger.info(f"Command-line argument '--auto_launch_position' set to {auto_launch_position}.")
    else:
        auto_launch_position = Params.AUTO_LAUNCH_POSITION
        logger.info(f"Using Params.AUTO_LAUNCH_POSITION = {Params.AUTO_LAUNCH_POSITION} as '--auto_launch_position' was not provided.")

    # Log initial position configuration.
    if auto_launch_position:
        logger.info("Initial Position: Auto Launch Position is ENABLED. Waypoints will be re-centered so the first waypoint becomes (0,0,0) in NED.")
    else:
        logger.info("Initial Position: Auto Launch Position is DISABLED. Positions will be shifted by config's initial_x and initial_y in NED.")

    try:
        asyncio.run(run_drone(synchronized_start_time, custom_csv=args.custom_csv, auto_launch_position=auto_launch_position))
    except Exception:
        logger.exception("Unhandled exception in main.")
        sys.exit(1)

if __name__ == "__main__":
    main()
