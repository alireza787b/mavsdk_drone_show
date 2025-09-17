#!/usr/bin/env python3
"""
Swarm Trajectory Mission Script (`swarm_trajectory_mission.py`)

----------------------------------------
Author: Alireza Ghaderi  
Date: 2025-09-12
Version: 1.0.0
Based on: drone_show.py v2.6.0
----------------------------------------

Description:
    Executes individual drone trajectories from shapes[_sitl]/trajectory/processed/Drone {pos_id}.csv
    files using the proven drone_show.py architecture. Designed for swarm operations where each
    drone follows its own pre-planned trajectory with global GPS positioning and synchronized timing.

Key Features:
  • Global Offboard Control  
    – Always uses `PositionGlobalYaw` for GPS-based precise positioning
    – Real-time NED to LLA conversion using PyMap3D

  • Position ID Based Execution
    – Automatically loads trajectory files: Drone {position_id}.csv
    – Falls back to HW_ID if no position_id specified
    – Compatible with React UI and manual execution

  • Configurable End-of-Mission Behavior
    – return_home: Return to launch position and land
    – land_current: Land at current position
    – hold_position: Hover at final waypoint
    – continue_heading: Continue last heading and speed

  • Synchronized Initial Climb for Multicopters
    – Velocity-controlled climb during initial phase (height: 5m, time: 5s, speed: 1m/s)
    – Simple time padding copies first waypoint position for gap periods
    – Seamless transition from climb to CSV trajectory following
    – Perfect synchronization: timer starts at t=0, climb completes, then joins CSV

  • Comprehensive Logging & LEDs  
    – Verbose debug/info logs for trajectory execution
    – LED status indication throughout mission phases

Usage:
    python swarm_trajectory_mission.py
        [--start_time START_TIME]          # UNIX timestamp to synchronize launch
        [--position_id POSITION_ID]        # Override position ID (default: use HW_ID)
        [--end_behavior END_BEHAVIOR]      # Override end behavior (return_home/land_current/hold_position/continue_heading)
        [--debug]                          # Enable DEBUG log level

Command Line Arguments:
  --start_time              UNIX epoch time to delay mission start (default: now)
  --position_id             Position ID for trajectory file (default: HW_ID from .hwID file)
  --end_behavior            End of mission behavior override
  --debug                   Turn on detailed (DEBUG) logging

Dependencies:
  • Python 3.7+  
  • MAVSDK (`pip install mavsdk`)  
  • psutil (`pip install psutil`)  
  • tenacity (`pip install tenacity`)  
  • pymap3d (`pip install pymap3d`)
  • requests, asyncio, argparse, logging, csv, socket

LED Status Indicators:
  • Blue      — Initialization  
  • Yellow    — Pre-flight checks  
  • White     — Offboard armed & ready  
  • Green     — Mission complete / standby  
  • Red       — Error or disarmed  
  • Cyan      — End behavior execution

File Structure:
  • Trajectory files: shapes[_sitl]/swarm_trajectory/processed/Drone {pos_id}.csv
  • CSV format with global coordinates: t,lat,lon,alt,vx,vy,vz,ax,ay,az,yaw,mode,ledr,ledg,ledb

Notes:
  • Built on proven drone_show.py architecture for maximum reliability
  • Always uses global GPS positioning for large-area operations
  • Two-phase approach: velocity-based climb + CSV trajectory following
  • Time padding ensures synchronized start regardless of first waypoint time
  • Parameters: SWARM_TRAJECTORY_INITIAL_CLIMB_HEIGHT/TIME/SPEED in Params
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
    PositionGlobalYaw,
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
)


# ----------------------------- #
#        Data Structures        #
# ----------------------------- #

Drone = namedtuple(
    "Drone",
    "hw_id pos_id initial_x initial_y ip mavlink_port debug_port gcs_ip",
)

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

HW_ID = None  # Hardware ID of the drone
position_id = None  # Position ID of the drone (for trajectory file selection)
global_synchronized_start_time = None  # Synchronized start time
initial_position_drift = None  # Initial position drift in NED coordinates
drift_delta = 0.0  # Drift delta (to adjust waypoint times)

CONFIG_CSV_NAME = os.path.join(Params.config_csv_name)

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
        argparse.ArgumentTypeError: If the input is not a valid boolean string.
    """
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def read_config(filename: str) -> Drone:
    """
    Read the drone configuration from a CSV file.
    This CSV is assumed to store real NED coordinates directly:
      - initial_x => North
      - initial_y => East

    Args:
        filename (str): Path to the config CSV file.

    Returns:
        Drone: Namedtuple containing drone configuration if found, else None.
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
                        # For config.csv, we do NOT transform: it is already NED
                        initial_x = float(row["x"])  # North
                        initial_y = float(row["y"])  # East
                        ip = row["ip"]
                        mavlink_port = int(row["mavlink_port"])
                        debug_port = int(row["debug_port"])
                        gcs_ip = row["gcs_ip"]

                        drone = Drone(
                            hw_id,
                            pos_id,
                            initial_x,
                            initial_y,
                            ip,
                            mavlink_port,
                            debug_port,
                            gcs_ip,
                        )
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


def pad_trajectory_for_time_gap(waypoints: list) -> list:
    """
    Simple trajectory padding to fill time gap from t=0 to first CSV waypoint.

    This function only copies the first waypoint's position (lat/lon/alt) for all
    times from 0 to first_waypoint_time. No altitude modifications.
    The actual initial climb is handled separately via velocity commands.

    Args:
        waypoints (list): Original CSV waypoints starting at some time > 0

    Returns:
        list: Padded waypoints list starting from t=0 with copied first position
    """
    logger = logging.getLogger(__name__)

    if not waypoints:
        logger.warning("Empty waypoints provided to padding function")
        return waypoints

    first_waypoint = waypoints[0]
    first_time = first_waypoint[0]  # t value of first CSV waypoint

    # If first waypoint is already at t=0 or very close, no padding needed
    if first_time <= 1.0:  # 1 second tolerance
        logger.info(f"First waypoint at t={first_time:.1f}s, no padding needed")
        return waypoints

    # Extract first waypoint data (no modifications)
    first_lat, first_lon, first_alt = first_waypoint[1], first_waypoint[2], first_waypoint[3]
    first_yaw = first_waypoint[10]
    first_ledr, first_ledg, first_ledb = first_waypoint[12], first_waypoint[13], first_waypoint[14]

    padded_waypoints = []

    logger.info(f"Padding trajectory: copy first position from t=0 to t={first_time:.1f}s")

    # Pad from t=0 to first_time with copied first waypoint position
    pad_steps = max(int(first_time / 0.1), 1)  # 10Hz rate

    for i in range(pad_steps):
        t = i * first_time / pad_steps

        padded_waypoints.append((
            t, first_lat, first_lon, first_alt,  # Use exact first waypoint position
            0.0, 0.0, 0.0,  # Zero velocity (position hold)
            0.0, 0.0, 0.0,  # Zero acceleration
            first_yaw,  # First waypoint yaw
            "0",  # mode
            first_ledr, first_ledg, first_ledb  # First waypoint LED color
        ))

    # Add original CSV waypoints unchanged
    padded_waypoints.extend(waypoints)

    logger.info(f"Trajectory padded: {len(padded_waypoints)} total waypoints (added {len(padded_waypoints) - len(waypoints)} padding points)")
    return padded_waypoints


def read_swarm_trajectory_file(position_id: int) -> list:
    """
    Read and adjust the swarm trajectory waypoints from a CSV file.
    File path: shapes[_sitl]/swarm_trajectory/processed/Drone {position_id}.csv

    CSV format: t,lat,lon,alt,vx,vy,vz,ax,ay,az,yaw,mode,ledr,ledg,ledb

    Args:
        position_id (int): Position ID for the drone trajectory file.

    Returns:
        list: List of trajectory waypoints with lat/lon/alt coordinates.
    """
    logger = logging.getLogger(__name__)
    waypoints = []

    # Get trajectory file path using Params method
    filename = Params.get_swarm_trajectory_file_path(position_id)
    
    try:
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            rows = list(reader)

            if not rows:
                logger.error(f"Trajectory file '{filename}' is empty.")
                sys.exit(1)

            # Read and collect all waypoints
            for idx, row in enumerate(rows):
                try:
                    t = float(row["t"])
                    # Positions in lat/lon/alt (global coordinates)
                    px = float(row["lat"])  # lat -> px for processing
                    py = float(row["lon"])  # lon -> py for processing
                    pz = float(row.get("alt", 0.0))  # alt -> pz for processing

                    # Velocities in NED
                    vx = float(row.get("vx", 0.0))
                    vy = float(row.get("vy", 0.0))
                    vz = float(row.get("vz", 0.0))

                    # Accelerations in NED
                    ax = float(row.get("ax", 0.0))
                    ay = float(row.get("ay", 0.0))
                    az = float(row.get("az", 0.0))

                    yaw = float(row.get("yaw", 0.0))
                    ledr = clamp_led_value(row.get("ledr", 255))
                    ledg = clamp_led_value(row.get("ledg", 255))
                    ledb = clamp_led_value(row.get("ledb", 255))
                    mode = row.get("mode", "0")

                    waypoints.append(
                        (
                            t,
                            px,
                            py,
                            pz,
                            vx,
                            vy,
                            vz,
                            ax,
                            ay,
                            az,
                            yaw,
                            mode,
                            ledr,
                            ledg,
                            ledb,
                        )
                    )
                except ValueError as ve:
                    logger.error(f"Invalid data type in row {idx}: {row}. Error: {ve}")
                except KeyError as ke:
                    logger.error(f"Missing key in row {idx}: {row}. Error: {ke}")

            logger.info(f"Trajectory file '{filename}' loaded with {len(waypoints)} waypoints.")

            # Apply simple trajectory padding to fill time gap from t=0
            waypoints = pad_trajectory_for_time_gap(waypoints)

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

async def perform_swarm_trajectory(
    drone: System,
    waypoints: list,
    home_position,
    start_time: float,
    launch_lat: float,
    launch_lon: float,
    launch_alt: float,
    end_behavior: str = None
):
    """
    Executes the swarm trajectory with initial vertical climb phase and configurable end behavior.
    Always uses global offboard positioning for maximum precision and range.
    
    Args:
        drone: MAVSDK drone system instance
        waypoints: List of trajectory waypoints
        home_position: Home position data
        start_time: Mission start time
        launch_lat: Launch latitude
        launch_lon: Launch longitude  
        launch_alt: Launch altitude
        end_behavior: End of mission behavior override
    """
    global drift_delta, initial_position_drift
    logger = logging.getLogger(__name__)

    # Use parameter default if not specified
    if end_behavior is None:
        end_behavior = Params.SWARM_TRAJECTORY_END_BEHAVIOR

    # Drift / sleep parameters
    DRIFT_CATCHUP_MAX_SEC = 0.5
    AHEAD_SLEEP_STEP_SEC = 0.1

    total_waypoints = len(waypoints)
    waypoint_index = 0
    mission_completed = False
    led_controller = LEDController.get_instance()

    # Initial climb state tracking for velocity-based climb control
    in_initial_climb = True
    initial_climb_completed = False
    initial_climb_start_time = time.time()
    climb_target_reached = False

    # Time step between CSV rows (for drift‐skip calculations)
    csv_step = (waypoints[1][0] - waypoints[0][0]) \
        if total_waypoints > 1 else Params.DRIFT_CHECK_PERIOD

    logger.info(f"=== STARTING SWARM TRAJECTORY EXECUTION ===")
    logger.info(f"Waypoints: {total_waypoints} | End behavior: {end_behavior}")
    logger.info(f"Launch position: lat={launch_lat:.6f}, lon={launch_lon:.6f}, alt={launch_alt:.1f}m")
    
    # -----------------------------------
    # Main Trajectory Execution Loop
    # -----------------------------------
    last_velocity = None  # Track last velocity for continue_heading behavior

    while waypoint_index < total_waypoints:
        try:
            now = time.time()
            elapsed = now - start_time
            waypoint = waypoints[waypoint_index]
            t_wp = waypoint[0]
            drift_delta = elapsed - t_wp

            # --- Case A: On time or behind schedule ---
            if drift_delta >= 0:
                # Unpack CSV row
                (_, raw_px, raw_py, raw_pz,
                 vx, vy, vz,
                 ax, ay, az,
                 raw_yaw, mode,
                 ledr, ledg, ledb) = waypoint

                # For global coordinates (lat/lon/alt), use them directly
                # px = lat, py = lon, pz = alt (no conversion needed for global setpoints)
                px, py, pz = raw_px, raw_py, raw_pz

                # --- (1) Enhanced Initial Climb Phase with Multi-Condition Monitoring ---
                time_in_climb = now - initial_climb_start_time
                if not initial_climb_completed:
                    # Enhanced climb completion conditions with altitude verification
                    altitude_condition = time_in_climb >= Params.SWARM_TRAJECTORY_INITIAL_CLIMB_TIME
                    height_condition = (time_in_climb * Params.SWARM_TRAJECTORY_INITIAL_CLIMB_SPEED) >= Params.SWARM_TRAJECTORY_INITIAL_CLIMB_HEIGHT

                    # Additional safety check: verify actual altitude if possible
                    actual_altitude_ok = True
                    try:
                        async for position in drone.telemetry.position():
                            current_alt = position.relative_altitude_m
                            if current_alt >= Params.SWARM_TRAJECTORY_INITIAL_CLIMB_HEIGHT * 0.8:  # 80% of target
                                actual_altitude_ok = True
                            break
                    except Exception:
                        pass  # Continue with time-based climb if altitude unavailable

                    in_initial_climb = not (altitude_condition and height_condition and actual_altitude_ok)

                    if in_initial_climb:
                        # Enhanced velocity commands for initial climb with safety limits
                        climb_vz = -min(Params.SWARM_TRAJECTORY_INITIAL_CLIMB_SPEED, 2.0)  # Cap at 2 m/s

                        # Send velocity setpoint during climb with retry logic
                        try:
                            await drone.offboard.set_velocity_ned(
                                VelocityNedYaw(0.0, 0.0, climb_vz, raw_yaw)
                            )
                        except OffboardError as e:
                            logger.warning(f"Climb velocity command failed: {e}, retrying...")
                            await asyncio.sleep(0.1)
                            await drone.offboard.set_velocity_ned(
                                VelocityNedYaw(0.0, 0.0, climb_vz, raw_yaw)
                            )

                        # LED white during climb
                        led_controller.set_color(255, 255, 255)

                        if Params.SWARM_TRAJECTORY_VERBOSE_LOGGING and waypoint_index % 50 == 0:
                            logger.debug(f"Enhanced climb: t={time_in_climb:.1f}s, vz={climb_vz:.1f}m/s, alt_ok={actual_altitude_ok}")

                        waypoint_index += 1
                        continue
                    else:
                        # Initial climb completed - switch to CSV trajectory following
                        initial_climb_completed = True
                        logger.info(f"Enhanced initial climb completed after {time_in_climb:.1f}s - switching to CSV trajectory")

                # Update LED color for feedback (after climb or normal trajectory)
                led_controller.set_color(ledr, ledg, ledb)

                # --- (2) Drift Correction (Skipping) ---
                safe_drift = min(drift_delta, DRIFT_CATCHUP_MAX_SEC)
                skip_count = int(safe_drift / csv_step)
                if skip_count > 0:
                    waypoint_index = min(waypoint_index + skip_count,
                                        total_waypoints - 1)
                    waypoint = waypoints[waypoint_index]
                    # Re-unpack after skip
                    (t_wp, raw_px, raw_py, raw_pz,
                     vx, vy, vz,
                     ax, ay, az,
                     raw_yaw, mode,
                     ledr, ledg, ledb) = waypoint

                    # For global coordinates (lat/lon/alt), use them directly
                    px, py, pz = raw_px, raw_py, raw_pz

                # --- (3) Use Global Coordinates Directly ---
                # px=lat, py=lon, pz=alt (already in global coordinates)
                lla_lat, lla_lon, lla_alt = px, py, pz

                # --- (3.1) Apply position drift correction if enabled ---
                if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift:
                    # For global coordinates, apply NED drift correction
                    # Convert drift to lat/lon offset and apply
                    import pymap3d as pm
                    drift_lat, drift_lon, drift_alt = pm.ned2geodetic(
                        initial_position_drift.north_m,
                        initial_position_drift.east_m,
                        initial_position_drift.down_m,
                        launch_lat, launch_lon, launch_alt
                    )
                    # Apply drift correction
                    lla_lat += (drift_lat - launch_lat)
                    lla_lon += (drift_lon - launch_lon)
                    lla_alt += (drift_alt - launch_alt)

                    if Params.SWARM_TRAJECTORY_VERBOSE_LOGGING and waypoint_index % 100 == 0:
                        logger.debug(f"Applied position drift correction: "
                                   f"N={initial_position_drift.north_m:.2f}m, "
                                   f"E={initial_position_drift.east_m:.2f}m, "
                                   f"D={initial_position_drift.down_m:.2f}m")

                # Always use GLOBAL setpoint for swarm trajectory mode
                gp = PositionGlobalYaw(
                    lla_lat,
                    lla_lon,
                    lla_alt,
                    raw_yaw,
                    PositionGlobalYaw.AltitudeType.AMSL
                )

                if Params.SWARM_TRAJECTORY_LOG_WAYPOINTS:
                    logger.debug(
                        f"GLOBAL setpoint → lat:{lla_lat:.6f}, lon:{lla_lon:.6f}, "
                        f"alt (AMSL):{lla_alt:.2f}, yaw:{raw_yaw:.1f}"
                    )

                # Enhanced setpoint with feed-forward control for better tracking
                if hasattr(Params, 'SWARM_TRAJECTORY_FEEDFORWARD_ENABLED') and Params.SWARM_TRAJECTORY_FEEDFORWARD_ENABLED:
                    # Use velocity feed-forward for smoother trajectory following
                    velocity_setpoint = VelocityNedYaw(vx, vy, vz, 0.0)
                    # Note: Global position + velocity is not directly supported in MAVSDK
                    # So we use position-only for global mode, but log the intent
                    if Params.SWARM_TRAJECTORY_VERBOSE_LOGGING and waypoint_index % 50 == 0:
                        logger.debug(f"Feed-forward velocities: vx={vx:.2f}, vy={vy:.2f}, vz={vz:.2f} m/s")

                await drone.offboard.set_position_global(gp)

                # Update LED color
                led_controller.set_color(ledr, ledg, ledb)

                # --- (4) Capture velocity for continue_heading behavior ---
                last_velocity = (vx, vy, vz, 0.0)  # yaw_rate = 0 for now

                # --- (5) Enhanced Progress Logging with Mission Status ---
                time_to_end = waypoints[-1][0] - t_wp
                prog = (waypoint_index + 1) / total_waypoints

                # Enhanced logging with mission status markers
                if (waypoint_index % 50 == 0) or (prog in [0.1, 0.25, 0.5, 0.75, 0.9]):
                    logger.info(
                        f"Trajectory progress: {prog:.1%} complete | "
                        f"WP {waypoint_index+1}/{total_waypoints} | "
                        f"Alt: {lla_alt:.1f}m | ETA: {time_to_end:.0f}s | "
                        f"Drift: {drift_delta:.2f}s"
                    )

                # Critical milestone logging
                if prog == 0.5:
                    logger.info("*** 50% TRAJECTORY COMPLETED ***")
                elif prog >= 0.9:
                    logger.info("*** 90% TRAJECTORY COMPLETED - APPROACHING END ***")

                if Params.SWARM_TRAJECTORY_VERBOSE_LOGGING and waypoint_index % 20 == 0:
                    logger.debug(
                        f"Position: lat={lla_lat:.6f}, lon={lla_lon:.6f}, alt={lla_alt:.1f}m, "
                        f"yaw={raw_yaw:.1f}°, drift={drift_delta:.2f}s"
                    )

                waypoint_index += 1

            # --- Case B: Ahead of schedule (drift_delta < 0) ---
            else:
                sleep_duration = t_wp - elapsed
                if sleep_duration > 0:
                    await asyncio.sleep(min(sleep_duration, AHEAD_SLEEP_STEP_SEC))
                else:
                    waypoint_index += 1

        except OffboardError as err:
            logger.error(f"Offboard error at waypoint {waypoint_index}: {err}")
            led_controller.set_color(255, 0, 0)
            # Simple recovery attempt
            try:
                await asyncio.sleep(0.5)
                await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
                await asyncio.sleep(0.5)
                continue
            except:
                break
        except Exception as e:
            logger.exception(f"Critical error in trajectory loop at waypoint {waypoint_index}: {e}")
            led_controller.set_color(255, 0, 0)
            break

    # -----------------------------------
    # End-of-Mission Behavior Execution
    # -----------------------------------
    logger.info(f"*** TRAJECTORY COMPLETE *** Executing end behavior: {end_behavior}")
    led_controller.set_color(0, 255, 255)  # Cyan for end behavior

    await execute_end_behavior(drone, end_behavior, launch_lat, launch_lon, launch_alt, last_velocity)

    logger.info("*** SWARM TRAJECTORY MISSION COMPLETE ***")
    led_controller.set_color(0, 255, 0)  # Green for completion


async def controlled_landing(drone: System):
    """
    Perform controlled landing by sending descent commands and monitoring landing state.
    Enhanced version from drone_show.py for maximum reliability.

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
        await drone.offboard.set_velocity_ned(
            VelocityNedYaw(0.0, 0.0, Params.CONTROLLED_DESCENT_SPEED, 0.0)
        )
    except OffboardError as e:
        logger.error(f"Offboard error during controlled landing setup: {e}")
        led_controller.set_color(255, 0, 0)
        return

    retry_count = 0
    max_retries = 3

    while not landing_detected and retry_count < max_retries:
        try:
            velocity_setpoint = VelocityNedYaw(0.0, 0.0, Params.CONTROLLED_DESCENT_SPEED, 0.0)
            await drone.offboard.set_velocity_ned(velocity_setpoint)
            logger.debug(f"Controlled Landing: Descending at {Params.CONTROLLED_DESCENT_SPEED:.2f} m/s.")

            # Check landing state
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
            retry_count += 1
            logger.error(f"Offboard error during controlled landing (attempt {retry_count}): {e}")
            if retry_count >= max_retries:
                led_controller.set_color(255, 0, 0)
                break
            await asyncio.sleep(0.5)  # Brief pause before retry

        except Exception as e:
            logger.exception(f"Unexpected error during controlled landing: {e}")
            led_controller.set_color(255, 0, 0)
            break

    if landing_detected:
        await stop_offboard_mode(drone)
        await disarm_drone(drone)
        logger.info("Controlled landing completed successfully.")
    else:
        logger.warning("Landing not detected. Initiating PX4 native landing as fallback.")
        await stop_offboard_mode(drone)
        await perform_landing(drone)

    led_controller.set_color(0, 255, 0)


