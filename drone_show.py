#!/usr/bin/env python3
# Copyright (c) 2025 Alireza Ghaderi
# SPDX-License-Identifier: CC-BY-NC-SA-4.0
#
# This file is part of MAVSDK Drone Show
# https://github.com/alireza787b/mavsdk_drone_show
#
# Licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0
# For commercial licensing, contact: p30planets@gmail.com

"""
Drone Show Script (`drone_show.py`)

----------------------------------------
Author: Alireza Ghaderi
Date: 2025-01-29
Version: 3.8.0 (Phase 2: Auto Global Origin Correction)
Previous Version Backup: drone_show_v3.7_backup.py
----------------------------------------

Description:
    Orchestrates an offboard drone show by executing time-synchronized trajectories with optional
    local (NED) or global (LLH) setpoints. Integrates with MAVSDK for flight control, pymap3d for
    coordinate transforms, and an LED controller for real-time status indication.

Key Features:
  • Dual Setpoint Modes
    – Local NED: `PositionNedYaw` for body-relative control.
    – Global LLH: `PositionGlobalYaw` using GPS-derived LLA when `Params.USE_GLOBAL_SETPOINTS` is True.

  • 🆕 PHASE 2: Auto Global Origin Correction (NEW in v3.8)
    – Fetch shared drone show origin from GCS server with triple fallback (GCS → cache → current position)
    – Position validation: Abort if drone placement deviates >20m from expected position
    – Smooth position blending: Transition from current position to corrected trajectory after initial climb
    – Allows approximate operator placement (±5-10m tolerance) with intelligent auto-correction
    – Enable via: `--auto_global_origin True` or `Params.AUTO_GLOBAL_ORIGIN_MODE = True`

  • Initial Climb Safety
    – Vertical climb phase with configurable thresholds (altitude, duration, and mode) to avoid abrupt maneuvers.

  • Drift Compensation
    – Time-drift catch-up allowing waypoint skipping and feed-forward velocity/acceleration in NED mode.

  • Auto / Manual Launch Position
    – Auto-extract first waypoint origin or shift by preconfigured NED offsets.

  • Controlled vs. Native Landing
    – Selects between PX4 native landing or a custom descent based on final altitude and mission progress.

  • Comprehensive Logging & LEDs
    – Verbose debug/info logs and LED color changes reflecting initialization, pre-flight, in-flight, and error states.

Usage:
    python drone_show.py
        [--start_time START_TIME]               # UNIX timestamp to synchronize launch
        [--custom_csv CUSTOM_CSV]               # Trajectory file name (e.g., active.csv)
        [--auto_launch_position {True,False}]   # Override Params.AUTO_LAUNCH_POSITION
        [--auto_global_origin {True,False}]     # 🆕 Phase 2: Enable/disable auto origin correction
        [--debug]                               # Enable DEBUG log level

Command Line Arguments:
  --start_time              UNIX epoch time to delay mission start (default: now)
  --custom_csv              Custom CSV file under `shapes[_sitl]/`
  --auto_launch_position    Force enable/disable automatic origin extraction
  --auto_global_origin      🆕 Phase 2: Force enable/disable auto global origin correction mode
  --debug                   Turn on detailed (DEBUG) logging

Dependencies:
  • Python 3.7+
  • MAVSDK (`pip install mavsdk`)
  • psutil (`pip install psutil`)
  • tenacity (`pip install tenacity`)
  • pymap3d (`pip install pymap3d`) - replaces navpy for coordinate transforms
  • requests, asyncio, argparse, logging, csv, socket
  • 🆕 src.origin_cache - Phase 2 origin caching system

LED Status Indicators:
  • Blue      — Initialization
  • Yellow    — Pre-flight checks
  • Green     — Arming in progress
  • CSV RGB   — Synchronized show LEDs during trajectory (ledr, ledg, ledb from waypoints)
  • Green     — Mission complete / standby
  • Red       — Error or disarmed  

Notes:
  • Ensure `mavsdk_server` is executable and located at `~/mavsdk_drone_show/mavsdk_server`.  
  • Toggle `Params.USE_GLOBAL_SETPOINTS` to switch between local and global control modes.
"""


import os
import sys
import time
import asyncio
import csv
import json
import subprocess
import logging
import socket
import psutil
import requests
import argparse
import pymap3d as pm

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
from src import origin_cache  # Phase 2: Origin caching system

from drone_show_src.utils import (
    configure_logging,
    read_hw_id,
    clamp_led_value,
    global_to_local,
)

# ----------------------------- #
#        Data Structures        #
# ----------------------------- #

Drone = namedtuple(
    "Drone",
    "hw_id pos_id initial_x initial_y ip mavlink_port",
)

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

HW_ID = None  # Hardware ID of the drone
position_id = None  # Position ID of the drone
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