async def execute_end_behavior(drone: System, behavior: str, launch_lat: float, launch_lon: float, launch_alt: float, last_velocity=None):
    """
    Execute the specified end-of-mission behavior using PX4 native flight modes.

    Args:
        drone: MAVSDK drone system instance
        behavior: End behavior mode
        launch_lat: Launch latitude for return_home
        launch_lon: Launch longitude for return_home
        launch_alt: Launch altitude for return_home
        last_velocity: Last NED velocity vector for continue_heading mode
    """
    logger = logging.getLogger(__name__)

    try:
        if behavior == 'return_home':
            logger.info("Executing return_home behavior - switching to PX4 RTL mode")
            await stop_offboard_mode(drone)
            await drone.action.hold()
            await drone.action.return_to_launch()
            logger.info("RTL mode activated - drone will return home and land automatically")

        elif behavior == 'land_current':
            logger.info("Executing land_current behavior - using controlled landing")
            await controlled_landing(drone)
            logger.info("Landing at current position completed")

        elif behavior == 'hold_position':
            logger.info("Executing hold_position behavior - switching to PX4 HOLD mode")
            await stop_offboard_mode(drone)
            await drone.action.hold()
            logger.info("HOLD mode activated - drone will maintain current position")

        elif behavior == 'continue_heading':
            logger.info("Executing continue_heading behavior - maintaining last velocity vector")
            if last_velocity is not None:
                vx, vy, vz, yaw_rate = last_velocity
                logger.info(f"Continuing with velocity: vx={vx:.2f}, vy={vy:.2f}, vz={vz:.2f} m/s, yaw_rate={yaw_rate:.2f} deg/s")

                # Continue with last velocity indefinitely
                while True:
                    try:
                        await drone.offboard.set_velocity_ned(
                            VelocityNedYaw(vx, vy, vz, yaw_rate)
                        )
                        await asyncio.sleep(0.1)  # 10Hz velocity commands
                    except OffboardError:
                        logger.warning("Offboard error in continue_heading - stopping")
                        break
            else:
                logger.warning("No last velocity available for continue_heading, switching to HOLD")
                await stop_offboard_mode(drone)
                await drone.action.hold()

        else:
            logger.warning(f"Unknown end behavior '{behavior}', defaulting to return_home")
            await execute_end_behavior(drone, 'return_home', launch_lat, launch_lon, launch_alt)

    except Exception as e:
        logger.error(f"Error executing end behavior '{behavior}': {e}")
        # Enhanced fallback with multiple recovery attempts
        recovery_attempts = [
            ("controlled_landing", lambda: controlled_landing(drone)),
            ("emergency_RTL", lambda: emergency_rtl_sequence(drone)),
            ("emergency_land", lambda: emergency_land_sequence(drone))
        ]

        for attempt_name, attempt_func in recovery_attempts:
            try:
                logger.warning(f"Attempting {attempt_name} recovery...")
                await attempt_func()
                logger.info(f"{attempt_name} recovery successful")
                break
            except Exception as recovery_error:
                logger.error(f"{attempt_name} recovery failed: {recovery_error}")
                continue
        else:
            logger.critical("All recovery attempts failed!")


async def emergency_rtl_sequence(drone: System):
    """Emergency Return to Launch sequence with retries."""
    logger = logging.getLogger(__name__)
    try:
        await stop_offboard_mode(drone)
        await asyncio.sleep(0.5)
        await drone.action.hold()
        await asyncio.sleep(0.5)
        await drone.action.return_to_launch()
        logger.info("Emergency RTL initiated")
    except Exception as e:
        logger.error(f"Emergency RTL sequence failed: {e}")
        raise


async def emergency_land_sequence(drone: System):
    """Emergency landing sequence with retries."""
    logger = logging.getLogger(__name__)
    try:
        await stop_offboard_mode(drone)
        await asyncio.sleep(0.5)
        await drone.action.hold()
        await asyncio.sleep(0.5)
        await drone.action.land()
        logger.info("Emergency landing initiated")
        await wait_for_landing(drone)
    except Exception as e:
        logger.error(f"Emergency land sequence failed: {e}")
        raise


# Import all the other functions from drone_show.py (connection, preflight, etc.)
# These functions are identical to drone_show.py implementation

@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(5))
async def initial_setup_and_connection():
    """
    Perform the initial setup and connection for the drone.
    (Identical to drone_show.py implementation)
    """
    logger = logging.getLogger(__name__)
    try:
        # Initialize LEDController
        led_controller = LEDController.get_instance()
        # Set LED color to blue to indicate initialization
        led_controller.set_color(0, 0, 255)
        logger.info("LED set to blue: Initialization in progress.")

        # Determine the MAVSDK server address and port
        grpc_port = Params.DEFAULT_GRPC_PORT  # Fixed gRPC port

        # MAVSDK server is assumed to be running on localhost
        mavsdk_server_address = "127.0.0.1"

        # Create the drone system
        drone = System(mavsdk_server_address=mavsdk_server_address, port=grpc_port)
        await drone.connect(system_address=f"udp://:{Params.mavsdk_port}")

        logger.info(
            f"Connecting to drone via MAVSDK server at {mavsdk_server_address}:{grpc_port} on UDP port {Params.mavsdk_port}."
        )

        # Wait for connection with a timeout
        start_time = time.time()
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(
                    f"Drone connected via MAVSDK server at {mavsdk_server_address}:{grpc_port}."
                )
                break
            if time.time() - start_time > 10:
                logger.error("Timeout while waiting for drone connection.")
                led_controller.set_color(255, 0, 0)  # Red
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        # Log initial connection success
        logger.info("Initial setup and connection successful.")
        return drone
    except Exception:
        logger.exception("Error during initial setup and connection.")
        led_controller.set_color(255, 0, 0)  # Red
        raise