def blender_north_west_up_to_ned(x_b, y_b, z_b=0.0):
    """
    Convert a 3D vector from a Blender-like system where:
      - X = North
      - Y = West
      - Z = Up
    into NED coordinates:
      - X = North
      - Y = East (so Y_ned = - Y_blender)
      - Z = Down (so Z_ned = - Z_blender)

    Args:
        x_b (float): Blender X (north)
        y_b (float): Blender Y (west)
        z_b (float): Blender Z (up)

    Returns:
        (float, float, float): (N, E, D) in NED
    """
    n = x_b          # North is unchanged
    e = -y_b         # West => negative East
    d = -z_b         # Up => negative Down
    return (n, e, d)


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

                        drone = Drone(
                            hw_id,
                            pos_id,
                            initial_x,
                            initial_y,
                            ip,
                            mavlink_port,
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


def extract_initial_positions(first_waypoint: dict) -> tuple:
    """
    Extract initial X, Y, Z positions from the first waypoint in NED coords.

    Args:
        first_waypoint (dict): Dictionary representing the first waypoint.

    Returns:
        tuple: (initial_x, initial_y, initial_z)

    Raises:
        KeyError: If required keys are missing in the waypoint.
        ValueError: If the values cannot be converted to float.
    """
    try:
        initial_x = float(first_waypoint["px"])
        initial_y = float(first_waypoint["py"])
        initial_z = float(first_waypoint.get("pz", 0.0))  # Default to 0.0 if pz not present
        return initial_x, initial_y, initial_z
    except KeyError as ke:
        raise KeyError(f"Missing key in first waypoint: {ke}")
    except ValueError as ve:
        raise ValueError(f"Invalid value in first waypoint: {ve}")


def adjust_waypoints(
    waypoints: list, initial_x: float, initial_y: float, initial_z: float = 0.0
) -> list:
    """
    Adjust all waypoints by subtracting the initial positions in NED coordinates.

    Args:
        waypoints (list): List of waypoints as tuples.
        initial_x (float): Initial X-coordinate (north).
        initial_y (float): Initial Y-coordinate (east).
        initial_z (float): Initial Z-coordinate (down).

    Returns:
        list: List of adjusted waypoints, such that the first position is (0,0,0).
    """
    adjusted_waypoints = []
    logger = logging.getLogger(__name__)

    for idx, waypoint in enumerate(waypoints):
        try:
            t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode, ledr, ledg, ledb = waypoint
            adjusted_px = px - initial_x
            adjusted_py = py - initial_y
            adjusted_pz = pz - initial_z
            adjusted_waypoints.append(
                (
                    t,
                    adjusted_px,
                    adjusted_py,
                    adjusted_pz,
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
            logger.error(f"Error adjusting waypoint at index {idx}: {ve}")
        except Exception as e:
            logger.error(f"Unexpected error adjusting waypoint at index {idx}: {e}")

    return adjusted_waypoints


async def get_current_ned_position(drone: System) -> PositionNedYaw:
    """
    Get current drone position in NED coordinates relative to takeoff.

    This function tries multiple methods to get the current NED position:
    1. MAVSDK telemetry (most reliable)
    2. Local API fallback
    3. Zero position fallback (safest)

    Args:
        drone (System): MAVSDK drone system instance

    Returns:
        PositionNedYaw: Current position in NED coordinates with zero yaw
    """
    logger = logging.getLogger(__name__)

    try:
        # Method 1: Try MAVSDK telemetry first (most reliable)
        logger.debug("Attempting to get current NED position via MAVSDK telemetry")
        async for position_ned in drone.telemetry.position_velocity_ned():
            current_pos = PositionNedYaw(
                position_ned.position.north_m,
                position_ned.position.east_m,
                position_ned.position.down_m,
                0.0  # Yaw not needed for position hold
            )
            logger.debug(f"Current NED position via telemetry: N={current_pos.north_m:.2f}, "
                        f"E={current_pos.east_m:.2f}, D={current_pos.down_m:.2f}")
            return current_pos
    except Exception as e:
        logger.warning(f"MAVSDK telemetry position failed: {e}")

    try:
        # Method 2: Fallback to local API
        logger.debug("Attempting to get current NED position via local API")
        response = requests.get(
            f"http://localhost:{Params.drones_flask_port}/get-local-position-ned",
            timeout=1
        )
        if response.status_code == 200:
            ned_data = response.json()
            current_pos = PositionNedYaw(
                ned_data['x'], ned_data['y'], ned_data['z'], 0.0
            )
            logger.debug(f"Current NED position via API: N={current_pos.north_m:.2f}, "
                        f"E={current_pos.east_m:.2f}, D={current_pos.down_m:.2f}")
            return current_pos
    except Exception as e:
        logger.warning(f"Local API position request failed: {e}")

    # Method 3: Ultimate fallback - return zero position (safest for position hold)
    logger.warning("Could not get current NED position, using (0,0,0) - drone will hover at takeoff position")
    return PositionNedYaw(0.0, 0.0, 0.0, 0.0)


def read_trajectory_file(
    filename: str,
    auto_launch_position: bool = False,
    initial_x: float = 0.0,
    initial_y: float = 0.0
) -> list:
    """
    Read and adjust the trajectory waypoints from a CSV file.

    The CSV is assumed to be in a Blender-like coordinate system:
      - X = North
      - Y = West
      - Z = Up
    So we transform to real NED (X=north, Y=east, Z=down), then optionally shift
    so that the first point is (0,0,0) if auto_launch_position is True (or if we subtract config initial_x / initial_y).

    Args:
        filename (str): Path to the drone-specific trajectory CSV file.
        auto_launch_position (bool): Flag to determine if initial positions should be auto-extracted from the first waypoint.
        initial_x (float): Initial X (N) from config (if auto_launch_position=False).
        initial_y (float): Initial Y (E) from config (if auto_launch_position=False).

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
                # Extract initial positions from the first waypoint (in NED coords)
                try:
                    init_n, init_e, init_d = extract_initial_positions(rows[0])
                    logger.info(
                        f"Auto Launch Position ENABLED. NED for first waypoint: "
                        f"(N={init_n:.2f}, E={init_e:.2f}, D={init_d:.2f})"
                    )
                except (KeyError, ValueError) as e:
                    logger.error(f"Failed to extract initial positions: {e}")
                    sys.exit(1)

                # Read and collect all waypoints in NED
                for idx, row in enumerate(rows):
                    try:
                        t = float(row["t"])
                        # Positions in  NED (already NED)
                        px = float(row["px"])
                        py = float(row["py"])
                        pz = float(row.get("pz", 0.0))

                        # Velocities in NED (already NED)
                        vx = float(row["vx"])
                        vy = float(row["vy"])
                        vz = float(row["vz"])

                        # Accelerations in NED (already NED)
                        ax = float(row["ax"])
                        ay = float(row["ay"])
                        az = float(row["az"])

                        yaw = float(row["yaw"])
                        ledr = clamp_led_value(row.get("ledr", 0))
                        ledg = clamp_led_value(row.get("ledg", 0))
                        ledb = clamp_led_value(row.get("ledb", 0))
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

                # Adjust waypoints so the first point is (0,0,0) in NED
                waypoints = adjust_waypoints(waypoints, init_n, init_e, init_d)
                logger.info(f"Trajectory waypoints adjusted to start from NED (0, 0, 0).")

            else:
                # We already have initial_x, initial_y in real NED from config.
                init_d = 0.0  # Typically 0 if we only store 2D offsets

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

                logger.info(f"Trajectory file '{filename}' read successfully with {len(waypoints)} waypoints.")

                # Now shift the entire path so that the first point is (0,0,0) in NED by subtracting (initial_x, initial_y, 0).
                logger.info(f"⚠️  ADJUSTING WAYPOINTS: Subtracting initial_x={initial_x:.2f}, initial_y={initial_y:.2f}, init_d={init_d:.2f}")
                logger.info(f"   First waypoint BEFORE adjust: ({waypoints[0][1]:.2f}, {waypoints[0][2]:.2f}, {waypoints[0][3]:.2f})")
                waypoints = adjust_waypoints(waypoints, initial_x, initial_y, init_d)
                logger.info(f"   First waypoint AFTER adjust: ({waypoints[0][1]:.2f}, {waypoints[0][2]:.2f}, {waypoints[0][3]:.2f})")
                logger.info(
                    f"Trajectory waypoints adjusted using config initial positions "
                    f"(N={initial_x}, E={initial_y}, D={init_d})."
                )

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
async def perform_trajectory(
    drone: System,
    waypoints: list,
    home_position,
    start_time: float,
    origin_lat: float,
    origin_lon: float,
    origin_alt: float,
    effective_auto_origin_mode=False,
    origin_source=None,
    use_global_setpoints=True
):
    """
    Executes the trajectory with an initial vertical climb phase to prevent abrupt movements,
    and handles time-drift corrections after the initial climb is complete.

    Now supports both local NED and global LLA setpoints, chosen by use_global_setpoints parameter.

    Phase 2 Enhancement:
        When effective_auto_origin_mode=True and origin_source in ['gcs', 'cache']:
        - Applies smooth position blending after initial climb
        - Transitions from current position to corrected trajectory over BLEND_TRANSITION_DURATION_SEC
        - Interpolates in LLA space for global setpoints

    Args:
        drone: MAVSDK System instance
        waypoints: List of trajectory waypoints
        home_position: Home position dict (may be unused)
        start_time: Mission start time (UNIX timestamp)
        origin_lat, origin_lon, origin_alt: Shared drone show origin coordinates (0,0,0) in NED for GPS conversion
        effective_auto_origin_mode: True if Phase 2 auto origin correction is enabled
        origin_source: Source of origin ('gcs', 'cache', 'launch_position', 'current_position')
        use_global_setpoints: True for GLOBAL mode (GPS), False for LOCAL mode (NED)
    """
    global drift_delta, initial_position_drift
    logger = logging.getLogger(__name__)

    # Drift / sleep parameters
    DRIFT_CATCHUP_MAX_SEC = 0.5
    AHEAD_SLEEP_STEP_SEC   = 0.1

    total_waypoints = len(waypoints)
    waypoint_index  = 0
    landing_detected = False
    led_controller  = LEDController.get_instance()

    # Initial climb bookkeeping
    in_initial_climb         = True
    initial_climb_completed  = False
    initial_climb_start_time = time.time()
    initial_climb_yaw        = None

    # Phase 2: Position blending bookkeeping
    blend_active = False
    blend_start_time = None
    blend_start_lat = None
    blend_start_lon = None
    blend_start_alt = None
    blending_enabled = effective_auto_origin_mode and origin_source in ['command', 'gcs', 'cache']

    if blending_enabled:
        logger.info(f"🔀 Phase 2 blending enabled (origin source: {origin_source})")
        logger.info(f"   Blend duration: {Params.BLEND_TRANSITION_DURATION_SEC}s")
    else:
        logger.info(f"🔀 Phase 2 blending disabled (origin source: {origin_source})")

    # Time step between CSV rows (for drift‐skip calculations)
    csv_step = (waypoints[1][0] - waypoints[0][0]) \
        if total_waypoints > 1 else Params.DRIFT_CHECK_PERIOD

    # Determine final altitude to choose landing method
    final_altitude       = -waypoints[-1][3]  # Convert NED down to altitude
    trajectory_ends_high = final_altitude > Params.GROUND_ALTITUDE_THRESHOLD
    logger.info(
        f"Trajectory ends {'high' if trajectory_ends_high else 'low'}; "
        f"{'PX4 native landing' if trajectory_ends_high else 'controlled landing'}."
    )

    # -----------------------------------
    # Main Trajectory Execution Loop
    # -----------------------------------
    while waypoint_index < total_waypoints:
        try:
            now     = time.time()
            elapsed = now - start_time
            waypoint = waypoints[waypoint_index]
            t_wp    = waypoint[0]
            drift_delta = elapsed - t_wp

            # --- Case A: On time or behind schedule ---
            if drift_delta >= 0:
                # Unpack CSV row
                (_, raw_px, raw_py, raw_pz,
                 vx, vy, vz,
                 ax, ay, az,
                 raw_yaw, mode,
                 ledr, ledg, ledb) = waypoint

                # --- Apply initial-position correction if enabled ---
                # NOTE: In Phase 2 auto-origin mode, waypoints are absolute offsets from shared origin
                # so we should NOT apply drift correction (which is in LOCAL frame)
                if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift and not effective_auto_origin_mode:
                    px = raw_px + initial_position_drift.north_m
                    py = raw_py + initial_position_drift.east_m
                    pz = raw_pz + initial_position_drift.down_m
                else:
                    px, py, pz = raw_px, raw_py, raw_pz

                # --- (1) Initial Climb Phase ---
                time_in_climb = now - initial_climb_start_time
                if not initial_climb_completed:
                    # Check BOTH altitude AND time (v3.7 behavior)
                    # This ensures drone actually climbs before completing initial climb phase
                    actual_alt = -pz  # Current waypoint altitude (increases as waypoints advance)
                    under_alt = actual_alt < Params.INITIAL_CLIMB_ALTITUDE_THRESHOLD
                    under_time = time_in_climb < Params.INITIAL_CLIMB_TIME_THRESHOLD
                    in_initial_climb = under_alt or under_time
                    if not in_initial_climb:
                        initial_climb_completed = True
                        logger.info(f"=== INITIAL CLIMB COMPLETED === after {time_in_climb:.1f}s at altitude {actual_alt:.1f}m, switching to CSV trajectory following")

                        # PHASE 2: Initiate position blending
                        if blending_enabled:
                            # Capture current position at end of climb
                            async for pos in drone.telemetry.position():
                                blend_start_lat = pos.latitude_deg
                                blend_start_lon = pos.longitude_deg
                                blend_start_alt = pos.absolute_altitude_m
                                break

                            # PHASE 2 FIX: Use CURRENT waypoint as blend target
                            # waypoint_index has advanced during climb to maintain timeline sync
                            # Do NOT reset - we need to continue from current position in timeline
                            logger.info(f"🔍 BLEND DEBUG: waypoint_index={waypoint_index}, time_in_climb={time_in_climb:.2f}s")

                            current_waypoint = waypoints[waypoint_index]

                            # Unpack current waypoint (timeline position after climb)
                            (t_wp_0, px_0, py_0, pz_0,
                             vx_0, vy_0, vz_0,
                             ax_0, ay_0, az_0,
                             yaw_0, mode_0,
                             ledr_0, ledg_0, ledb_0) = current_waypoint

                            logger.info(f"🔍 BLEND TARGET: idx={waypoint_index}, t={t_wp_0:.2f}s")
                            logger.info(f"🔍 NED coords: px={px_0:.2f}, py={py_0:.2f}, pz={pz_0:.2f}")

                            # Apply drift correction to first waypoint if needed
                            if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift and not effective_auto_origin_mode:
                                px_0 += initial_position_drift.north_m
                                py_0 += initial_position_drift.east_m
                                pz_0 += initial_position_drift.down_m

                            # Convert current waypoint NED to GPS (this is our blend target)
                            blend_end_lat, blend_end_lon, blend_end_alt = pm.ned2geodetic(
                                px_0, py_0, pz_0,
                                origin_lat, origin_lon, origin_alt
                            )

                            logger.info(f"🔍 GPS CONVERSION:")
                            logger.info(f"   Input NED: ({px_0:.2f}, {py_0:.2f}, {pz_0:.2f})")
                            logger.info(f"   Origin: ({origin_lat:.8f}, {origin_lon:.8f}, {origin_alt:.2f})")
                            logger.info(f"   Output: ({blend_end_lat:.8f}, {blend_end_lon:.8f}, {blend_end_alt:.2f})")

                            blend_start_time = time.time()
                            blend_active = True

                            logger.info(f"🔀 === POSITION BLENDING INITIATED ===")
                            logger.info(f"   Start position: lat={blend_start_lat:.6f}°, lon={blend_start_lon:.6f}°, alt={blend_start_alt:.1f}m")
                            logger.info(f"   Target (waypoint {waypoint_index} at t={t_wp_0:.2f}s): lat={blend_end_lat:.6f}°, lon={blend_end_lon:.6f}°, alt={blend_end_alt:.1f}m")
                            logger.info(f"   Blend duration: {Params.BLEND_TRANSITION_DURATION_SEC}s")
                            logger.info(f"   Timeline synchronized: waypoint {waypoint_index}")

                else:
                    in_initial_climb = False

                # Update LED color for feedback
                led_controller.set_color(ledr, ledg, ledb)

                if in_initial_climb:
                    # Enhanced logging for initial climb start (once per flight)
                    # Only print when first entering climb (time < 0.1s to print once)
                    if time_in_climb < 0.1:
                        logger.info(f"=== INITIAL CLIMB STARTED ===")
                        logger.info(f"Mode: {Params.INITIAL_CLIMB_MODE}")
                        logger.info(f"Target altitude: {Params.INITIAL_CLIMB_ALTITUDE_THRESHOLD}m")
                        logger.info(f"Climb speed: {Params.INITIAL_CLIMB_VZ_DEFAULT} m/s")
                        logger.info(f"Initial trajectory waypoint: N={px:.2f}, E={py:.2f}, D={pz:.2f}")
                        logger.info(f"Waypoint index advances for sync, setpoints overridden with climb")

                    # BODY-frame climb or LOCAL-NED climb
                    # PHASE 2 FIX: Force BODY_VELOCITY mode in Phase 2 to climb straight UP
                    # without holding GPS position (which may be incorrect due to placement error)
                    use_body_velocity_climb = (
                        Params.INITIAL_CLIMB_MODE == "BODY_VELOCITY" or
                        effective_auto_origin_mode
                    )

                    if use_body_velocity_climb:
                        # Always use configured climb speed during initial climb phase
                        # Ignore CSV vz values which may contain numerical noise
                        vz_climb = Params.INITIAL_CLIMB_VZ_DEFAULT
                        if initial_climb_yaw is None:
                            initial_climb_yaw = raw_yaw if isinstance(raw_yaw, float) else 0.0

                        # Send body‐frame velocity setpoint
                        velocity_cmd = VelocityBodyYawspeed(0.0, 0.0, -vz_climb, 0.0)
                        await drone.offboard.set_velocity_body(velocity_cmd)

                        # Log climb progress periodically (every 1 second)
                        if waypoint_index % 100 == 0:
                            climb_mode_label = "BODY_VELOCITY (Phase 2 forced)" if effective_auto_origin_mode else "BODY_VELOCITY"
                            logger.info(f"🚁 CLIMBING: {climb_mode_label} | vz={-vz_climb:.2f} m/s | t={time_in_climb:.2f}s | alt={actual_alt:.2f}m")

                    # Keep waypoint_index advancing for swarm synchronization
                    # Setpoints overridden with climb commands, but timeline continues
                    waypoint_index += 1
                    continue

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

                    # Apply drift correction (but NOT in Phase 2 mode - waypoints are already absolute)
                    if Params.ENABLE_INITIAL_POSITION_CORRECTION and initial_position_drift and not effective_auto_origin_mode:
                        px = raw_px + initial_position_drift.north_m
                        py = raw_py + initial_position_drift.east_m
                        pz = raw_pz + initial_position_drift.down_m
                    else:
                        px, py, pz = raw_px, raw_py, raw_pz

                # --- (3) Compute Altitude & Convert NED → LLA ---
                current_alt_sp = -pz
                # Use PyMap3D's ned2geodetic (positional args):
                lla_lat, lla_lon, lla_alt = pm.ned2geodetic(
                    px, py, pz,
                    origin_lat, origin_lon, origin_alt
                )  # :contentReference[oaicite:15]{index=15}

                # --- (3.5) PHASE 2: Apply Position Blending ---
                if blend_active:
                    # Calculate blend progress (alpha: 0.0 → 1.0)
                    elapsed_blend = now - blend_start_time

                    if elapsed_blend < Params.BLEND_TRANSITION_DURATION_SEC:
                        # Still blending: interpolate in LLA space
                        alpha = elapsed_blend / Params.BLEND_TRANSITION_DURATION_SEC

                        # PHASE 2 FIX: Use fixed blend target (set at blend initiation)
                        # Linear interpolation from start position to timeline-synchronized waypoint
                        blended_lat = blend_start_lat + alpha * (blend_end_lat - blend_start_lat)
                        blended_lon = blend_start_lon + alpha * (blend_end_lon - blend_start_lon)
                        blended_alt = blend_start_alt + alpha * (blend_end_alt - blend_start_alt)

                        logger.debug(
                            f"🔀 Blending: α={alpha:.2f}, "
                            f"lat={blended_lat:.6f}°, lon={blended_lon:.6f}°, alt={blended_alt:.1f}m "
                            f"(target: timeline-synced waypoint)"
                        )

                        # Use blended position
                        lla_lat = blended_lat
                        lla_lon = blended_lon
                        lla_alt = blended_alt

                    else:
                        # Blending complete
                        blend_active = False
                        logger.info(f"✅ === POSITION BLENDING COMPLETED === after {elapsed_blend:.1f}s")
                        logger.info(f"   Now following corrected trajectory from shared drone show origin")

                # --- (4) Global vs. Local Branching ---
                if use_global_setpoints:
                    # Send GLOBAL setpoint (lat, lon, alt, yaw)
                    gp = PositionGlobalYaw(
                    lla_lat,
                    lla_lon,
                    lla_alt,
                    raw_yaw,
                    PositionGlobalYaw.AltitudeType.AMSL
                    )
                    #Other Options: RELATIVE , AMSL , TAKEOFF
                    # Log periodically (every 5 seconds) to reduce verbosity
                    if waypoint_index % 500 == 0:
                        logger.info(
                            f"🌍 GLOBAL | lat:{lla_lat:.6f}°, lon:{lla_lon:.6f}°, "
                            f"alt:{lla_alt:.2f}m, yaw:{raw_yaw:.1f}° | WP:{waypoint_index}/{total_waypoints}"
                        )
                    await drone.offboard.set_position_global(gp)
                else:
                    # Local NED setpoint
                    ln = PositionNedYaw(px, py, pz, raw_yaw)
                    # Log periodically (every 5 seconds) to reduce verbosity
                    if waypoint_index % 500 == 0:
                        logger.info(
                            f"📍 LOCAL | N:{px:.2f}m, E:{py:.2f}m, D:{pz:.2f}m (alt:{-pz:.2f}m), yaw:{raw_yaw:.1f}° | WP:{waypoint_index}/{total_waypoints}"
                        )

                    # Decide feedforward mode
                    if Params.FEEDFORWARD_VELOCITY_ENABLED and Params.FEEDFORWARD_ACCELERATION_ENABLED:
                        # Position+Velocity+Acceleration
                        velocity_setpoint     = VelocityNedYaw(vx, vy, vz, raw_yaw)
                        acceleration_setpoint = AccelerationNed(ax, ay, az)
                        await drone.offboard.set_position_velocity_acceleration_ned(
                            ln, velocity_setpoint, acceleration_setpoint
                        )
                    elif Params.FEEDFORWARD_VELOCITY_ENABLED:
                        # Position+Velocity only
                        velocity_setpoint = VelocityNedYaw(vx, vy, vz, raw_yaw)
                        await drone.offboard.set_position_velocity_ned(ln, velocity_setpoint)
                    else:
                        # Position‐only
                        await drone.offboard.set_position_ned(ln)

                led_controller.set_color(ledr, ledg, ledb)

                # --- (5) Progress & Landing Trigger ---
                time_to_end = waypoints[-1][0] - t_wp
                prog = (waypoint_index + 1) / total_waypoints
                logger.info(
                    f"WP {waypoint_index+1}/{total_waypoints}, "
                    f"progress {prog:.2%}, ETA {time_to_end:.2f}s, "
                    f"drift {drift_delta:.2f}s"
                )

                if (not trajectory_ends_high) and (prog >= Params.MISSION_PROGRESS_THRESHOLD):
                    if time_to_end <= Params.CONTROLLED_LANDING_TIME \
                       or current_alt_sp < Params.CONTROLLED_LANDING_ALTITUDE:
                        logger.info("Triggering controlled landing.")
                        await controlled_landing(drone)
                        landing_detected = True
                        break

                waypoint_index += 1

            # --- Case B: Ahead of schedule (drift_delta < 0) ---
            else:
                sleep_duration = t_wp - elapsed
                if sleep_duration > 0:
                    await asyncio.sleep(min(sleep_duration, AHEAD_SLEEP_STEP_SEC))
                else:
                    waypoint_index += 1

        except OffboardError as err:
            logger.error(f"Offboard error: {err}")
            led_controller.set_color(255, 0, 0)
            break
        except Exception:
            logger.exception("Error in trajectory loop.")
            led_controller.set_color(255, 0, 0)
            break

    # --- Post-trajectory Landing Handling ---
    if not landing_detected:
        if trajectory_ends_high:
            await stop_offboard_mode(drone)
            await perform_landing(drone)
            await wait_for_landing(drone)
        else:
            await controlled_landing(drone)

    logger.info("Mission complete.")
    led_controller.set_color(0, 255, 0)




async def controlled_landing(drone: System):
    """
    Perform controlled landing by sending descent commands and monitoring landing state.

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
    Wait for the drone to land after initiating landing.

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
    Perform the initial setup and connection for the drone.

    Returns:
        drone (System): MAVSDK drone system instance.
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


# ----------------------------- #
#  Phase 2: Origin Management   #
# ----------------------------- #

async def fetch_origin_with_fallback(drone: System):
    """
    Fetch drone show origin with multi-level fallback mechanism (Phase 2).

    Priority order:
    1. Try loading from command origin (sent with mission command from GCS)
    2. Try fetching from GCS server (network fetch)
    3. Try loading from local cache (previous fetch)
    4. Use current drone position (last resort with warning)

    Args:
        drone: MAVSDK System instance

    Returns:
        dict: Origin data with keys:
              - lat: float (latitude in degrees)
              - lon: float (longitude in degrees)
              - alt: float (altitude MSL in meters)
              - source: str ('command', 'gcs', 'cache', or 'current_position')

    Raises:
        ValueError: If all fetch attempts fail
    """
    logger = logging.getLogger(__name__)
    led = LEDController.get_instance()

    # Attempt 1: Check for origin sent with command (highest priority)
    # This is the most reliable as it's embedded in the mission command from GCS
    try:
        command_origin_file = origin_cache.CACHE_DIR / 'command_origin.json'
        if command_origin_file.exists():
            logger.info("🌍 Checking for origin from mission command...")
            with open(command_origin_file, 'r') as f:
                command_origin = json.load(f)

            if all(key in command_origin for key in ['lat', 'lon', 'alt']):
                logger.info(f"✅ Origin found in mission command")
                logger.info(f"   Latitude:  {command_origin['lat']:.6f}°")
                logger.info(f"   Longitude: {command_origin['lon']:.6f}°")
                logger.info(f"   Altitude:  {command_origin['alt']:.1f}m MSL")
                logger.info(f"   Source:    {command_origin.get('source', 'command')}")

                # Update main cache for future use
                origin_cache.save_origin_to_cache(command_origin)

                # Clean up command origin file after use
                command_origin_file.unlink()

                return {
                    'lat': float(command_origin['lat']),
                    'lon': float(command_origin['lon']),
                    'alt': float(command_origin['alt']),
                    'source': 'command'
                }
    except Exception as e:
        logger.debug(f"No command origin found: {e}")

    # Attempt 2: Fetch from GCS server
    try:
        logger.info("🌍 Fetching drone show origin from GCS...")
        gcs_url = f"http://{Params.GCS_IP}:5000/get-origin-for-drone"

        response = requests.get(
            gcs_url,
            timeout=Params.ORIGIN_FETCH_TIMEOUT_SEC
        )

        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Origin fetched from GCS successfully")
            logger.info(f"   Latitude:  {data['lat']:.6f}°")
            logger.info(f"   Longitude: {data['lon']:.6f}°")
            logger.info(f"   Altitude:  {data['alt']:.1f}m MSL")
            logger.info(f"   Source:    {data.get('source', 'unknown')}")

            # Save to cache for future use
            origin_cache.save_origin_to_cache(data)

            return {
                'lat': float(data['lat']),
                'lon': float(data['lon']),
                'alt': float(data['alt']),
                'source': 'gcs'
            }
        else:
            logger.warning(f"❌ GCS returned error: {response.status_code}")
            if response.status_code == 404:
                logger.warning("   Origin not set in GCS")

    except requests.exceptions.Timeout:
        logger.warning(f"❌ GCS origin fetch timeout after {Params.ORIGIN_FETCH_TIMEOUT_SEC}s")
    except requests.exceptions.ConnectionError:
        logger.warning(f"❌ Cannot connect to GCS at {Params.GCS_IP}:5000")
    except Exception as e:
        logger.warning(f"❌ GCS origin fetch failed: {e}")

    # Attempt 2: Load from local cache
    try:
        logger.info("🔄 Attempting to load origin from local cache...")
        cached = origin_cache.load_origin_from_cache()

        if cached:
            age_sec = origin_cache.get_cache_age_seconds()

            if age_sec is not None:
                age_min = age_sec / 60
                if age_sec < Params.ORIGIN_CACHE_STALENESS_WARNING_SEC:
                    logger.info(f"✅ Using cached origin (age: {age_min:.1f} minutes)")
                else:
                    logger.warning(f"⚠️  Using STALE cached origin (age: {age_min:.1f} minutes)")
                    logger.warning(f"   Consider setting fresh origin in GCS")

            logger.info(f"   Latitude:  {cached['lat']:.6f}°")
            logger.info(f"   Longitude: {cached['lon']:.6f}°")
            logger.info(f"   Altitude:  {cached['alt']:.1f}m MSL")

            led.set_color(255, 255, 0)  # Yellow = using cache

            return {
                'lat': float(cached['lat']),
                'lon': float(cached['lon']),
                'alt': float(cached['alt']),
                'source': 'cache'
            }
    except Exception as e:
        logger.warning(f"❌ Cache load failed: {e}")

    # Attempt 3: Use current position (last resort)
    try:
        logger.warning("⚠️⚠️⚠️ FALLBACK TO CURRENT POSITION - Origin not available!")
        logger.warning("   This means the drone will use its current GPS position as origin.")
        logger.warning("   Formation accuracy will depend on operator placement precision.")

        led.set_color(255, 165, 0)  # Orange = fallback mode

        async for pos in drone.telemetry.position():
            current_lat = pos.latitude_deg
            current_lon = pos.longitude_deg
            current_alt = pos.absolute_altitude_m

            logger.warning(f"   Using current position as origin:")
            logger.warning(f"   Latitude:  {current_lat:.6f}°")
            logger.warning(f"   Longitude: {current_lon:.6f}°")
            logger.warning(f"   Altitude:  {current_alt:.1f}m MSL")

            return {
                'lat': current_lat,
                'lon': current_lon,
                'alt': current_alt,
                'source': 'current_position'
            }

    except Exception as e:
        logger.error(f"❌ Failed to get current position: {e}")
        raise ValueError("All origin fetch attempts failed. Cannot proceed with flight.")


async def validate_drone_position(drone: System, origin: dict, config: dict):
    """
    Validate that drone's current position is within acceptable range of expected position.

    This safety check prevents flight if the drone is placed too far from where it should be
    according to config.csv offsets from the shared origin.

    Args:
        drone: MAVSDK System instance
        origin: Origin dict with lat, lon, alt keys
        config: Drone config dict with x (North) and y (East) offsets

    Returns:
        float: Horizontal deviation distance in meters

    Raises:
        ValueError: If deviation exceeds ORIGIN_DEVIATION_ABORT_THRESHOLD_M
    """
    logger = logging.getLogger(__name__)

    try:
        # Get current GPS position
        async for pos in drone.telemetry.position():
            current_lat = pos.latitude_deg
            current_lon = pos.longitude_deg
            current_alt = pos.absolute_altitude_m
            break

        # Calculate expected position based on config offsets from origin
        # config['x'] = North offset, config['y'] = East offset (NED system)
        expected_lat, expected_lon, expected_alt = pm.ned2geodetic(
            config['x'],  # North offset
            config['y'],  # East offset
            0,            # Use origin altitude as reference
            origin['lat'],
            origin['lon'],
            origin['alt']
        )

        # Calculate horizontal deviation (North and East components)
        ned_deviation = pm.geodetic2ned(
            current_lat, current_lon, 0,
            expected_lat, expected_lon, 0
        )

        # Calculate horizontal distance (ignore vertical for now)
        horizontal_deviation_m = (ned_deviation[0]**2 + ned_deviation[1]**2)**0.5

        # Log validation results
        logger.info("📍 Position Validation:")
        logger.info(f"   Expected position:  lat={expected_lat:.6f}°, lon={expected_lon:.6f}°")
        logger.info(f"   Current position:   lat={current_lat:.6f}°, lon={current_lon:.6f}°")
        logger.info(f"   Horizontal deviation: {horizontal_deviation_m:.2f}m")
        logger.info(f"   North offset:       {ned_deviation[0]:.2f}m")
        logger.info(f"   East offset:        {ned_deviation[1]:.2f}m")
        logger.info(f"   Safety threshold:   {Params.ORIGIN_DEVIATION_ABORT_THRESHOLD_M:.1f}m")

        # Check against threshold
        if horizontal_deviation_m > Params.ORIGIN_DEVIATION_ABORT_THRESHOLD_M:
            logger.error("❌ POSITION VALIDATION FAILED!")
            logger.error(f"   Deviation {horizontal_deviation_m:.1f}m exceeds threshold {Params.ORIGIN_DEVIATION_ABORT_THRESHOLD_M:.1f}m")
            logger.error(f"   This indicates the drone is placed in the wrong location.")
            logger.error(f"   Expected config offset: North={config['x']:.1f}m, East={config['y']:.1f}m")
            logger.error(f"   Please reposition the drone closer to the expected location.")
            raise ValueError(
                f"Position deviation {horizontal_deviation_m:.1f}m exceeds "
                f"safety threshold {Params.ORIGIN_DEVIATION_ABORT_THRESHOLD_M:.1f}m"
            )

        logger.info(f"✅ Position validation PASSED: {horizontal_deviation_m:.2f}m deviation (within {Params.ORIGIN_DEVIATION_ABORT_THRESHOLD_M:.1f}m threshold)")
        return horizontal_deviation_m

    except ValueError:
        # Re-raise validation failures
        raise
    except Exception as e:
        logger.error(f"❌ Position validation error: {e}")
        raise ValueError(f"Position validation failed: {e}")


async def pre_flight_checks(drone: System):
    """
    Perform pre-flight checks to ensure the drone is ready for flight, including:
    - Checking the health of the global and home position via MAVSDK
    - Fetching the GPS global origin using MAVSDK when health is valid
    - Implementing a fallback mechanism using current position if origin request fails
    
    Args:
        drone (System): MAVSDK drone system instance

    Returns:
        dict: GPS global origin data containing latitude, longitude, and altitude
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
            logger.info("Skipping GPS health checks (REQUIRE_GLOBAL_POSITION=False)")
            logger.info("This is normal for LOCAL mode or non-GPS operations")
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

    Args:
        drone (System): MAVSDK drone system instance.
        home_position (dict): Home position telemetry data in global coordinates.

    Returns:
        None
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

        # Step 5: Start offboard mode
        logger.info("Starting offboard mode.")
        await drone.offboard.start()

        # LED control will be managed by CSV waypoints during trajectory execution
        # Don't set status LED here as it interferes with synchronized show LEDs
        logger.info("Offboard mode started. LED control transferred to trajectory CSV colors.")

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
    The NED origin is automatically set when the drone arms (matches GPS_GLOBAL_ORIGIN).
    
    Returns:
        PositionNedYaw: Drift in NED coordinates or None if unavailable
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

    Args:
        drone (System): MAVSDK drone system instance.
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

    Returns:
        str: Path to mavsdk_server.
    """
    home_dir = os.path.expanduser("~")
    mavsdk_drone_show_dir = os.path.join(home_dir, "mavsdk_drone_show")
    mavsdk_server_path = os.path.join(mavsdk_drone_show_dir, "mavsdk_server")
    return mavsdk_server_path


def start_mavsdk_server(udp_port: int):
    """
    Start MAVSDK server instance for the drone.

    Args:
        udp_port (int): UDP port for MAVSDK server communication.

    Returns:
        subprocess.Popen: MAVSDK server subprocess if started successfully, else None.
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
    Wait until a port starts accepting TCP connections.

    Args:
        port (int): The port to check.
        host (str): The hostname to check.
        timeout (float): The maximum time to wait in seconds.

    Returns:
        bool: True if the port is open, False if the timeout was reached.
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

    Args:
        mavsdk_server (subprocess.Popen): The subprocess running the MAVSDK server.
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

    Args:
        mavsdk_server (subprocess.Popen): MAVSDK server subprocess.
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


async def run_drone(synchronized_start_time, custom_csv=None, auto_launch_position=False, auto_global_origin=None, use_global_setpoints=None, mission_type=None):
    """
    Run the drone with the provided configurations.

    Args:
        synchronized_start_time (float): Synchronized start time (UNIX timestamp).
        custom_csv (str): Name of the custom trajectory CSV file.
        auto_launch_position (bool): Flag to enable automated initial position extraction.
        auto_global_origin (bool or None): Phase 2: Enable auto global origin correction mode.
                                            If None, uses Params.AUTO_GLOBAL_ORIGIN_MODE.
                                            CLI/UI override takes precedence.
        use_global_setpoints (bool or None): Enable GLOBAL mode (True) or LOCAL mode (False).
                                            If None, uses Params.USE_GLOBAL_SETPOINTS.
        mission_type (int or None): Mission type (1=DRONE_SHOW_FROM_CSV, 3=CUSTOM_CSV, 106=HOVER_TEST).
                                    Required for Phase 2 strict filtering.
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

        # Give the server time to spin up
        await asyncio.sleep(2)

        # Step 2: Initial Setup and Connection
        drone = await initial_setup_and_connection()

        # Step 3: Pre-flight Checks
        home_position = await pre_flight_checks(drone)

        # Step 3.5: PHASE 2 - Determine effective modes
        # Priority: CLI/UI argument > Params defaults

        # Determine effective USE_GLOBAL_SETPOINTS (LOCAL vs GLOBAL mode)
        if use_global_setpoints is not None:
            effective_use_global_setpoints = use_global_setpoints
            logger.info(f"Using CLI/UI override: USE_GLOBAL_SETPOINTS = {effective_use_global_setpoints}")
        elif hasattr(Params, 'USE_GLOBAL_SETPOINTS'):
            effective_use_global_setpoints = Params.USE_GLOBAL_SETPOINTS
            logger.info(f"Using params.py default: USE_GLOBAL_SETPOINTS = {effective_use_global_setpoints}")
        else:
            effective_use_global_setpoints = True  # Default to GLOBAL
            logger.warning("USE_GLOBAL_SETPOINTS not defined in params.py, defaulting to True")

        # Determine effective AUTO_GLOBAL_ORIGIN_MODE (Phase 2 auto-correction)
        if auto_global_origin is not None:
            effective_auto_origin_mode = auto_global_origin
            logger.info(f"Using CLI/UI override: AUTO_GLOBAL_ORIGIN_MODE = {effective_auto_origin_mode}")
        elif hasattr(Params, 'AUTO_GLOBAL_ORIGIN_MODE'):
            effective_auto_origin_mode = Params.AUTO_GLOBAL_ORIGIN_MODE
            logger.info(f"Using params.py default: AUTO_GLOBAL_ORIGIN_MODE = {effective_auto_origin_mode}")
        else:
            effective_auto_origin_mode = False
            logger.warning("AUTO_GLOBAL_ORIGIN_MODE not defined in params.py, defaulting to False")

        # Mission type logging
        if mission_type is not None:
            mission_type_name = {1: "DRONE_SHOW_FROM_CSV", 3: "CUSTOM_CSV", 106: "HOVER_TEST"}.get(mission_type, f"UNKNOWN({mission_type})")
            logger.info(f"Mission type: {mission_type_name} ({mission_type})")
        else:
            logger.warning("Mission type not provided - Phase 2 filtering cannot be enforced")

        # Origin source tracking variable
        origin_source = None

        # --- PHASE 2: STRICT FILTERING ---
        # Phase 2 ONLY applies to DRONE_SHOW_FROM_CSV (mission_type=1) in GLOBAL mode
        if effective_auto_origin_mode and effective_use_global_setpoints:
            if mission_type != 1:
                logger.warning("=" * 70)
                logger.warning("⚠️  PHASE 2 RESTRICTION: Auto Global Origin Correction is ONLY")
                logger.warning("    supported for DRONE_SHOW_FROM_CSV missions (mission_type=1).")
                logger.warning(f"    Current mission type: {mission_type}")
                logger.warning("    Disabling Phase 2 auto-correction for this mission.")
                logger.warning("=" * 70)
                effective_auto_origin_mode = False

        # --- PHASE 2: ORIGIN FETCH AND VALIDATION ---
        if effective_auto_origin_mode and effective_use_global_setpoints:
            logger.info("=" * 70)
            logger.info("🌍 AUTO GLOBAL ORIGIN MODE: ENABLED (Phase 2)")
            logger.info("=" * 70)
            logger.info("This mode uses shared drone show origin from GCS for precise formation.")
            logger.info("Drones can be placed approximately; system auto-corrects after initial climb.")

            # Read drone config early (needed for position validation)
            HW_ID = read_hw_id()
            if HW_ID is None:
                logger.error("Failed to read HW ID; cannot validate position.")
                sys.exit(1)

            drone_config = read_config(CONFIG_CSV_NAME)
            if drone_config is None:
                logger.error("Drone config not found; cannot validate position.")
                sys.exit(1)

            logger.info(f"Drone HW_ID={HW_ID}, Position ID={drone_config.pos_id}")
            logger.info(f"Expected offset from origin: North={drone_config.initial_x:.1f}m, East={drone_config.initial_y:.1f}m")

            # Fetch shared origin with fallback
            try:
                origin_data = await fetch_origin_with_fallback(drone)
                origin_lat = origin_data['lat']
                origin_lon = origin_data['lon']
                origin_alt = origin_data['alt']
                origin_source = origin_data['source']

                logger.info(f"✅ Using drone show origin (source: {origin_source})")

                # Validate drone position (abort if too far from expected)
                if origin_source in ['command', 'gcs', 'cache']:
                    # Only validate if we have a proper origin (not current_position fallback)
                    try:
                        deviation = await validate_drone_position(
                            drone,
                            origin_data,
                            {'x': drone_config.initial_x, 'y': drone_config.initial_y}
                        )
                        logger.info(f"✅ Position validation passed with {deviation:.2f}m deviation")
                    except ValueError as e:
                        logger.error(f"❌ Position validation failed: {e}")
                        logger.error("ABORTING FLIGHT FOR SAFETY")
                        sys.exit(1)
                else:
                    logger.warning("⚠️  Skipping position validation (using current position as fallback origin)")

            except Exception as e:
                logger.error(f"❌ Failed to fetch origin: {e}")
                logger.error("Cannot proceed with Phase 2 mode. Consider disabling AUTO_GLOBAL_ORIGIN_MODE.")
                sys.exit(1)

        else:
            # LEGACY MODE: Manual operator placement (v3.7 behavior)
            if not effective_use_global_setpoints:
                logger.info("=" * 70)
                logger.info("🧭 LOCAL NED MODE (No GPS origin required)")
                logger.info("=" * 70)
            else:
                logger.info("=" * 70)
                logger.info("🌍 GLOBAL MODE: Manual Placement (v3.7 behavior)")
                logger.info("=" * 70)
                logger.info("Using drone's current GPS position as origin.")
                logger.info("Ensure drones are placed accurately at intended positions.")

            # Capture current position as launch origin (traditional method)
            origin_lat = origin_lon = origin_alt = None
            logger.info("Capturing launch position from telemetry...")
            async for pos in drone.telemetry.position():
                origin_lat = pos.latitude_deg
                origin_lon = pos.longitude_deg
                origin_alt = pos.absolute_altitude_m
                logger.info(
                    f"Launch position captured: "
                    f"lat={origin_lat:.6f}, lon={origin_lon:.6f}, alt={origin_alt:.2f}m"
                )
                break

            if origin_lat is None:
                logger.error("Failed to capture launch position from telemetry.")
                sys.exit(1)

            origin_source = 'launch_position'

        logger.info("=" * 70)

        # Step 4: Handle synchronized start time
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

        # Step 5: Arm and enter Offboard
        await arming_and_starting_offboard_mode(drone, home_position)

        # Step 6: Load and adjust trajectory
        if custom_csv:
            trajectory_filename = os.path.join(
                'shapes_sitl' if Params.sim_mode else 'shapes',
                custom_csv
            )

            # --- WAYPOINT ZEROING DECISION TREE ---
            # LOCAL mode: Always zero waypoints (use feedforward control)
            # GLOBAL manual: Always zero waypoints (traditional GPS origin)
            # GLOBAL Phase 2: NO zeroing (absolute offsets from shared origin)
            effective_auto_launch = auto_launch_position
            if not effective_use_global_setpoints:
                # LOCAL mode: Always zero (use first waypoint as origin)
                effective_auto_launch = True
                logger.info("LOCAL mode: Will zero first waypoint (feedforward control)")
            elif effective_auto_origin_mode:
                # GLOBAL Phase 2: NO zeroing (absolute waypoints)
                effective_auto_launch = False
                logger.info("GLOBAL Phase 2: Loading waypoints as absolute offsets (no zeroing)")
            else:
                # GLOBAL manual: Zero waypoints (traditional behavior)
                effective_auto_launch = True if auto_launch_position else False
                logger.info(f"GLOBAL manual: Zeroing waypoints (auto_launch={effective_auto_launch})")

            waypoints = read_trajectory_file(
                filename=trajectory_filename,
                auto_launch_position=effective_auto_launch
            )
            logger.info(f"Loaded custom CSV '{custom_csv}'.")
        else:
            # Read HW_ID and config if not already loaded (Phase 2 loads them earlier)
            if not ('HW_ID' in locals() and 'drone_config' in locals()):
                HW_ID = read_hw_id()
                if HW_ID is None:
                    logger.error("Failed to read HW ID; exiting.")
                    sys.exit(1)
                drone_config = read_config(CONFIG_CSV_NAME)
                if drone_config is None:
                    logger.error("Drone config not found; exiting.")
                    sys.exit(1)

            position_id = drone_config.pos_id
            trajectory_filename = os.path.join(
                'shapes_sitl' if Params.sim_mode else 'shapes',
                'swarm',
                'processed',
                f"Drone {position_id}.csv"
            )

            # --- WAYPOINT ZEROING DECISION TREE ---
            # LOCAL mode: Extract launch position from trajectory CSV first row
            # GLOBAL manual: Extract launch position from trajectory CSV first row
            # GLOBAL Phase 2: NO adjustment (absolute offsets from shared origin)
            if not effective_use_global_setpoints:
                # LOCAL mode: Extract from CSV first row
                effective_auto_launch = True
                logger.info("LOCAL mode: Extracting launch position from trajectory CSV first row")
            elif effective_auto_origin_mode:
                # GLOBAL Phase 2: NO adjustment (absolute waypoints)
                effective_auto_launch = False
                logger.info("GLOBAL Phase 2: Loading trajectory without waypoint adjustment")
                logger.info(f"Waypoints used as absolute offsets from drone show origin")
            else:
                # GLOBAL manual: Extract from CSV first row
                effective_auto_launch = True
                logger.info("GLOBAL manual: Extracting launch position from trajectory CSV first row")

            # Load waypoints with appropriate adjustment
            if effective_auto_origin_mode:
                # Phase 2: No adjustment (pass zeros to prevent subtraction)
                waypoints = read_trajectory_file(
                    filename=trajectory_filename,
                    auto_launch_position=False,
                    initial_x=0.0,
                    initial_y=0.0
                )
            else:
                # LOCAL and GLOBAL manual: Extract from CSV, pass zeros to prevent config interference
                # auto_launch_position=True will extract CSV first row and zero it
                waypoints = read_trajectory_file(
                    filename=trajectory_filename,
                    auto_launch_position=effective_auto_launch,
                    initial_x=0.0,  # Don't use config values - rely on CSV first row extraction
                    initial_y=0.0
                )
            logger.info(f"Loaded trajectory for Drone {position_id} ({len(waypoints)} waypoints).")

        # Step 7: Execute the show trajectory (now with global reference)
        await perform_trajectory(
            drone,
            waypoints,
            home_position,
            synchronized_start_time,
            origin_lat, origin_lon, origin_alt,
            effective_auto_origin_mode=effective_auto_origin_mode,
            origin_source=origin_source,
            use_global_setpoints=effective_use_global_setpoints
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
    Main function to run the drone.
    """
    # Configure logging
    configure_logging("drone_show")
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description='Drone Show Script')
    parser.add_argument('--start_time', type=float, help='Synchronized start UNIX time')
    parser.add_argument('--custom_csv', type=str, help='Name of the custom trajectory CSV file, e.g., active.csv')
    parser.add_argument(
        '--auto_launch_position',
        type=str2bool,
        nargs='?',
        const=True,
        default=None,
        help='Explicitly enable (True) or disable (False) automated initial position extraction from trajectory CSV.',
    )
    parser.add_argument(
        '--auto_global_origin',
        type=str2bool,
        nargs='?',
        const=True,
        default=None,
        help='Phase 2: Enable (True) or disable (False) auto global origin correction mode. Overrides Params.AUTO_GLOBAL_ORIGIN_MODE.',
    )
    parser.add_argument(
        '--use_global_setpoints',
        type=str2bool,
        nargs='?',
        const=True,
        default=None,
        help='Enable (True) for GLOBAL mode with GPS, disable (False) for LOCAL mode without GPS. Overrides Params.USE_GLOBAL_SETPOINTS.',
    )
    parser.add_argument(
        '--mission_type',
        type=int,
        default=None,
        help='Mission type: 1=DRONE_SHOW_FROM_CSV, 3=CUSTOM_CSV, 106=HOVER_TEST. Required for Phase 2 filtering.',
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

    # Get the synchronized start time
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

    # Determine if auto launch position is enabled
    if args.auto_launch_position is not None:
        auto_launch_position = args.auto_launch_position
        logger.info(f"Command-line argument '--auto_launch_position' set to {auto_launch_position}.")
    else:
        auto_launch_position = Params.AUTO_LAUNCH_POSITION
        logger.info(
            f"Using Params.AUTO_LAUNCH_POSITION = {Params.AUTO_LAUNCH_POSITION} "
            f"as '--auto_launch_position' was not provided."
        )

    # Display initial position configuration
    if auto_launch_position:
        logger.info("Initial Position: Auto Launch Position is ENABLED.")
        logger.info("Waypoints will be re-centered so the first waypoint becomes (0,0,0) in NED.")
    else:
        logger.info("Initial Position: Auto Launch Position is DISABLED.")
        logger.info("Positions will be shifted by config's initial_x and initial_y in NED.")

    # Determine if Phase 2 auto global origin mode is enabled
    if args.auto_global_origin is not None:
        auto_global_origin = args.auto_global_origin
        logger.info(f"Command-line argument '--auto_global_origin' set to {auto_global_origin}.")
    else:
        auto_global_origin = getattr(Params, 'AUTO_GLOBAL_ORIGIN_MODE', False)
        logger.info(
            f"Using Params.AUTO_GLOBAL_ORIGIN_MODE = {auto_global_origin} "
            f"as '--auto_global_origin' was not provided."
        )

    # Determine if LOCAL/GLOBAL mode is set
    if args.use_global_setpoints is not None:
        use_global_setpoints = args.use_global_setpoints
        logger.info(f"Command-line argument '--use_global_setpoints' set to {use_global_setpoints}.")
    else:
        use_global_setpoints = getattr(Params, 'USE_GLOBAL_SETPOINTS', True)
        logger.info(
            f"Using Params.USE_GLOBAL_SETPOINTS = {use_global_setpoints} "
            f"as '--use_global_setpoints' was not provided."
        )

    # Display mode configuration
    if use_global_setpoints:
        logger.info("Mode: GLOBAL (GPS-based positioning)")
    else:
        logger.info("Mode: LOCAL (NED feedforward control, no GPS required)")

    # Get mission type
    mission_type = args.mission_type
    if mission_type is not None:
        mission_name = {1: "DRONE_SHOW_FROM_CSV", 3: "CUSTOM_CSV", 106: "HOVER_TEST"}.get(mission_type, f"UNKNOWN({mission_type})")
        logger.info(f"Mission Type: {mission_name} ({mission_type})")
    else:
        logger.warning("Mission type not provided - Phase 2 filtering will not be enforced")

    # Display Phase 2 configuration
    if auto_global_origin:
        logger.info("=" * 70)
        logger.info("🌍 PHASE 2: Auto Global Origin Correction is ENABLED")
        logger.info("=" * 70)
        logger.info("Drones will fetch shared origin from GCS and auto-correct positions.")
        logger.info("This allows approximate operator placement with intelligent correction.")
    else:
        logger.info("🌍 PHASE 2: Auto Global Origin Correction is DISABLED")
        logger.info("Using traditional launch position capture (v3.7 behavior).")

    try:
        asyncio.run(
            run_drone(
                synchronized_start_time,
                custom_csv=args.custom_csv,
                auto_launch_position=auto_launch_position,
                auto_global_origin=auto_global_origin,
                use_global_setpoints=use_global_setpoints,
                mission_type=mission_type,
            )
        )
    except Exception:
        logger.exception("Unhandled exception in main.")
        sys.exit(1)


if __name__ == "__main__":
    main()