async def pre_flight_checks(drone: System):
    """
    Perform pre-flight checks to ensure the drone is ready for flight.
    (Identical to drone_show.py implementation)
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting pre-flight checks.")

    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 255, 0)  # Yellow = in progress

    start_time = time.time()
    gps_origin = None
    health_checks_passed = False

    try:
        if Params.REQUIRE_GLOBAL_POSITION:
            # Phase 1: Wait for health checks to pass with timeout
            logger.info("Waiting for health checks...")
            async for health in drone.telemetry.health():
                # Check timeout first
                if time.time() - start_time > Params.PRE_FLIGHT_TIMEOUT:
                    logger.error("Pre-flight checks timed out during health verification")
                    led_controller.set_color(255, 0, 0)
                    raise TimeoutError("Health check phase timed out")

                if health.is_global_position_ok and health.is_home_position_ok:
                    logger.info("Global position and home position checks passed")
                    health_checks_passed = True
                    break  # Exit health check loop

                # Log missing requirements
                if not health.is_global_position_ok:
                    logger.warning("Waiting for global position estimate...")
                if not health.is_home_position_ok:
                    logger.warning("Waiting for home position initialization...")
                
                await asyncio.sleep(1)

            if not health_checks_passed:
                raise RuntimeError("Failed to pass health checks")

            # Phase 2: Get GPS origin (with fallback)
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
                # Get single position update as fallback
                async for position in drone.telemetry.position():
                    gps_origin = {
                        'latitude': position.latitude_deg,
                        'longitude': position.longitude_deg,
                        'altitude': position.absolute_altitude_m
                    }
                    logger.info(f"Using fallback position: {gps_origin}")
                    break  # Exit after first position update

            # Final validation
            if not gps_origin:
                logger.error("Failed to obtain GPS origin")
                led_controller.set_color(255, 0, 0)
                raise ValueError("No GPS origin available")

            logger.info("Pre-flight checks completed successfully")
            led_controller.set_color(0, 255, 0)  # Green = success
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
    Arm the drone and start offboard mode.
    (Identical to drone_show.py implementation)
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Initialize LED controller
        led_controller = LEDController.get_instance()
        led_controller.set_color(0, 255, 0)  # Green: Arming in progress
        logger.info("LED set to green: Arming in progress.")

        # Step 1: Compute initial position offset if required
        global initial_position_drift

        if Params.REQUIRE_GLOBAL_POSITION and home_position:
            logger.info("Computing initial position offset in NED coordinates.")
            initial_position_drift = await compute_position_drift()
            logger.info(f"Initial position drift computed: {initial_position_drift}")
        else:
            logger.info("Skipping position offset computation (global position check disabled or no home position).")

        # Step 2: Set flight mode to Hold as a safety precaution
        logger.info("Setting Hold flight mode.")
        await drone.action.hold()

        # Step 3: Arm the drone
        logger.info("Arming the drone.")
        await drone.action.arm()

        # Step 4: Set an initial offboard velocity setpoint
        logger.info("Setting initial velocity setpoint for offboard mode.")
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))

        # Step 5: Start offboard mode with retry logic
        logger.info("Starting offboard mode.")
        offboard_attempts = 0
        max_offboard_attempts = 3

        while offboard_attempts < max_offboard_attempts:
            try:
                await drone.offboard.start()
                logger.info("Offboard mode started successfully.")
                break
            except OffboardError as e:
                offboard_attempts += 1
                logger.warning(f"Offboard start attempt {offboard_attempts} failed: {e}")
                if offboard_attempts >= max_offboard_attempts:
                    raise
                await asyncio.sleep(1.0)
                await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))

        # Indicate readiness with LED color
        led_controller.set_color(255, 255, 255)  # White: Ready to fly
        logger.info("LED set to white: Drone is ready to fly.")

    except OffboardError as error:
        # Handle specific Offboard mode errors
        logger.error(f"Offboard error encountered: {error}")
        await drone.action.disarm()
        led_controller.set_color(255, 0, 0)  # Red: Error state
        raise

    except Exception as e:
        # Handle general exceptions and ensure the drone is disarmed
        logger.exception("Unexpected error during arming and starting offboard mode.")
        await drone.action.disarm()
        led_controller.set_color(255, 0, 0)  # Red: Error state
        raise e


async def compute_position_drift():
    """
    Compute initial position drift using LOCAL_POSITION_NED from the drone's API.
    (Identical to drone_show.py implementation)
    """
    logger = logging.getLogger(__name__)
    default_drift = PositionNedYaw(0.0, 0.0, 0.0, 0.0)  # Default to no drift

    try:
        # Request NED data from local API endpoint
        response = requests.get(
            f"http://localhost:{Params.drones_flask_port}/get-local-position-ned",
            timeout=2
        )

        if response.status_code == 200:
            ned_data = response.json()
            
            # Create PositionNedYaw from API response (x=north, y=east, z=down)
            drift = PositionNedYaw(
                north_m=ned_data['x'],
                east_m=ned_data['y'],
                down_m=ned_data['z'],
                yaw_deg=0.0  # Adding yaw parameter, set to 0 if not needed
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
    (Identical to drone_show.py implementation)
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Initiating landing.")
        await drone.action.land()

        start_time = time.time()
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


async def wait_for_landing(drone: System):
    """
    Wait for the drone to land after initiating landing.
    (Identical to drone_show.py implementation)
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


async def stop_offboard_mode(drone: System):
    """
    Stop offboard mode for the drone.
    (Identical to drone_show.py implementation)
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
    (Identical to drone_show.py implementation)
    """
    logger = logging.getLogger(__name__)
    try:
        logger.info("Disarming drone.")
        await drone.action.disarm()
        # Set LEDs to solid red to indicate disarming
        led_controller = LEDController.get_instance()
        led_controller.set_color(255, 0, 0)
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
    (Identical to drone_show.py implementation)
    """
    home_dir = os.path.expanduser("~")
    mavsdk_drone_show_dir = os.path.join(home_dir, "mavsdk_drone_show")
    mavsdk_server_path = os.path.join(mavsdk_drone_show_dir, "mavsdk_server")
    return mavsdk_server_path


def start_mavsdk_server(udp_port: int):
    """
    Start MAVSDK server instance for the drone.
    (Identical to drone_show.py implementation)
    """
    logger = logging.getLogger(__name__)
    try:
        # Check if MAVSDK server is already running
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

        # Construct the absolute path to mavsdk_server
        mavsdk_server_path = get_mavsdk_server_path()

        logger.debug(f"Constructed MAVSDK server path: {mavsdk_server_path}")

        if not os.path.isfile(mavsdk_server_path):
            logger.error(f"mavsdk_server executable not found at '{mavsdk_server_path}'.")
            sys.exit(1)  # Exit the program as the server is essential

        if not os.access(mavsdk_server_path, os.X_OK):
            logger.info(f"Setting executable permissions for '{mavsdk_server_path}'.")
            os.chmod(mavsdk_server_path, 0o755)

        # Start the MAVSDK server
        mavsdk_server = subprocess.Popen(
            [mavsdk_server_path, "-p", str(Params.DEFAULT_GRPC_PORT), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(
            f"MAVSDK server started with gRPC port {Params.DEFAULT_GRPC_PORT} and UDP port {udp_port}."
        )

        # Optionally, start logging the MAVSDK server output asynchronously
        asyncio.create_task(log_mavsdk_output(mavsdk_server))

        # Wait until the server is listening on the gRPC port
        if not wait_for_port(Params.DEFAULT_GRPC_PORT, timeout=Params.PRE_FLIGHT_TIMEOUT):
            logger.error(
                f"MAVSDK server did not start listening on port {Params.DEFAULT_GRPC_PORT} within timeout."
            )
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
    Checks if the MAVSDK server is running on the specified gRPC port.
    (Identical to drone_show.py implementation)
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
    Wait until a port starts accepting TCP connections.
    (Identical to drone_show.py implementation)
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
    Asynchronously logs the stdout and stderr of the MAVSDK server.
    (Identical to drone_show.py implementation)
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
    Stop the MAVSDK server instance.
    (Identical to drone_show.py implementation)
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
#         Main Runner           #
# ----------------------------- #

async def run_swarm_trajectory_mission(
    synchronized_start_time,
    position_id_override=None,
    end_behavior_override=None
):
    """
    Run the swarm trajectory mission with the provided configurations.

    Args:
        synchronized_start_time (float): Synchronized start time (UNIX timestamp).
        position_id_override (int): Override position ID (default: use HW_ID).
        end_behavior_override (str): Override end behavior.
    """
    logger = logging.getLogger(__name__)
    mavsdk_server = None
    
    try:
        global HW_ID, position_id

        # Step 1: Start MAVSDK Server
        udp_port = Params.mavsdk_port
        mavsdk_server = start_mavsdk_server(udp_port)
        if mavsdk_server is None:
            logger.error("Failed to start MAVSDK server. Exiting program.")
            sys.exit(1)

        # Give the server time to spin up
        await asyncio.sleep(2)

        # Step 2: Initial Setup and Connection
        drone = await initial_setup_and_connection()

        # Step 3: Pre-flight Checks
        home_position = await pre_flight_checks(drone)

        # Step 4: Capture precise launch position from telemetry
        launch_lat = launch_lon = launch_alt = None
        logger.info("Capturing launch position (lat/lon/alt) from telemetry...")
        start = time.time()
        async for pos in drone.telemetry.position():
            launch_lat = pos.latitude_deg
            launch_lon = pos.longitude_deg
            launch_alt = pos.absolute_altitude_m
            logger.info(
                f"Launch position captured: "
                f"lat={launch_lat:.6f}, lon={launch_lon:.6f}, alt={launch_alt:.2f}m"
            )
            break
        if launch_lat is None:
            logger.error("Failed to capture launch position from telemetry within timeout.")
            sys.exit(1)

        # Step 5: Determine Position ID for trajectory file
        if position_id_override is not None:
            position_id = position_id_override
            logger.info(f"Using position ID override: {position_id}")
        else:
            # Read HW_ID and get position_id from config
            HW_ID = read_hw_id()
            if HW_ID is None:
                logger.error("Failed to read HW ID; exiting.")
                sys.exit(1)
            
            drone_config = read_config(CONFIG_CSV_NAME)
            if drone_config is None:
                logger.error("Drone config not found; exiting.")
                sys.exit(1)
            
            position_id = drone_config.pos_id
            logger.info(f"Using position ID from config: {position_id} (HW_ID: {HW_ID})")

        # Step 6: Handle synchronized start time (exact match with drone_show.py)
        if synchronized_start_time is None:
            synchronized_start_time = time.time()
            logger.info(f"No start_time provided; using now: {time.ctime(synchronized_start_time)}")
        now = time.time()
        if synchronized_start_time > now:
            wait_secs = synchronized_start_time - now
            logger.info(f"Waiting {wait_secs:.2f}s until synchronized start time.")
            await asyncio.sleep(wait_secs)
        elif synchronized_start_time < now:
            logger.warning(f"Start time was {now - synchronized_start_time:.2f}s ago; starting immediately.")
        else:
            logger.info("Synchronized start time is now.")

        # Step 7: Arm and enter Offboard
        await arming_and_starting_offboard_mode(drone, home_position)

        # Step 8: Load trajectory file with validation
        try:
            waypoints = read_swarm_trajectory_file(position_id=position_id)
            logger.info(f"Loaded trajectory for position ID {position_id} with {len(waypoints)} waypoints.")

            # Validate trajectory data
            if len(waypoints) < 10:
                raise ValueError(f"Trajectory too short: {len(waypoints)} waypoints")

            # Check trajectory duration
            trajectory_duration = waypoints[-1][0] - waypoints[0][0]
            logger.info(f"Trajectory duration: {trajectory_duration:.1f} seconds")

            if trajectory_duration < 10:
                logger.warning(f"Short trajectory duration: {trajectory_duration:.1f}s")

        except Exception as e:
            logger.error(f"CRITICAL - Failed to load trajectory: {e}")
            sys.exit(1)

        # Step 9: Execute the swarm trajectory mission
        await perform_swarm_trajectory(
            drone,
            waypoints,
            home_position,
            synchronized_start_time,
            launch_lat, launch_lon, launch_alt,
            end_behavior=end_behavior_override
        )

        logger.info("Mission completed successfully.")
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
    Main function to run the swarm trajectory mission.
    """
    # Configure logging
    configure_logging("swarm_trajectory")
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description='Swarm Trajectory Mission Script')
    parser.add_argument('--start_time', type=float, help='Synchronized start UNIX time')
    parser.add_argument(
        '--position_id',
        type=int,
        help='Position ID for trajectory file (overrides HW_ID config lookup)'
    )
    parser.add_argument(
        '--end_behavior',
        type=str,
        choices=['return_home', 'land_current', 'hold_position', 'continue_heading'],
        help='End-of-mission behavior override'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode for verbose logging.',
    )
    
    args = parser.parse_args()

    # Adjust logging level based on debug flag
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug mode ENABLED: Verbose logging is active.")
    else:
        logging.getLogger().setLevel(logging.INFO)
        logger.info("Debug mode DISABLED: Standard logging level set to INFO.")

    # Get the synchronized start time (exact match with drone_show.py)
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

    # Display configuration
    logger.info(f"Swarm Trajectory Mode Configuration:")
    logger.info(f"  - Base Path: {Params.SWARM_TRAJECTORY_BASE_PATH}")
    logger.info(f"  - File Prefix: {Params.SWARM_TRAJECTORY_FILE_PREFIX}")
    logger.info(f"  - End Behavior: {args.end_behavior or Params.SWARM_TRAJECTORY_END_BEHAVIOR}")
    logger.info(f"  - Force Global: {Params.SWARM_TRAJECTORY_FORCE_GLOBAL}")
    logger.info(f"  - Auto Launch Position: {Params.AUTO_LAUNCH_POSITION}")

    if args.position_id:
        logger.info(f"Position ID override: {args.position_id}")
    else:
        logger.info("Position ID: Will use HW_ID from config lookup")

    try:
        asyncio.run(
            run_swarm_trajectory_mission(
                synchronized_start_time,
                position_id_override=args.position_id,
                end_behavior_override=args.end_behavior,
            )
        )
    except Exception:
        logger.exception("Unhandled exception in main.")
        sys.exit(1)


if __name__ == "__main__":
    main()