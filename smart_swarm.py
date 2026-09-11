# smart_swarm/smart_swarm.py
# Copyright (c) 2025 Alireza Ghaderi
# SPDX-License-Identifier: CC-BY-NC-SA-4.0
#
# This file is part of MAVSDK Drone Show
# https://github.com/alireza787b/mavsdk_drone_show
#
# Licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0
# For commercial licensing, contact: p30planets@gmail.com

"""Smart Swarm runtime orchestration for one MDS node.

The node resolves its saved GCS assignment, validates fresh leader and local
motion evidence, converts the configured formation target into the follower's
NED frame, and streams bounded commands through the cohesive follower motion
controller. Formation admission, velocity shaping, and source validity live in
focused ``smart_swarm_src`` modules; this file owns transport, MAVSDK lifecycle,
role changes, and failover to explicit PX4 HOLD.
"""


import os
import sys
import logging
import time
import asyncio
import csv
import subprocess
import socket
import psutil
import argparse
from typing import Optional
from collections import namedtuple
from mavsdk import System
from mavsdk.offboard import VelocityBodyYawspeed, VelocityNedYaw, OffboardError
from mavsdk.action import ActionError
from tenacity import retry, stop_after_attempt, wait_fixed
import numpy as np  # Added for numerical computations

from src.drone_config import ConfigLoader
from src.drone_api_routes import DRONE_SWARM_STATE_ROUTE, DRONE_WS_SWARM_STATE_ROUTE
from src.gcs_api_routes import (
    GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE,
    GCS_CONFIG_SWARM_ROUTE,
)
from src.led_controller import LEDController
from src.params import Params
from src.gcs_auth_client import gcs_auth_headers
from src.action_safety import (
    AIRBORNE_MIN_RELATIVE_ALTITUDE_M,
    observe_authoritative_vehicle_state,
)
from src.swarm_runtime_state import build_runtime_swarm_assignment, write_runtime_swarm_assignment, clear_runtime_swarm_assignment
from src.smart_swarm_contract import normalize_topology, topology_revision
from smart_swarm_src.control_authority import ControlAuthority
from smart_swarm_src.session_runtime import SwarmSessionRuntime
import aiohttp 

from smart_swarm_src.kalman_filter import LeaderKalmanFilter
from smart_swarm_src.failover import choose_leader_loss_response
from smart_swarm_src.assignment_recovery import LocalRecoveryOverride, recovery_assignment
from smart_swarm_src.follower_controller import FollowerMotionController
from smart_swarm_src.formation_guard import FormationGuard
from smart_swarm_src.motion_state_validity import (
    validate_leader_motion_sample,
    validate_own_motion_state,
)
from smart_swarm_src.runtime_shutdown import (
    SmartSwarmRuntimeLifecycle,
    VehicleHandoffResult,
    install_shutdown_signal_handlers,
)
from smart_swarm_src.velocity_command_shaper import (
    NedVelocityCommandShaper,
    VelocityCommandShapeError,
)
from smart_swarm_src.utils import (
    transform_body_to_nea,
    fetch_home_position,
    lla_to_ned
)

# Unified logging system
from mds_logging.drone import init_drone_logging
from mds_logging import get_logger, register_component
from mds_logging.cli import add_log_arguments, apply_log_args

# ----------------------------- #
#        Data Structures        #
# ----------------------------- #

DroneConfig = namedtuple(
    "DroneConfig", "hw_id pos_id x y ip mavlink_port"
)

SwarmConfig = namedtuple(
    "SwarmConfig", "hw_id follow offset_x offset_y offset_z frame"
)

# ----------------------------- #
#        Global Variables       #
# ----------------------------- #

HW_ID = None  # Hardware ID of the drone
DRONE_CONFIG = {}  # Drone configurations from config.json
SWARM_CONFIG = {}  # Swarm configurations from swarm.json
RECOVERY_OVERRIDE = LocalRecoveryOverride()
DRONE_STATE = {}  # Own drone's state
LEADER_STATE = {}  # Leader drone's state
OWN_STATE = {}  # Own drone's NED state
IS_LEADER = False  # Flag indicating if this drone is a leader
OFFSETS = {'x': 0.0, 'y': 0.0, 'z': 0.0}  # Offsets from the leader
FRAME = "ned"  # Coordinate frame for offsets: "ned" or "body"
LEADER_HW_ID = None  # Hardware ID of the leader drone
LEADER_IP = None  # IP address of the leader drone
LEADER_KALMAN_FILTER = None  # Kalman filter instance for leader state estimation
LEADER_HOME_POS = None  # Home position of the leader drone
OWN_HOME_POS = None  # Home position of own drone
REFERENCE_POS = None  # Reference position (latitude, longitude, altitude)


DRONE_INSTANCE = None  # MAVSDK drone instance
FOLLOWER_TASKS = {}  # Dictionary to hold tasks for follower mode (leader update, state update, control loop)

leader_unreachable_count = 0  # Initialize the counter for failed leader fetch attempts
max_unreachable_attempts = Params.SMART_SWARM_MAX_LEADER_UNREACHABLE_ATTEMPTS
LEADER_FAILOVER_IN_PROGRESS = False  # Prevent duplicate failover runs while leader health is degraded
LAST_LEADER_SAMPLE_REJECTION_CODE = None

# for leader-election cooldown
last_election_time = 0.0
FORMATION_CONFIG_VERSION = 0
LEADER_STREAM_TARGET_VERSION = 0


# ----------------------------- #
#         Helper Functions      #
# ----------------------------- #


def parse_float(field_value, default=0.0):
    """
    Safely convert a field value to float. If it's missing or invalid, log a warning and return default.
    """
    logger = logging.getLogger(__name__)
    try:
        return float(field_value)
    except (TypeError, ValueError):
        logger.warning(f"parse_float: Invalid or missing value '{field_value}', using default={default}")
        return default


def normalize_hw_id(hw_id):
    """Normalize a hardware ID for dict lookups. Returns None for leader/no-follow."""
    try:
        normalized = int(hw_id)
    except (TypeError, ValueError):
        return None

    if normalized <= 0:
        return None
    return str(normalized)


def get_drone_config_for_hw_id(hw_id):
    """Resolve a drone config entry regardless of string/int HW ID input."""
    normalized = normalize_hw_id(hw_id)
    if normalized is None:
        return None
    return DRONE_CONFIG.get(normalized)


def reset_leader_tracking():
    """Drop leader-estimation state when the follow target changes."""
    global LEADER_STATE, LEADER_KALMAN_FILTER, leader_unreachable_count, LEADER_FAILOVER_IN_PROGRESS
    global LAST_LEADER_SAMPLE_REJECTION_CODE
    LEADER_STATE.clear()
    LEADER_KALMAN_FILTER = LeaderKalmanFilter()
    leader_unreachable_count = 0
    LEADER_FAILOVER_IN_PROGRESS = False
    LAST_LEADER_SAMPLE_REJECTION_CODE = None


def bump_formation_config_version(reason: str):
    """Signal the control loop to reset/blend after a live formation change."""
    global FORMATION_CONFIG_VERSION
    FORMATION_CONFIG_VERSION += 1
    logging.getLogger(__name__).info(
        "Formation control version advanced to %s (%s).",
        FORMATION_CONFIG_VERSION,
        reason,
    )


def current_leader_stream_target():
    """Return the currently expected leader-stream target identity."""
    return LEADER_STREAM_TARGET_VERSION, LEADER_HW_ID, LEADER_IP


def leader_stream_target_changed(expected_version, expected_hw_id, expected_ip) -> bool:
    """Detect whether the leader stream must reconnect to a new target."""
    return (
        expected_version != LEADER_STREAM_TARGET_VERSION
        or expected_hw_id != LEADER_HW_ID
        or expected_ip != LEADER_IP
    )


RUNTIME_SESSION = None
CONTROL_AUTHORITY = None
RUNTIME_PHASE = "ready"
RUNTIME_DETAIL = ""
CONFIG_REFRESH_ERROR = None


def publish_runtime_assignment(entry=None, *, force_follow=None, active=True):
    """Publish the active Smart Swarm assignment for local telemetry/API readers."""
    logger = logging.getLogger(__name__)

    if HW_ID is None:
        return

    source = entry
    if source is None:
        source = SWARM_CONFIG.get(str(HW_ID), {})

    try:
        payload = build_runtime_swarm_assignment(
            HW_ID,
            source,
            force_follow=force_follow,
            session_id=RUNTIME_SESSION.command_id if RUNTIME_SESSION else None,
            active=active,
        )
        payload.update(phase=RUNTIME_PHASE, detail=RUNTIME_DETAIL)
        write_runtime_swarm_assignment(payload)
        logger.debug("Published runtime swarm assignment: %s", payload)
    except Exception as exc:
        logger.warning("Failed to publish runtime swarm assignment: %s", exc)


def should_use_local_ned(sample: dict) -> bool:
    """Decide whether local NED can be used directly for Smart Swarm tracking."""
    return bool(
        getattr(Params, "SMART_SWARM_USE_LOCAL_NED_WHEN_VALID", False)
        and sample.get("source_frame") == "local_ned"
        and sample.get("source_time_boot_ms", 0)
    )


def estimate_yaw_rate_deg_s(sample: dict, measurement_time: float) -> float:
    """Prefer streamed yaw-rate, otherwise estimate it from successive samples."""
    streamed = sample.get("yaw_rate_deg_s", None)
    if streamed is not None:
        try:
            return float(streamed)
        except (TypeError, ValueError):
            pass

    previous_yaw = LEADER_STATE.get("yaw")
    previous_time = LEADER_STATE.get("update_time")
    current_yaw = float(sample.get("yaw_deg", sample.get("yaw", 0.0)))

    if previous_yaw is None or previous_time is None:
        return 0.0

    dt = measurement_time - previous_time
    if dt <= 0:
        return 0.0

    delta = (current_yaw - previous_yaw + 180.0) % 360.0 - 180.0
    return delta / dt


def build_leader_measurement_from_sample(sample: dict):
    """Normalize a streamed/polled leader sample into the Smart Swarm internal measurement."""
    if should_use_local_ned(sample):
        leader_n = float(sample.get("local_position_north", 0.0))
        leader_e = float(sample.get("local_position_east", 0.0))
        leader_d = float(sample.get("local_position_down", 0.0))
        vel_n = float(sample.get("local_velocity_north", 0.0))
        vel_e = float(sample.get("local_velocity_east", 0.0))
        vel_d = float(sample.get("local_velocity_down", 0.0))
        source_frame = "local_ned"
    else:
        leader_n, leader_e, leader_d = lla_to_ned(
            sample['position_lat'],
            sample['position_long'],
            sample['position_alt'],
            REFERENCE_POS['latitude'],
            REFERENCE_POS['longitude'],
            REFERENCE_POS['altitude']
        )
        vel_n = float(sample.get('velocity_north', 0.0))
        vel_e = float(sample.get('velocity_east', 0.0))
        vel_d = float(sample.get('velocity_down', 0.0))
        source_frame = "global_lla_ned"

    return {
        'pos_n': leader_n,
        'pos_e': leader_e,
        'pos_d': leader_d,
        'vel_n': vel_n,
        'vel_e': vel_e,
        'vel_d': vel_d,
        'source_frame': source_frame,
    }


def apply_leader_state_sample(sample: dict, source: str) -> bool:
    """Apply one leader sample from WebSocket or HTTP fallback."""
    logger = logging.getLogger(__name__)
    global LEADER_STATE, leader_unreachable_count, LAST_LEADER_SAMPLE_REJECTION_CODE

    received_monotonic = time.monotonic()
    received_at_ms = int(time.time() * 1000)
    use_local_ned = should_use_local_ned(sample)
    validity = validate_leader_motion_sample(
        sample,
        expected_hw_id=LEADER_HW_ID,
        use_local_ned=use_local_ned,
        now_epoch_ms=received_at_ms,
        max_source_age_sec=float(Params.SMART_SWARM_SOURCE_MAX_AGE_SEC),
    )
    if not validity.valid:
        log = logger.warning if validity.code != LAST_LEADER_SAMPLE_REJECTION_CODE else logger.debug
        log(
            "Rejected leader motion sample via %s (%s): %s",
            source,
            validity.code,
            validity.reason,
        )
        LAST_LEADER_SAMPLE_REJECTION_CODE = validity.code
        return False

    if LAST_LEADER_SAMPLE_REJECTION_CODE is not None:
        logger.info("Leader motion source recovered via %s.", source)
        LAST_LEADER_SAMPLE_REJECTION_CODE = None

    source_timestamp_field = (
        'local_position_timestamp_ms' if use_local_ned else 'global_position_timestamp_ms'
    )
    motion_source_timestamp_ms = int(sample[source_timestamp_field])
    previous_motion_source_timestamp_ms = int(
        LEADER_STATE.get('motion_source_timestamp_ms', 0) or 0
    )
    if (
        previous_motion_source_timestamp_ms
        and motion_source_timestamp_ms <= previous_motion_source_timestamp_ms
    ):
        logger.debug(
            "Ignoring duplicate/out-of-order leader motion sample via %s (%s=%s <= %s).",
            source,
            source_timestamp_field,
            motion_source_timestamp_ms,
            previous_motion_source_timestamp_ms,
        )
        return False

    source_update_monotonic = received_monotonic - float(validity.age_sec or 0.0)
    # The existing estimator advances its state clock on every control-loop
    # prediction, so delayed/out-of-sequence updates cannot be replayed at the
    # producer timestamp. Keep estimator time monotonic at local receipt while
    # using the independent source clock below for motion freshness/failover.
    measurement_time = received_monotonic

    stream_seq = int(sample.get('stream_seq', 0) or 0)
    telemetry_timestamp_ms = int(sample.get('telemetry_timestamp_ms', 0) or 0)

    previous_seq = int(LEADER_STATE.get('stream_seq', 0) or 0)
    previous_ts_ms = int(LEADER_STATE.get('telemetry_timestamp_ms', 0) or 0)
    if stream_seq and previous_seq and stream_seq <= previous_seq and telemetry_timestamp_ms <= previous_ts_ms:
        logger.debug(
            "Ignoring duplicate/out-of-order leader sample via %s (seq=%s ts_ms=%s <= seq=%s ts_ms=%s).",
            source,
            stream_seq,
            telemetry_timestamp_ms,
            previous_seq,
            previous_ts_ms,
        )
        return False

    if stream_seq and previous_seq and stream_seq > (previous_seq + 1):
        logger.debug(
            "Leader sample gap detected via %s: seq advanced from %s to %s.",
            source,
            previous_seq,
            stream_seq,
        )

    source_time_boot_ms = int(sample.get('source_time_boot_ms', 0) or 0)
    previous_boot_ms = int(LEADER_STATE.get('source_time_boot_ms', 0) or 0)
    if source_time_boot_ms and previous_boot_ms and source_time_boot_ms < previous_boot_ms:
        logger.warning(
            "Leader PX4 boot clock rolled back from %sms to %sms; resetting estimator state.",
            previous_boot_ms,
            source_time_boot_ms,
        )
        reset_leader_tracking()

    measurement = build_leader_measurement_from_sample(sample)
    yaw_deg = float(sample.get('yaw_deg', sample.get('yaw', 0.0)))
    yaw_rate_deg_s = estimate_yaw_rate_deg_s(sample, measurement_time)
    sample_age_ms = max(0, received_at_ms - int(sample.get('emitted_at_ms', received_at_ms) or received_at_ms))

    LEADER_STATE.update({
        **measurement,
        'yaw': yaw_deg,
        'yaw_rate_deg_s': yaw_rate_deg_s,
        'update_time': source_update_monotonic,
        'received_monotonic': received_monotonic,
        'stream_seq': stream_seq,
        'telemetry_timestamp_ms': telemetry_timestamp_ms,
        'received_at_ms': received_at_ms,
        'emitted_at_ms': int(sample.get('emitted_at_ms', received_at_ms) or received_at_ms),
        'sample_age_ms': sample_age_ms,
        'source_time_boot_ms': source_time_boot_ms,
        'motion_source_timestamp_ms': motion_source_timestamp_ms,
        'source_age_sec': validity.age_sec,
        'transport': source,
    })

    LEADER_KALMAN_FILTER.update(measurement, measurement_time)
    leader_unreachable_count = 0
    logger.debug(
        "Leader sample via %s applied: seq=%s age_ms=%s frame=%s pos=(%.2f, %.2f, %.2f) vel=(%.2f, %.2f, %.2f)",
        source,
        stream_seq,
        sample_age_ms,
        measurement['source_frame'],
        measurement['pos_n'],
        measurement['pos_e'],
        measurement['pos_d'],
        measurement['vel_n'],
        measurement['vel_e'],
        measurement['vel_d'],
    )
    return True


def assign_leader_target(new_leader_hw_id):
    """Apply a new follow target and reset estimation state."""
    global LEADER_HW_ID, LEADER_IP, LEADER_STREAM_TARGET_VERSION

    normalized = normalize_hw_id(new_leader_hw_id)
    if normalized is None:
        target_changed = LEADER_HW_ID is not None or LEADER_IP is not None
        LEADER_HW_ID = None
        LEADER_IP = None
        if target_changed:
            LEADER_STREAM_TARGET_VERSION += 1
            reset_leader_tracking()
        return None

    leader_cfg = get_drone_config_for_hw_id(normalized)
    if leader_cfg is None:
        return None

    new_ip = leader_cfg['ip']
    target_changed = normalized != LEADER_HW_ID or new_ip != LEADER_IP
    LEADER_HW_ID = normalized
    LEADER_IP = new_ip
    if target_changed:
        LEADER_STREAM_TARGET_VERSION += 1
        reset_leader_tracking()
    return leader_cfg


FOLLOWER_MOTION_LEASE = None


async def cancel_follower_tasks(logger):
    """Cancel follower-mode tasks without leaking unfinished coroutines."""
    global FOLLOWER_TASKS, FOLLOWER_MOTION_LEASE

    if not FOLLOWER_TASKS:
        if FOLLOWER_MOTION_LEASE is not None:
            FOLLOWER_MOTION_LEASE.release()
            FOLLOWER_MOTION_LEASE = None
        return

    current_task = asyncio.current_task()
    tasks = list(FOLLOWER_TASKS.items())

    # Signal every sibling before awaiting any one of them. A single task with
    # slow cancellation must never leave another control/setpoint producer
    # running during the shutdown handoff.
    for task_name, task in tasks:
        if task is current_task:
            logger.debug("Follower task %s is completing its own transition.", task_name)
            continue
        if not task.done():
            task.cancel()

    for task_name, task in tasks:
        if task is current_task:
            continue
        try:
            await task
        except asyncio.CancelledError:
            logger.debug("Cancelled follower task: %s", task_name)
        except Exception:
            logger.exception("Follower task %s exited with an error during cancellation", task_name)
    FOLLOWER_TASKS.clear()
    if FOLLOWER_MOTION_LEASE is not None:
        FOLLOWER_MOTION_LEASE.release()
        FOLLOWER_MOTION_LEASE = None


def _follower_task_missing(task_name: str) -> bool:
    task = FOLLOWER_TASKS.get(task_name)
    return task is None or task.done()


async def ensure_offboard_active_for_follower(drone: System, logger, reason: str) -> bool:
    """Start follower offboard mode if it is not already active."""
    global FOLLOWER_MOTION_LEASE
    from src.mavsdk_server_ownership import MotionControlLease
    if FOLLOWER_MOTION_LEASE is None:
        FOLLOWER_MOTION_LEASE = MotionControlLease.acquire(Params.DEFAULT_GRPC_PORT)
        if FOLLOWER_MOTION_LEASE is None:
            return False
    try:
        if CONTROL_AUTHORITY is not None and not CONTROL_AUTHORITY.expect("OFFBOARD"):
            return False
        await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        if CONTROL_AUTHORITY is not None and CONTROL_AUTHORITY.takeover_reason:
            return False
        await drone.offboard.start()
        if CONTROL_AUTHORITY is not None:
            deadline = time.monotonic() + 3.0
            while not CONTROL_AUTHORITY.owns_fresh_offboard():
                if CONTROL_AUTHORITY.takeover_reason or time.monotonic() > deadline:
                    return False
                await asyncio.sleep(0.05)
        logger.info("Follower offboard control active (%s).", reason)
        return True
    except OffboardError as exc:
        message = str(exc).lower()
        if "already" in message and "offboard" in message:
            logger.debug("Follower offboard control already active (%s).", reason)
            return CONTROL_AUTHORITY is None or CONTROL_AUTHORITY.owns_fresh_offboard()
        logger.error("Failed to start follower offboard control (%s): %s", reason, exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error while starting follower offboard control (%s): %s", reason, exc)
        return False


async def ensure_follower_runtime(drone: System, logger, reason: str) -> bool:
    """Ensure the follower control runtime is fully active and recover crashed tasks."""
    if not await ensure_offboard_active_for_follower(drone, logger, reason):
        return False

    if _follower_task_missing('leader_update_task'):
        FOLLOWER_TASKS['leader_update_task'] = asyncio.create_task(update_leader_state())
    if _follower_task_missing('own_state_task'):
        FOLLOWER_TASKS['own_state_task'] = asyncio.create_task(update_own_state(drone))
    if _follower_task_missing('own_attitude_task'):
        FOLLOWER_TASKS['own_attitude_task'] = asyncio.create_task(update_own_attitude(drone))
    if _follower_task_missing('control_task'):
        FOLLOWER_TASKS['control_task'] = asyncio.create_task(control_loop(drone))
    return True


async def handle_leader_unavailability(drone: System, logger, reason: str):
    """Run one failover sequence at a time when leader health is lost."""
    global LEADER_FAILOVER_IN_PROGRESS, RUNTIME_PHASE, RUNTIME_DETAIL

    if CONTROL_AUTHORITY is not None and CONTROL_AUTHORITY.takeover_reason:
        return
    if LEADER_FAILOVER_IN_PROGRESS:
        logger.debug("Leader failover already in progress (%s).", reason)
        return

    LEADER_FAILOVER_IN_PROGRESS = True
    RUNTIME_PHASE, RUNTIME_DETAIL = "holding", "Leader unavailable; recovering the follow chain"
    try:
        await execute_failsafe(drone, reason=reason)
        await elect_new_leader()
    finally:
        LEADER_FAILOVER_IN_PROGRESS = False


async def transition_to_leader_mode(drone: System, logger, reason: str):
    """Stop follower control and leave the vehicle in an explicit leader-safe HOLD state."""
    global IS_LEADER

    await execute_failsafe(drone, reason=reason)
    IS_LEADER = True
    assign_leader_target(0)
    await cancel_follower_tasks(logger)

    publish_runtime_assignment(force_follow=0)


async def transition_to_follower_mode(drone: System, new_leader_hw_id, logger, reason: str):
    """Start follower-mode tasks against a validated leader target."""
    global IS_LEADER, RUNTIME_PHASE, RUNTIME_DETAIL

    leader_cfg = assign_leader_target(new_leader_hw_id)
    if leader_cfg is None:
        logger.error("[Periodic Update] Leader config missing for HW_ID=%s", new_leader_hw_id)
        return False

    IS_LEADER = False
    publish_runtime_assignment(force_follow=new_leader_hw_id)
    logger.info("[Periodic Update] Ensuring follower runtime (%s).", reason)
    # Publishing the follower assignment prevents admission of another leader
    # action. An already-running borrowed action keeps movement authority until
    # its cleanup completes. Do not seed Offboard or replace its commands.
    RUNTIME_PHASE = "holding"
    RUNTIME_DETAIL = "Waiting for the current movement to finish"
    from src.mavsdk_server_ownership import MotionControlLease
    global FOLLOWER_MOTION_LEASE
    if FOLLOWER_MOTION_LEASE is None:
        FOLLOWER_MOTION_LEASE = MotionControlLease.acquire(Params.DEFAULT_GRPC_PORT)
        if FOLLOWER_MOTION_LEASE is None:
            return False
    RUNTIME_DETAIL = "Joining formation"
    return await ensure_follower_runtime(drone, logger, reason)

def read_config(filename: str):
    """
    Reads the drone configurations from the config JSON file and populates DRONE_CONFIG.

    Note: x,y positions now come from trajectory CSV files (single source of truth),
    not from config.json.

    Args:
        filename (str): Path to the config JSON file.
    """
    logger = logging.getLogger(__name__)
    global DRONE_CONFIG
    try:
        import json
        with open(filename, 'r') as f:
            data = json.load(f)
        entries = data.get('drones', data) if isinstance(data, dict) else data
        for entry in entries:
            try:
                hw_id = str(int(entry["hw_id"]))
                pos_id = int(entry["pos_id"])

                # Get position from trajectory CSV (single source of truth)
                base_dir = 'shapes_sitl' if Params.sim_mode else 'shapes'
                trajectory_file = os.path.join(
                    os.path.dirname(__file__),  # Project root
                    base_dir,
                    'swarm',
                    'processed',
                    f"Drone {pos_id}.csv"
                )

                x, y = 0.0, 0.0  # Default values
                try:
                    if os.path.exists(trajectory_file):
                        with open(trajectory_file, 'r') as traj_f:
                            traj_reader = csv.DictReader(traj_f)
                            first_waypoint = next(traj_reader, None)
                            if first_waypoint:
                                x = float(first_waypoint.get('px', 0))  # North
                                y = float(first_waypoint.get('py', 0))  # East
                            else:
                                logger.warning(f"Trajectory file empty for pos_id={pos_id}")
                    else:
                        logger.warning(f"Trajectory file not found for pos_id={pos_id}: {trajectory_file}")
                except Exception as e:
                    logger.error(f"Error reading trajectory for pos_id={pos_id}: {e}")

                DRONE_CONFIG[hw_id] = {
                    'hw_id': hw_id,
                    'pos_id': pos_id,
                    'x': x,
                    'y': y,
                    'ip': entry["ip"],
                    'mavlink_port': int(entry["mavlink_port"]),
                }
            except ValueError as ve:
                logger.error(f"Invalid data type in config file entry: {entry}. Error: {ve}")
        logger.info(f"Read {len(DRONE_CONFIG)} drone configurations from '{filename}' with positions from trajectory CSV.")
    except FileNotFoundError:
        logger.exception(f"Config file '{filename}' not found.")
        sys.exit(1)
    except Exception:
        logger.exception(f"Error reading config file '{filename}'.")
        sys.exit(1)

def read_swarm(filename: str):
    """
    Reads the swarm configurations from the swarm JSON file and populates SWARM_CONFIG.

    Args:
        filename (str): Path to the swarm JSON file.
    """
    logger = logging.getLogger(__name__)
    try:
        import json
        with open(filename, 'r') as f:
            data = json.load(f)
        entries = data.get('assignments', data) if isinstance(data, dict) else data
        replace_swarm_config(entries, source_name=f"local file '{filename}'", announce_level=logging.INFO)
    except FileNotFoundError:
        logger.exception(f"Swarm file '{filename}' not found.")
        sys.exit(1)
    except Exception:
        logger.exception(f"Error reading swarm file '{filename}'.")
        sys.exit(1)


def parse_swarm_entries(entries):
    """Parse raw swarm assignment entries into the normalized in-memory map."""
    logger = logging.getLogger(__name__)
    parsed = {}
    for entry in entries:
        try:
            hw_id = str(int(entry["hw_id"]))
            parsed[hw_id] = {
                'hw_id': hw_id,
                'follow': int(entry["follow"]),
                'offset_x': float(entry["offset_x"]),
                'offset_y': float(entry["offset_y"]),
                'offset_z': float(entry["offset_z"]),
                'frame': str(entry.get("frame", "ned")),
            }
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Invalid swarm entry %s. Error: %s", entry, exc)
    return parsed


def replace_swarm_config(entries, source_name: str, announce_level=logging.DEBUG):
    """Replace the global swarm assignment map from a raw entry list."""
    global SWARM_CONFIG

    SWARM_CONFIG.clear()
    SWARM_CONFIG.update(parse_swarm_entries(entries))
    logging.getLogger(__name__).log(
        announce_level,
        "Loaded %d swarm configurations from %s.",
        len(SWARM_CONFIG),
        source_name,
    )


async def refresh_swarm_config_from_gcs(logger, source_label: str, session: Optional[aiohttp.ClientSession] = None):
    """
    Refresh swarm assignments from GCS.

    Returns True when the GCS snapshot was fetched and applied, False when the
    local swarm file remains in effect.
    """
    global CONFIG_REFRESH_ERROR
    state_url = f"http://{Params.GCS_IP}:{Params.gcs_api_port}{GCS_CONFIG_SWARM_ROUTE}"
    owns_session = session is None
    active_session = session

    try:
        if active_session is None:
            active_session = aiohttp.ClientSession()

        timeout = aiohttp.ClientTimeout(
            total=float(Params.SMART_SWARM_GCS_CONFIG_TIMEOUT_SEC)
        )
        async with active_session.get(
            state_url,
            headers=gcs_auth_headers(),
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            api_data = await resp.json()

        entries = api_data.get("assignments", api_data) if isinstance(api_data, dict) else api_data
        entries = normalize_topology(entries)  # reject malformed snapshots atomically
        if source_label != "startup" and RECOVERY_OVERRIDE.assignment is not None:
            # Compare parsed slots so JSON numeric/string ID formatting cannot
            # accidentally clear the local recovery decision.
            incoming = parse_swarm_entries(entries)
            own_key = str(HW_ID)
            if own_key in incoming:
                incoming[own_key] = RECOVERY_OVERRIDE.resolve(incoming[own_key])
            entries = list(incoming.values())
        if source_label == "startup" and RUNTIME_SESSION and RUNTIME_SESSION.snapshot:
            if topology_revision(entries) != RUNTIME_SESSION.snapshot.revision:
                raise RuntimeError("Swarm configuration changed after command confirmation")
        replace_swarm_config(
            entries,
            source_name=f"GCS API ({source_label})",
            announce_level=logging.INFO if source_label == "startup" else logging.DEBUG,
        )
        if CONFIG_REFRESH_ERROR:
            logger.info("Swarm configuration refresh recovered")
        CONFIG_REFRESH_ERROR = None
        return True
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        log = logger.warning if failure != CONFIG_REFRESH_ERROR else logger.debug
        log(
            "[%s] Failed to refresh swarm configuration from GCS; continuing with local swarm file. Error: %s",
            source_label,
            exc,
        )
        CONFIG_REFRESH_ERROR = failure
        return False
    finally:
        if owns_session and active_session is not None:
            await active_session.close()

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

# ----------------------------- #
#       MAVSDK Server Control   #
# ----------------------------- #

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
            logger.info(f"MAVSDK server already running on port {Params.DEFAULT_GRPC_PORT}. Terminating...")
            try:
                psutil.Process(pid).terminate()
                psutil.Process(pid).wait(timeout=5)
                logger.info(f"Terminated existing MAVSDK server with PID: {pid}")
            except psutil.NoSuchProcess:
                logger.warning(f"No process found with PID: {pid} to terminate.")
            except psutil.TimeoutExpired:
                logger.warning(f"Process with PID: {pid} did not terminate gracefully. Killing it.")
                psutil.Process(pid).kill()
                psutil.Process(pid).wait()
                logger.info(f"Killed MAVSDK server with PID: {pid}")

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
            stderr=subprocess.PIPE
        )
        logger.info(
            f"MAVSDK server started with gRPC port {Params.DEFAULT_GRPC_PORT} and UDP port {udp_port}."
        )

        # Optionally, you can start logging the MAVSDK server output asynchronously
        asyncio.create_task(log_mavsdk_output(mavsdk_server))

        # Wait until the server is listening on the gRPC port
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
        logger.exception("Error starting MAVSDK server")
        return None

def check_mavsdk_server_running(port):
    """
    Checks if the MAVSDK server is running on the specified gRPC port.

    Args:
        port (int): The gRPC port to check.

    Returns:
        tuple: (is_running (bool), pid (int or None))
    """
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def wait_for_port(port, host='localhost', timeout=Params.PRE_FLIGHT_TIMEOUT):
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
        logger.exception("Error while reading MAVSDK server stdout")

    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stderr.readline)
            if not line:
                break
            logger.error(f"MAVSDK Server Error: {line.decode().strip()}")
    except Exception:
        logger.exception("Error while reading MAVSDK server stderr")

def stop_mavsdk_server(mavsdk_server, timeout_sec: float = 5.0):
    """
    Stop the MAVSDK server instance.

    Args:
        mavsdk_server (subprocess.Popen): MAVSDK server subprocess.
        timeout_sec: Grace period before the server is force-stopped.
    """
    logger = logging.getLogger(__name__)
    try:
        if mavsdk_server.poll() is None:
            logger.info("Stopping MAVSDK server...")
            mavsdk_server.terminate()
            try:
                mavsdk_server.wait(timeout=max(0.01, float(timeout_sec)))
                logger.info("MAVSDK server terminated gracefully.")
            except subprocess.TimeoutExpired:
                logger.warning("MAVSDK server did not terminate gracefully. Killing it.")
                mavsdk_server.kill()
                mavsdk_server.wait()
                logger.info("MAVSDK server killed forcefully.")
        else:
            logger.debug("MAVSDK server has already terminated.")
    except Exception:
        logger.exception("Error stopping MAVSDK server")


async def update_swarm_config_periodically(drone):
    """
    Periodically fetches the swarm configuration from the GCS API endpoint and updates
    global parameters such as role, formation offsets, and leader information.

    If a role change is detected (e.g., switching from follower to leader or vice versa),
    it starts or cancels follower-specific tasks accordingly.

    NOTE: Requires Params.GCS_IP and Params.gcs_api_port to be set.
    """
    global SWARM_CONFIG, IS_LEADER, OFFSETS, FRAME
    global LEADER_HW_ID, LEADER_IP, LEADER_KALMAN_FILTER, FOLLOWER_TASKS
    global HW_ID

    logger = logging.getLogger(__name__)

    str_hw_id = str(HW_ID)
    if not DRONE_CONFIG.get(str_hw_id):
        logger.error(f"[Periodic Update] Cannot resolve drone config for HW_ID={HW_ID}")
        return

    # Shared session for connection reuse
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                if LEADER_FAILOVER_IN_PROGRESS:
                    await asyncio.sleep(0.25)
                    continue
                logger.debug("[Periodic Update] Checking swarm configuration")
                refreshed = await refresh_swarm_config_from_gcs(
                    logger,
                    source_label="periodic update",
                    session=session,
                )
                if not refreshed:
                    await asyncio.sleep(Params.SMART_SWARM_CONFIG_REFRESH_INTERVAL_SEC)
                    continue

                # Grab this drone's new config
                new_cfg = SWARM_CONFIG.get(str(HW_ID))
                if new_cfg is None:
                    logger.error(f"[Periodic Update] No swarm entry for HW_ID={HW_ID}")
                else:
                    publish_runtime_assignment(new_cfg)
                    config_changed = False
                    # Determine new role/offsets/frame
                    new_offsets     = {
                        'x':   new_cfg['offset_x'],
                        'y':   new_cfg['offset_y'],
                        'z':   new_cfg['offset_z']
                    }
                    new_frame       = new_cfg['frame']
                    new_leader      = new_cfg['follow']
                    new_is_leader   = (new_leader == 0)

                    # ROLE CHANGE?
                    if new_is_leader != IS_LEADER:
                        logger.info(
                            "[Periodic Update] Role change: %s → %s",
                            "Leader" if IS_LEADER else "Follower",
                            "Leader" if new_is_leader else "Follower"
                        )
                        config_changed = True

                        if new_is_leader:
                            await transition_to_leader_mode(drone, logger, "config update")
                        else:
                            await transition_to_follower_mode(drone, new_leader, logger, "config update")
                    elif not new_is_leader and _follower_task_missing('control_task'):
                        # A role change can wait behind a leader action. Retry
                        # against the latest assignment, not a stale queued one.
                        await transition_to_follower_mode(drone, new_leader, logger, "pending role change")

                    # Handle leader change if drone is a follower
                    if not new_is_leader:
                        new_leader_hw_id = normalize_hw_id(new_leader)
                        if new_leader_hw_id != LEADER_HW_ID:
                            logger.info(f"[Periodic Update] Leader change detected. Following new leader {new_leader}.")
                            config_changed = True
                            leader_cfg = assign_leader_target(new_leader)
                            if not leader_cfg:
                                logger.error("[Periodic Update] Leader config missing for HW_ID=%s", LEADER_HW_ID)
                            else:
                                logger.info(f"[Periodic Update] Following new leader at {LEADER_IP}")

                    # OFFSET CHANGE?
                    if new_offsets != OFFSETS:
                        logger.info(
                            "[Periodic Update] Offsets changed: %s → %s",
                            OFFSETS, new_offsets
                        )
                        config_changed = True
                        OFFSETS.update(new_offsets)

                    # FRAME CHANGE?
                    if new_frame != FRAME:
                        logger.info(
                            "[Periodic Update] Frame changed: %s → %s",
                            FRAME, new_frame
                        )
                        config_changed = True
                        FRAME = new_frame

                    if config_changed:
                        bump_formation_config_version("swarm config update")

            except Exception as e:
                logger.exception(f"[Periodic Update] Error fetching/updating swarm config: {e}")

            # Wait before next poll
            await asyncio.sleep(Params.SMART_SWARM_CONFIG_REFRESH_INTERVAL_SEC)



# ----------------------------- #
#    Leader State Update Task   #
# ----------------------------- #

async def update_leader_state():
    """
    Maintain leader state using the dedicated Smart Swarm stream with HTTP fallback.
    """
    logger = logging.getLogger(__name__)
    global leader_unreachable_count, max_unreachable_attempts

    def state_url(target_ip: str) -> str:
        return f"http://{target_ip}:{Params.drone_api_port}{DRONE_SWARM_STATE_ROUTE}"

    def ws_url(target_ip: str) -> str:
        return f"http://{target_ip}:{Params.drone_api_port}{DRONE_WS_SWARM_STATE_ROUTE}".replace("http://", "ws://", 1)

    async def consume_http_fallback(window_sec: float, target_version: int, target_hw_id: str | None, target_ip: str) -> None:
        global leader_unreachable_count
        poll_interval = 1.0 / max(1.0, float(Params.SMART_SWARM_HTTP_FALLBACK_RATE_HZ))
        end_time = time.monotonic() + max(window_sec, poll_interval)
        timeout = aiohttp.ClientTimeout(
            total=float(Params.SMART_SWARM_LEADER_STATE_TIMEOUT_SEC)
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while time.monotonic() < end_time:
                if leader_stream_target_changed(target_version, target_hw_id, target_ip):
                    logger.info(
                        "Leader fallback target changed from %s@%s to %s@%s; reconnecting.",
                        target_hw_id,
                        target_ip,
                        LEADER_HW_ID,
                        LEADER_IP,
                    )
                    return
                try:
                    async with session.get(state_url(target_ip)) as response:
                        if response.status != 200:
                            raise aiohttp.ClientResponseError(
                                response.request_info,
                                response.history,
                                status=response.status,
                                message=f"Leader swarm-state fetch failed with HTTP {response.status}",
                                headers=response.headers,
                            )
                        data = await response.json()
                    applied = apply_leader_state_sample(data, "http-fallback")
                    if not applied:
                        leader_unreachable_count += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    leader_unreachable_count += 1
                    logger.debug(
                        "Leader fallback fetch failed (%s/%s): %s",
                        leader_unreachable_count,
                        max_unreachable_attempts,
                        exc,
                    )
                if leader_unreachable_count >= max_unreachable_attempts and DRONE_INSTANCE is not None:
                    logger.warning(
                        "Leader fallback path degraded for %s attempts; the control loop will hold zero and own failover timing.",
                        leader_unreachable_count,
                    )
                await asyncio.sleep(poll_interval)

    use_stream = bool(getattr(Params, "SMART_SWARM_USE_REALTIME_STREAM", True))
    use_http_fallback = bool(getattr(Params, "SMART_SWARM_ENABLE_HTTP_FALLBACK", True))
    connect_timeout = float(getattr(Params, "SMART_SWARM_STREAM_CONNECT_TIMEOUT_SEC", 3.0))
    backoff = float(getattr(Params, "SMART_SWARM_STREAM_BACKOFF_INITIAL_SEC", 0.25))
    max_backoff = float(getattr(Params, "SMART_SWARM_STREAM_BACKOFF_MAX_SEC", 2.0))

    while True:
        target_version, target_hw_id, target_ip = current_leader_stream_target()
        if not target_ip:
            await asyncio.sleep(backoff)
            continue
        if use_stream:
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_connect=connect_timeout, sock_read=None)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(ws_url(target_ip), heartbeat=15) as websocket:
                        logger.info("Connected to leader Smart Swarm stream at %s", ws_url(target_ip))
                        leader_unreachable_count = 0
                        backoff = float(getattr(Params, "SMART_SWARM_STREAM_BACKOFF_INITIAL_SEC", 0.25))

                        async for message in websocket:
                            if leader_stream_target_changed(target_version, target_hw_id, target_ip):
                                logger.info(
                                    "Leader stream target changed from %s@%s to %s@%s; reconnecting.",
                                    target_hw_id,
                                    target_ip,
                                    LEADER_HW_ID,
                                    LEADER_IP,
                                )
                                break
                            if message.type == aiohttp.WSMsgType.TEXT:
                                data = message.json()
                                if isinstance(data, dict) and data.get("error"):
                                    logger.debug("Leader stream returned error payload: %s", data)
                                    continue
                                apply_leader_state_sample(data, "ws")
                            elif message.type == aiohttp.WSMsgType.ERROR:
                                raise websocket.exception() or RuntimeError("leader websocket closed with error")
                            elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                                raise RuntimeError("leader websocket closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                leader_unreachable_count += 1
                logger.warning(
                    "Leader Smart Swarm stream unavailable (%s/%s): %s",
                    leader_unreachable_count,
                    max_unreachable_attempts,
                    exc,
                )
        if use_http_fallback:
            await consume_http_fallback(backoff, target_version, target_hw_id, target_ip)
        elif leader_unreachable_count >= max_unreachable_attempts and DRONE_INSTANCE is not None:
            logger.warning(
                "Leader stream unavailable for %s attempts with no HTTP fallback; the control loop will own failover timing.",
                leader_unreachable_count,
            )

        await asyncio.sleep(backoff)
        backoff = min(max_backoff, max(backoff * 2.0, float(getattr(Params, "SMART_SWARM_STREAM_BACKOFF_INITIAL_SEC", 0.25))))

        
async def elect_new_leader():
    """
    Elect a new leader when the current leader is unreachable.
    The exact failover policy is controlled by Params.SMART_SWARM_LEADER_LOSS_STRATEGY.
    """
    global last_election_time
    global SWARM_CONFIG, LEADER_HW_ID, LEADER_IP
    global leader_unreachable_count, LEADER_KALMAN_FILTER
    global IS_LEADER, FOLLOWER_TASKS, DRONE_INSTANCE

    now = time.time()
    # Cooldown guard
    if now - last_election_time < Params.SMART_SWARM_LEADER_ELECTION_COOLDOWN_SEC:
        logging.getLogger(__name__).debug(
            f"Election skipped; only {now-last_election_time:.1f}s since last "
            f"(<{Params.SMART_SWARM_LEADER_ELECTION_COOLDOWN_SEC}s cooldown)."
        )
        return
    last_election_time = now

    logger = logging.getLogger(__name__)
    old_leader = LEADER_HW_ID
    strategy = getattr(Params, "SMART_SWARM_LEADER_LOSS_STRATEGY", "upstream_or_hold")
    failover = choose_leader_loss_response(
        self_hw_id=HW_ID,
        current_leader_hw_id=old_leader,
        swarm_config=SWARM_CONFIG,
        strategy=strategy,
    )
    logger.warning(
        "Leader-loss failover resolved using strategy '%s': %s",
        failover["strategy"],
        failover["reason"],
    )

    original = dict(SWARM_CONFIG[str(HW_ID)])
    if failover["action"] == "self_hold":
        SWARM_CONFIG[str(HW_ID)]['follow'] = 0
        bump_formation_config_version("leader loss self-hold")
        try:
            await notify_gcs_of_leader_change(0)
        except Exception:
            logger.warning("GCS notify failed for self-promotion during failover.")
        RECOVERY_OVERRIDE.remember(original, SWARM_CONFIG[str(HW_ID)])
        await transition_to_leader_mode(DRONE_INSTANCE, logger, "leader loss failover")
        return

    new_leader = failover["leader_hw_id"]
    if new_leader is None:
        logger.warning("Failover did not resolve a leader candidate; entering HOLD mode.")
        SWARM_CONFIG[str(HW_ID)]['follow'] = 0
        bump_formation_config_version("leader loss no safe candidate")
        RECOVERY_OVERRIDE.remember(original, SWARM_CONFIG[str(HW_ID)])
        await transition_to_leader_mode(DRONE_INSTANCE, logger, "leader loss failover")
        return

    logger.info("Attempting failover to Drone %s.", new_leader)
    try:
        projected = recovery_assignment(HW_ID, new_leader, SWARM_CONFIG, strategy=strategy)
        accepted = await notify_gcs_of_leader_change(new_leader)
    except ValueError as exc:
        logger.warning("%s", exc)
        accepted = False
    if accepted and assign_leader_target(new_leader) is not None:
        SWARM_CONFIG[str(HW_ID)] = projected
        OFFSETS.update({axis: projected[f'offset_{axis}'] for axis in ('x', 'y', 'z')})
        bump_formation_config_version(f"leader failover to {new_leader}")
        RECOVERY_OVERRIDE.remember(original, projected)
        publish_runtime_assignment(SWARM_CONFIG.get(str(HW_ID), {}), force_follow=new_leader)
        logger.info("Leader failover committed: now following %s @ %s", new_leader, LEADER_IP)
        return

    logger.warning(
        "Leader failover to %s could not be committed; reverting to self-hold for safety.",
        new_leader,
    )
    SWARM_CONFIG[str(HW_ID)]['follow'] = 0
    bump_formation_config_version("leader failover rejected")
    try:
        await notify_gcs_of_leader_change(0)
    except Exception:
        logger.warning("GCS notify failed while reverting to self-hold after failover rejection.")
    RECOVERY_OVERRIDE.remember(original, SWARM_CONFIG[str(HW_ID)])
    await transition_to_leader_mode(DRONE_INSTANCE, logger, "failover commit rejected")



    
    
async def notify_gcs_of_leader_change(new_leader_hw_id) -> bool:
    """
    Notify the GCS of our updated leader by patching our canonical swarm assignment.
    Returns True if the GCS accepted the change, False otherwise.
    """
    logger = logging.getLogger(__name__)

    if RUNTIME_SESSION and RUNTIME_SESSION.snapshot:
        try:
            # Self-hold callers have already updated the local follow field.
            # Reconstruct the pre-recovery revision for compare-and-save.
            entries = [dict(m) for m in SWARM_CONFIG.values()]
            for entry in entries:
                if str(entry['hw_id']) == str(HW_ID):
                    entry['follow'] = int(LEADER_HW_ID or 0)
            await RUNTIME_SESSION.commit_recovery(HW_ID, new_leader_hw_id, topology_revision(entries))
            return True
        except Exception as exc:
            logger.warning("Session recovery write not accepted (%s); retaining local Hold if needed", type(exc).__name__)
            return False

    gcs_ip = Params.GCS_IP
    notify_url = (
        f"http://{gcs_ip}:{Params.gcs_api_port}"
        f"{GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE.format(hw_id=int(HW_ID))}"
    )
    payload = {
        'follow': int(new_leader_hw_id),
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                notify_url,
                json=payload,
                headers=gcs_auth_headers(),
                timeout=aiohttp.ClientTimeout(
                    total=float(Params.SMART_SWARM_GCS_NOTIFY_TIMEOUT_SEC)
                ),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                if data.get('status') == 'success':
                    logger.info(f"GCS accepted leader change for HW_ID={HW_ID}")
                    return True
                else:
                    logger.warning(f"GCS rejected leader change: {data}")
                    return False
    except Exception as e:
        logger.error(f"Error notifying GCS of leader change for HW_ID={HW_ID}: {e}")
        return False




# ----------------------------- #
#    Own State Update Task      #
# ----------------------------- #

async def update_own_state(drone: System):
    """
    Keep the follower's own NED motion stream alive and timestamped.
    """
    logger = logging.getLogger(__name__)
    global OWN_STATE
    last_failure = None
    backoff_sec = 0.25
    while True:
        try:
            await drone.telemetry.set_rate_position_velocity_ned(float(Params.SMART_SWARM_CONTROL_RATE_HZ))
        except Exception as exc:
            logger.debug("Could not raise own-state telemetry rate for Smart Swarm: %s", exc)

        try:
            async for position_velocity in drone.telemetry.position_velocity_ned():
                if last_failure is not None:
                    logger.info("Own NED telemetry stream recovered.")
                    last_failure = None
                backoff_sec = 0.25
                position = position_velocity.position
                velocity = position_velocity.velocity
                OWN_STATE['pos_n'] = position.north_m
                OWN_STATE['pos_e'] = position.east_m
                OWN_STATE['pos_d'] = position.down_m
                OWN_STATE['vel_n'] = velocity.north_m_s
                OWN_STATE['vel_e'] = velocity.east_m_s
                OWN_STATE['vel_d'] = velocity.down_m_s
                OWN_STATE['timestamp'] = time.time()
                OWN_STATE['updated_monotonic'] = time.monotonic()
            raise RuntimeError("own NED telemetry stream ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            log = logger.warning if failure != last_failure else logger.debug
            log("Own NED telemetry stream unavailable; retrying: %s", failure)
            last_failure = failure
            await asyncio.sleep(backoff_sec)
            backoff_sec = min(2.0, backoff_sec * 2.0)


async def update_own_attitude(drone: System):
    """Keep a fresh yaw seed so Smart Swarm never steps to leader yaw."""
    logger = logging.getLogger(__name__)
    last_failure = None
    backoff_sec = 0.25
    while True:
        try:
            await drone.telemetry.set_rate_attitude_euler(
                float(Params.SMART_SWARM_CONTROL_RATE_HZ)
            )
        except Exception as exc:
            logger.debug("Could not raise own-yaw telemetry rate for Smart Swarm: %s", exc)

        try:
            async for attitude in drone.telemetry.attitude_euler():
                if last_failure is not None:
                    logger.info("Own yaw telemetry stream recovered.")
                    last_failure = None
                backoff_sec = 0.25
                yaw_deg = float(attitude.yaw_deg)
                if not np.isfinite(yaw_deg):
                    logger.warning("Ignoring non-finite own yaw from PX4 telemetry.")
                    continue
                OWN_STATE['yaw_deg'] = yaw_deg
                OWN_STATE['yaw_updated_monotonic'] = time.monotonic()
            raise RuntimeError("own yaw telemetry stream ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            log = logger.warning if failure != last_failure else logger.debug
            log("Own yaw telemetry stream unavailable; retrying: %s", failure)
            last_failure = failure
            await asyncio.sleep(backoff_sec)
            backoff_sec = min(2.0, backoff_sec * 2.0)

# ----------------------------- #
#          Control Loop         #
# ----------------------------- #


def _build_follower_motion_controller(seed_yaw_deg: float) -> FollowerMotionController:
    """Build one controller from the centralized Smart Swarm policy."""
    max_dt = float(Params.SMART_SWARM_MAX_COMMAND_DT_SEC)
    return FollowerMotionController(
        position_gain=float(Params.SMART_SWARM_POSITION_GAIN),
        velocity_gain=float(Params.SMART_SWARM_KV),
        leader_velocity_feedforward=float(Params.SMART_SWARM_LEADER_VELOCITY_FEEDFORWARD),
        max_yaw_rate_deg_s=float(Params.SMART_SWARM_MAX_YAW_RATE_DEG_S),
        max_dt_s=max_dt,
        seed_yaw_deg=seed_yaw_deg,
        formation_guard=FormationGuard(
            capture_horizontal_m=float(Params.SMART_SWARM_CAPTURE_HORIZONTAL_M),
            capture_vertical_m=float(Params.SMART_SWARM_CAPTURE_VERTICAL_M),
            capture_stable_sec=float(Params.SMART_SWARM_CAPTURE_STABLE_SEC),
            tracking_horizontal_m=float(Params.SMART_SWARM_TRACKING_HORIZONTAL_M),
            tracking_vertical_m=float(Params.SMART_SWARM_TRACKING_VERTICAL_M),
        ),
        velocity_shaper=NedVelocityCommandShaper(
            max_horizontal_speed_m_s=float(Params.SMART_SWARM_MAX_HORIZONTAL_SPEED_M_S),
            max_vertical_speed_m_s=float(Params.SMART_SWARM_MAX_VERTICAL_SPEED_M_S),
            max_acceleration_m_s2=float(Params.SMART_SWARM_MAX_ACCELERATION_M_S2),
            max_jerk_m_s3=float(Params.SMART_SWARM_MAX_JERK_M_S3),
            max_dt_s=max_dt,
        ),
        position_deadband_m=float(Params.SMART_SWARM_POSITION_DEADBAND_M),
        vertical_deadband_m=float(Params.SMART_SWARM_VERTICAL_DEADBAND_M),
        position_filter_time_constant_s=float(
            Params.SMART_SWARM_POSITION_FILTER_TIME_CONSTANT_SEC
        ),
        position_softening_m=float(Params.SMART_SWARM_POSITION_SOFTENING_M),
        vertical_softening_m=float(Params.SMART_SWARM_VERTICAL_SOFTENING_M),
    )


def _leader_motion_confidence(leader_age_sec: float) -> float:
    """Ramp the complete follower request to zero as leader motion ages."""
    fresh_sec = float(Params.SMART_SWARM_SOURCE_MAX_AGE_SEC)
    grace_sec = max(float(Params.SMART_SWARM_STREAM_PREDICT_GRACE_SEC), 1e-3)
    if leader_age_sec <= fresh_sec:
        return 1.0
    return max(0.0, 1.0 - ((leader_age_sec - fresh_sec) / grace_sec))


def _fresh_own_yaw(snapshot: dict, current_time: float) -> float | None:
    """Return a finite, fresh yaw seed from the follower's own PX4 stream."""
    try:
        yaw = float(snapshot.get('yaw_deg'))
        updated = float(snapshot.get('yaw_updated_monotonic'))
    except (TypeError, ValueError):
        return None
    age = current_time - updated
    if (
        not np.isfinite(yaw)
        or not np.isfinite(updated)
        or updated <= 0
        or age < 0
        or age > float(Params.SMART_SWARM_OWN_STATE_MAX_AGE_SEC)
    ):
        return None
    return yaw


async def control_loop(drone: System):
    """
    Control loop that sends offboard setpoints to the drone based on the leader state.

    Args:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    global LEADER_KALMAN_FILTER, RUNTIME_PHASE, RUNTIME_DETAIL
    loop_interval = 1 / float(Params.SMART_SWARM_CONTROL_RATE_HZ)
    led_controller = LEDController.get_instance()
    led_controller.set_color(0, 255, 0)  # Green to indicate control loop started

    previous_time = None
    state_gate_status = None
    motion_status = None
    applied_config_version = FORMATION_CONFIG_VERSION
    controller = None
    own_invalid_since = None
    leader_missing_since = None
    offboard_active = True

    async def send_decision(decision):
        if CONTROL_AUTHORITY is not None and not CONTROL_AUTHORITY.owns_fresh_offboard():
            return
        await drone.offboard.set_velocity_ned(VelocityNedYaw(
            float(decision.velocity_ned[0]),
            float(decision.velocity_ned[1]),
            float(decision.velocity_ned[2]),
            float(decision.yaw_deg),
        ))

    try:
        while True:
            if CONTROL_AUTHORITY is not None and CONTROL_AUTHORITY.takeover_reason:
                return
            current_time = time.monotonic()
            dt = max(1e-3, current_time - previous_time) if previous_time else loop_interval
            previous_time = current_time

            own_snapshot = dict(OWN_STATE)
            own_validity = validate_own_motion_state(
                own_snapshot,
                updated_monotonic=own_snapshot.get('updated_monotonic'),
                now_monotonic=current_time,
                max_age_sec=float(Params.SMART_SWARM_OWN_STATE_MAX_AGE_SEC),
            )
            own_yaw = _fresh_own_yaw(own_snapshot, current_time)
            own_state_ready = own_validity.valid and own_yaw is not None
            leader_state_ready = 'update_time' in LEADER_STATE

            if not own_state_ready:
                RUNTIME_PHASE, RUNTIME_DETAIL = "holding", "Waiting for fresh vehicle position"
                if state_gate_status != 'own':
                    logger.warning(
                        "Follower motion suspended while own-state evidence is unavailable: %s",
                        own_validity.reason if not own_validity.valid else "own yaw is unavailable or stale",
                    )
                    state_gate_status = 'own'
                if own_invalid_since is None:
                    own_invalid_since = current_time
                if controller is not None and offboard_active:
                    decision = controller.suspend(dt_s=dt, reason="own motion state unavailable")
                    await send_decision(decision)
                if (
                    offboard_active
                    and own_invalid_since is not None
                    and current_time - own_invalid_since > float(Params.SMART_SWARM_HARD_STALE_TIMEOUT_SEC)
                ):
                    await execute_failsafe(drone, reason="own motion state remained stale")
                    offboard_active = False
                await asyncio.sleep(loop_interval)
                continue

            own_invalid_since = None
            if controller is None:
                controller = _build_follower_motion_controller(own_yaw)

            if not leader_state_ready:
                RUNTIME_PHASE, RUNTIME_DETAIL = "tracking_degraded", "Waiting for fresh leader position"
                if state_gate_status != 'leader':
                    logger.info("Follower holding zero while waiting for a valid leader-state lock.")
                    state_gate_status = 'leader'
                if offboard_active:
                    await send_decision(
                        controller.suspend(dt_s=dt, reason="leader motion state unavailable")
                    )
                if leader_missing_since is None:
                    leader_missing_since = current_time
                elif (
                    current_time - leader_missing_since
                    > float(Params.SMART_SWARM_HARD_STALE_TIMEOUT_SEC)
                ):
                    logger.warning(
                        "No valid leader motion lock for %.3fs; leaving Offboard and starting failover.",
                        current_time - leader_missing_since,
                    )
                    await handle_leader_unavailability(
                        drone,
                        logger,
                        "initial leader motion unavailable",
                    )
                    if IS_LEADER:
                        return
                    leader_missing_since = current_time
                    offboard_active = False
                await asyncio.sleep(loop_interval)
                continue

            leader_age = current_time - float(LEADER_STATE['update_time'])
            if leader_age > float(Params.SMART_SWARM_HARD_STALE_TIMEOUT_SEC):
                logger.warning(
                    "Leader motion stale for %.3fs; leaving Offboard and starting failover.",
                    leader_age,
                )
                await handle_leader_unavailability(drone, logger, "control-loop stale leader motion")
                if IS_LEADER:
                    return
                offboard_active = False
                await asyncio.sleep(loop_interval)
                continue

            leader_missing_since = None
            if not offboard_active:
                if not await ensure_offboard_active_for_follower(
                    drone,
                    logger,
                    "fresh motion evidence recovered",
                ):
                    await asyncio.sleep(loop_interval)
                    continue
                offboard_active = True
                controller.reset_after_offboard_hold(seed_yaw_deg=own_yaw)

            if state_gate_status is not None:
                logger.info("Follower state lock acquired; beginning bounded formation capture.")
                state_gate_status = None

            if applied_config_version != FORMATION_CONFIG_VERSION:
                applied_config_version = FORMATION_CONFIG_VERSION
                controller.require_new_capture()
                logger.info(
                    "Follower motion suspended for bounded formation reconfiguration (version=%s).",
                    applied_config_version,
                )

            predicted_state = LEADER_KALMAN_FILTER.predict(current_time)
            leader_n = predicted_state[0]
            leader_e = predicted_state[1]
            leader_d = predicted_state[2]
            leader_vel_n = predicted_state[3]
            leader_vel_e = predicted_state[4]
            leader_vel_d = predicted_state[5]
            leader_yaw = LEADER_STATE.get('yaw', 0.0)
            leader_yaw_rate_deg_s = LEADER_STATE.get('yaw_rate_deg_s', 0.0)

            if FRAME == "body":
                offset_x_ned, offset_y_ned = transform_body_to_nea(OFFSETS['x'], OFFSETS['y'], leader_yaw)
                yaw_rate_rad_s = np.deg2rad(leader_yaw_rate_deg_s)
                offset_velocity_n = -offset_y_ned * yaw_rate_rad_s
                offset_velocity_e = offset_x_ned * yaw_rate_rad_s
            else:
                offset_x_ned, offset_y_ned = OFFSETS['x'], OFFSETS['y']
                offset_velocity_n = 0.0
                offset_velocity_e = 0.0

            desired_n = leader_n + offset_x_ned
            desired_e = leader_e + offset_y_ned
            desired_d = leader_d - OFFSETS['z']

            target_velocity = np.array([
                leader_vel_n + offset_velocity_n,
                leader_vel_e + offset_velocity_e,
                leader_vel_d,
            ])

            own_position = np.array([
                own_snapshot['pos_n'],
                own_snapshot['pos_e'],
                own_snapshot['pos_d'],
            ])
            own_velocity = np.array([
                own_snapshot['vel_n'],
                own_snapshot['vel_e'],
                own_snapshot['vel_d'],
            ])
            desired_position = np.array([desired_n, desired_e, desired_d])

            decision = controller.compute(
                desired_position_ned=desired_position,
                own_position_ned=own_position,
                leader_velocity_ned=target_velocity,
                own_velocity_ned=own_velocity,
                target_yaw_deg=leader_yaw,
                confidence=_leader_motion_confidence(leader_age),
                dt_s=dt,
                now_s=current_time,
            )
            await send_decision(decision)
            RUNTIME_PHASE = ("tracking_degraded" if decision.confidence < 1.0 else decision.status) if decision.tracking_allowed else "holding"
            RUNTIME_DETAIL = ("Leader data delayed; slowing smoothly"
                              if RUNTIME_PHASE == "tracking_degraded" else decision.detail)
            if decision.status != motion_status:
                log = (
                    logger.warning
                    if decision.status in {'unsafe_geometry', 'invalid'}
                    else logger.info
                )
                log("Follower motion state: %s — %s", decision.status, decision.detail)
                motion_status = decision.status
            logger.debug(
                "Velocity command sent: vel=%s yaw=%.2f leader_age=%.3fs confidence=%.2f requested=%s",
                decision.velocity_ned,
                decision.yaw_deg,
                leader_age,
                decision.confidence,
                decision.requested_velocity_ned,
            )
            await asyncio.sleep(loop_interval)
    except asyncio.CancelledError:
        logger.info("Control loop cancelled.")
    except OffboardError as e:
        logger.error(f"Offboard error in control loop: {e}")
        RUNTIME_PHASE, RUNTIME_DETAIL = "holding", "Paused: Offboard command failed; restart following when ready."
        await execute_failsafe(drone, reason="offboard error in control loop")
        await asyncio.Event().wait()
    except (ValueError, VelocityCommandShapeError) as exc:
        logger.error("Smart Swarm motion policy rejected a command: %s", exc)
        RUNTIME_PHASE, RUNTIME_DETAIL = "holding", f"Paused: motion controller error ({exc}); restart following when ready."
        await execute_failsafe(drone, reason="motion policy rejection")
        await asyncio.Event().wait()
    except Exception:
        logger.exception("Unexpected error in control loop")
        RUNTIME_PHASE, RUNTIME_DETAIL = "holding", "Paused: internal controller error; restart following when ready."
        await execute_failsafe(drone, reason="unexpected control-loop error")
        await asyncio.Event().wait()

# ----------------------------- #
#         Failsafe Function     #
# ----------------------------- #

async def execute_failsafe(
    drone: System,
    reason: str = "",
    *,
    operation_timeout_sec: Optional[float] = None,
) -> VehicleHandoffResult:
    """
    Leave Offboard and command PX4 HOLD without a discontinuous zero setpoint.

    Args:
        drone (System): MAVSDK drone system instance.
        operation_timeout_sec: Optional bound applied independently to the
            Offboard-stop and HOLD RPCs during process shutdown. Runtime
            failsafe callers retain the normal MAVSDK behavior by omitting it.
    """
    logger = logging.getLogger(__name__)
    if CONTROL_AUTHORITY is not None:
        if CONTROL_AUTHORITY.takeover_reason or CONTROL_AUTHORITY.never_requested_follower_control():
            # Startup may fail before we own any control. In particular, a
            # leader waiting for a missing follower must not interrupt its RC
            # or QGC mission just because the startup barrier failed.
            logger.info("Preserving PX4 control during %s (%s).", reason, CONTROL_AUTHORITY.mode)
            return VehicleHandoffResult(False, False, control_preserved=True)
        if not CONTROL_AUTHORITY.owns_fresh_offboard():
            # Do not infer authority from an old mode sample. Stopping the
            # producer/server leaves PX4's configured Offboard-loss action in
            # charge; if the mode is unknown, report an unconfirmed handoff.
            preserved = CONTROL_AUTHORITY.has_fresh_mode() and CONTROL_AUTHORITY.mode != "OFFBOARD"
            return VehicleHandoffResult(False, False, control_preserved=preserved)
        CONTROL_AUTHORITY.expect("HOLD")
    led_controller = LEDController.get_instance()
    led_controller.set_color(255, 0, 0)  # Red to indicate failsafe
    offboard_stop_completed = False
    hold_requested = False

    async def await_operation(awaitable):
        if operation_timeout_sec is None:
            return await awaitable
        return await asyncio.wait_for(
            awaitable,
            timeout=max(0.01, float(operation_timeout_sec)),
        )

    try:
        await await_operation(drone.offboard.stop())
        offboard_stop_completed = True
        logger.info("Failsafe: Offboard stopped%s.", f" ({reason})" if reason else "")
    except asyncio.TimeoutError:
        logger.error(
            "Failsafe timed out while stopping Offboard%s.",
            f" ({reason})" if reason else "",
        )
    except OffboardError as exc:
        logger.warning("Failsafe could not stop Offboard cleanly: %s", exc)
    except Exception:
        logger.exception("Unexpected error while stopping Offboard during failsafe.")

    try:
        if CONTROL_AUTHORITY is not None and CONTROL_AUTHORITY.takeover_reason:
            return VehicleHandoffResult(offboard_stop_completed, False, control_preserved=True)
        await await_operation(drone.action.hold())
        hold_requested = True
        logger.info("Failsafe: PX4 HOLD requested%s.", f" ({reason})" if reason else "")
    except asyncio.TimeoutError:
        logger.error(
            "Failsafe timed out while commanding HOLD%s.",
            f" ({reason})" if reason else "",
        )
    except ActionError as exc:
        logger.error("Failsafe HOLD command failed: %s", exc)
    except Exception:
        logger.exception("Unexpected error while commanding HOLD during failsafe.")

    return VehicleHandoffResult(
        offboard_stop_completed=offboard_stop_completed,
        hold_requested=hold_requested,
    )

# ----------------------------- #
#       Drone Initialization    #
# ----------------------------- #

async def require_authoritative_airborne_state(drone: System):
    """Repeat Smart Swarm's airborne gate from fresh MAVSDK streams."""
    try:
        admission_state = await observe_authoritative_vehicle_state(drone)
    except Exception as exc:
        raise RuntimeError(
            "Smart Swarm was blocked because fresh armed, landed, and relative-altitude "
            "telemetry could not be sampled immediately before runtime start."
        ) from exc
    if admission_state.airborne:
        return admission_state

    evidence = admission_state.as_dict()
    raise RuntimeError(
        "Smart Swarm requires fresh authoritative telemetry showing an armed IN_AIR "
        f"vehicle at least {AIRBORNE_MIN_RELATIVE_ALTITUDE_M:.1f}m above home; "
        f"observed armed={evidence.get('armed')}, "
        f"landed_state={evidence.get('landed_state')}, "
        f"relative_altitude_m={evidence.get('relative_altitude_m')}."
    )


@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(2))
async def initialize_drone(start_offboard: bool = False):
    """
    Initializes the drone connection and performs pre-flight checks.

    Returns:
        drone (System): MAVSDK drone system instance.
    """
    logger = logging.getLogger(__name__)
    try:
        # Initialize LEDController
        led_controller = LEDController.get_instance()
        led_controller.set_color(0, 0, 255)  # Blue to indicate initialization


        # MAVSDK server is assumed to be running on localhost
        mavsdk_server_address = "127.0.0.1"

        # Create the drone system
        drone = System(mavsdk_server_address=mavsdk_server_address, port=Params.DEFAULT_GRPC_PORT)
        await drone.connect(system_address=f"udp://:{Params.mavsdk_port}")

        logger.info(
            f"Connecting to drone via MAVSDK server at {mavsdk_server_address}:{Params.DEFAULT_GRPC_PORT} on UDP port {Params.mavsdk_port}."
        )

        # Wait for connection with a timeout
        start_time = time.time()
        async for state in drone.core.connection_state():
            if state.is_connected:
                logger.info(
                    f"Drone connected via MAVSDK server at {mavsdk_server_address}:{Params.DEFAULT_GRPC_PORT}."
                )
                break
            if time.time() - start_time > Params.PRE_FLIGHT_TIMEOUT:
                logger.error("Timeout while waiting for drone connection.")
                led_controller.set_color(255, 0, 0)  # Red
                raise TimeoutError("Drone connection timeout.")
            await asyncio.sleep(1)

        # Perform pre-flight checks (only check for global and home position)
        logger.info("Performing pre-flight checks.")
        start_time = time.time()
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                logger.info("Global position estimate and home position check passed.")
                break
            else:
                if not health.is_global_position_ok:
                    logger.warning("Waiting for global position to be okay.")
                if not health.is_home_position_ok:
                    logger.warning("Waiting for home position to be set.")
            if time.time() - start_time > Params.PRE_FLIGHT_TIMEOUT:
                logger.error("Pre-flight checks timed out.")
                led_controller.set_color(255, 0, 0)  # Red
                raise TimeoutError("Pre-flight checks timed out.")
            await asyncio.sleep(1)

        await require_authoritative_airborne_state(drone)

        if start_offboard:
            logger.info("Starting offboard mode during initialization.")
            await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
            await drone.offboard.start()
        led_controller.set_color(0, 255, 0)  # Green to indicate ready

        return drone
    except Exception:
        logger.exception("Error during drone initialization")
        raise

# ----------------------------- #
#         Main Runner           #
# ----------------------------- #

async def run_smart_swarm(lifecycle: SmartSwarmRuntimeLifecycle):
    """
    Main function to run the smart swarm mode with dynamic configuration updates.
    """
    logger = logging.getLogger(__name__)
    global HW_ID, DRONE_CONFIG, SWARM_CONFIG, IS_LEADER, OFFSETS, FRAME, LEADER_HW_ID, LEADER_IP, LEADER_KALMAN_FILTER
    global LEADER_HOME_POS, OWN_HOME_POS, REFERENCE_POS, RUNTIME_PHASE, RUNTIME_DETAIL
    global CONTROL_AUTHORITY

    # --------------------------- #
    #      Initialization         #
    # --------------------------- #

    # Read hardware ID from the canonical runtime identity model
    HW_ID = ConfigLoader.get_hw_id()
    if HW_ID is None:
        logger.error("Hardware ID not found.")
        sys.exit(1)

    # Read configuration JSON files
    config_filename = Params.config_file_name
    swarm_filename = Params.swarm_file_name
    read_config(config_filename)
    if RUNTIME_SESSION and RUNTIME_SESSION.snapshot:
        # Command-carried, hash-verified snapshot is the startup authority. A
        # temporary GCS outage never silently substitutes a stale disk file.
        replace_swarm_config([m.model_dump() for m in RUNTIME_SESSION.snapshot.assignments], "confirmed command")
    else:
        read_swarm(swarm_filename)
        await refresh_swarm_config_from_gcs(logger, source_label="startup")

    # Get own drone configuration
    hw_id_str = str(HW_ID)
    drone_config = DRONE_CONFIG.get(hw_id_str)
    if drone_config is None:
        logger.error(f"Configuration for HW_ID {HW_ID} not found.")
        sys.exit(1)

    # Get swarm configuration for own drone
    swarm_config = SWARM_CONFIG.get(hw_id_str)
    if swarm_config is None:
        logger.error(f"Swarm configuration for HW_ID {HW_ID} not found.")
        sys.exit(1)

    # Determine drone role and set formation parameters
    IS_LEADER = swarm_config['follow'] == 0
    OFFSETS['x'] = swarm_config['offset_x']
    OFFSETS['y'] = swarm_config['offset_y']
    OFFSETS['z'] = swarm_config['offset_z']
    FRAME = swarm_config['frame']
    logger.info(f"Drone HW_ID {HW_ID} - Initial Role: {'Leader' if IS_LEADER else 'Follower'}, Offsets: {OFFSETS}, Frame: {FRAME}")
    publish_runtime_assignment(swarm_config, active=False)

    # For followers, set leader info and initialize Kalman filter; for leaders, simply log the role.
    if not IS_LEADER:
        LEADER_HW_ID = normalize_hw_id(swarm_config['follow'])
        leader_config = get_drone_config_for_hw_id(LEADER_HW_ID)
        if leader_config is None:
            logger.error(f"Leader configuration for HW_ID {LEADER_HW_ID} not found.")
            sys.exit(1)
        LEADER_IP = leader_config['ip']
        LEADER_KALMAN_FILTER = LeaderKalmanFilter()
    else:
        logger.info("Operating in Leader mode.")

    # --------------------------- #
    #     Start MAVSDK Server     #
    # --------------------------- #

    mavsdk_server = start_mavsdk_server(Params.mavsdk_port)
    if mavsdk_server is None:
        logger.error("Failed to start MAVSDK server.")
        sys.exit(1)
    lifecycle.mavsdk_server = mavsdk_server

    await asyncio.sleep(2)  # Allow server to initialize

    # --------------------------- #
    #      Drone Initialization   #
    # --------------------------- #

    try:
        drone = await initialize_drone(start_offboard=False)
        lifecycle.drone = drone
        global DRONE_INSTANCE
        DRONE_INSTANCE = drone
        CONTROL_AUTHORITY = ControlAuthority()
        lifecycle.authority_task = asyncio.create_task(watch_control_authority(drone))
    except Exception:
        logger.error("Failed to initialize drone.")
        sys.exit(1)

    # --------------------------- #
    #  Fetch Own Home Position    #
    # --------------------------- #
    # (Existing logic remains unchanged)
    telemetry_origin = None
    fallback_origin = None

    try:
        origin = await drone.telemetry.get_gps_global_origin()
        telemetry_origin = {
            'latitude': origin.latitude_deg,
            'longitude': origin.longitude_deg,
            'altitude': origin.altitude_m
        }
        logger.info(f"Retrieved GPS global origin from telemetry: {telemetry_origin}")
    except Exception as e:
        logger.warning(f"Telemetry GPS origin request failed: {e}")

    if telemetry_origin is None:
        fallback_origin = fetch_home_position('127.0.0.1', Params.drone_api_port, Params.get_drone_gps_origin_URI)

    if telemetry_origin is not None:
        OWN_HOME_POS = telemetry_origin
        logger.info(f"Using telemetry GPS origin as primary: {OWN_HOME_POS}")
    elif fallback_origin is not None:
        OWN_HOME_POS = fallback_origin
        logger.info(f"Using fallback API GPS origin: {OWN_HOME_POS}")
    else:
        logger.error("Both telemetry and fallback API failed to provide a valid GPS origin. Exiting.")
        sys.exit(1)

    REFERENCE_POS = {
        'latitude': OWN_HOME_POS['latitude'],
        'longitude': OWN_HOME_POS['longitude'],
        'altitude': OWN_HOME_POS['altitude'],
    }
    logger.info(f"Reference position set to: {REFERENCE_POS}")

    if not IS_LEADER:
        leader_home_pos = fetch_home_position(LEADER_IP, Params.drone_api_port, Params.get_drone_home_URI)
        if leader_home_pos is None:
            logger.error("Failed to fetch leader's home position.")
            sys.exit(1)
        LEADER_HOME_POS = leader_home_pos
        logger.info(f"Leader's home position: {LEADER_HOME_POS}")

    # --------------------------- #
    #      Start Async Tasks      #
    # --------------------------- #

    # For followers, start the corresponding tasks and store them in FOLLOWER_TASKS
    if RUNTIME_SESSION:
        await RUNTIME_SESSION.wait_for_cluster(
            HW_ID, swarm_config['follow'], topology_revision(list(SWARM_CONFIG.values())),
            authority=CONTROL_AUTHORITY,
        )
    if CONTROL_AUTHORITY is not None and CONTROL_AUTHORITY.takeover_reason:
        raise RuntimeError(f"Smart Swarm start cancelled: {CONTROL_AUTHORITY.takeover_reason}")
    if not IS_LEADER:
        if not await ensure_follower_runtime(drone, logger, "startup"):
            logger.error("Failed to start follower runtime.")
            sys.exit(1)
    else:
        logger.info("No follower tasks started as drone is in Leader mode.")
        RUNTIME_PHASE = "active"

    # Launch the periodic swarm configuration update task (applies to both roles)
    swarm_update_task = asyncio.create_task(update_swarm_config_periodically(drone))
    lifecycle.swarm_update_task = swarm_update_task
    logger.info(f"[Main] Scheduled swarm_update_task: {swarm_update_task!r}")

    # --------------------------- #
    #         Main Loop         #
    # --------------------------- #

    while True:
        if CONTROL_AUTHORITY is not None and CONTROL_AUTHORITY.takeover_reason:
            RUNTIME_PHASE = "takeover"
            RUNTIME_DETAIL = CONTROL_AUTHORITY.takeover_reason
            break
        for task_name, task in list(FOLLOWER_TASKS.items()):
            if task.done() and not IS_LEADER and not LEADER_FAILOVER_IN_PROGRESS:
                raise RuntimeError(f"Follower task ended unexpectedly: {task_name}")
        publish_runtime_assignment()
        if RUNTIME_SESSION:
            RUNTIME_SESSION.phase = "active" if IS_LEADER else RUNTIME_PHASE
            RUNTIME_SESSION.detail = RUNTIME_DETAIL
            follow = 0 if IS_LEADER else LEADER_HW_ID
            await RUNTIME_SESSION.report(HW_ID, follow, topology_revision(list(SWARM_CONFIG.values())))
        await asyncio.sleep(1)


async def watch_control_authority(drone):
    """Independent of follower tasks so elections cannot remove the watcher."""
    async def consume(factory, update):
        while True:
            try:
                async for value in factory():
                    update(value)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).debug("PX4 authority stream unavailable", exc_info=True)
            await asyncio.sleep(0.25)
    tasks = [asyncio.create_task(consume(drone.telemetry.flight_mode,
                lambda value: CONTROL_AUTHORITY.update_mode(value, leader=IS_LEADER))),
             asyncio.create_task(consume(drone.telemetry.armed, CONTROL_AUTHORITY.update_armed)),
             asyncio.create_task(consume(drone.telemetry.landed_state, CONTROL_AUTHORITY.update_landed))]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ----------------------------- #
#             Main              #
# ----------------------------- #


async def run_smart_swarm_process(logger) -> bool:
    """Run Smart Swarm and return whether its final vehicle handoff completed."""
    global RUNTIME_SESSION, CONTROL_AUTHORITY, RUNTIME_PHASE, RUNTIME_DETAIL
    RUNTIME_SESSION = SwarmSessionRuntime(Params, logger)
    CONTROL_AUTHORITY = None
    RUNTIME_PHASE = "ready"
    lifecycle = SmartSwarmRuntimeLifecycle(
        logger,
        cancel_follower_tasks=cancel_follower_tasks,
        vehicle_handoff=execute_failsafe,
        stop_mavsdk_server=stop_mavsdk_server,
        manager_grace_sec=Params.MISSION_PROCESS_STOP_GRACE_SEC,
    )
    loop = asyncio.get_running_loop()
    process_task = asyncio.current_task()
    signal_state, installed_signals = install_shutdown_signal_handlers(
        loop,
        process_task,
        logger,
    )

    shutdown_completed = False
    try:
        try:
            await run_smart_swarm(lifecycle)
        except asyncio.CancelledError:
            if signal_state.received_signal is None:
                raise
            logger.warning(
                "Smart Swarm runtime accepted %s and is handing control back to PX4.",
                signal_state.received_signal,
            )
        except Exception as exc:
            RUNTIME_PHASE, RUNTIME_DETAIL = "failed", str(exc)[:500]
            raise
    finally:
        reason = signal_state.received_signal or "runtime exit"
        shutdown_completed = await lifecycle.shutdown(reason)
        if CONTROL_AUTHORITY is not None and CONTROL_AUTHORITY.takeover_reason:
            RUNTIME_PHASE = "takeover"
        elif RUNTIME_PHASE != "failed":
            RUNTIME_PHASE = "stopped"
        clear_runtime_swarm_assignment(session_id=RUNTIME_SESSION.command_id, phase=RUNTIME_PHASE)
        RUNTIME_SESSION.phase = RUNTIME_PHASE
        RUNTIME_SESSION.detail = (CONTROL_AUTHORITY.takeover_reason if CONTROL_AUTHORITY else None) or (RUNTIME_DETAIL if RUNTIME_PHASE == "failed" else reason)
        if HW_ID is not None and SWARM_CONFIG:
            await RUNTIME_SESSION.report(HW_ID, 0 if IS_LEADER else (LEADER_HW_ID or 0),
                                         topology_revision(list(SWARM_CONFIG.values())))
        authority_task = getattr(lifecycle, "authority_task", None)
        if authority_task is not None:
            authority_task.cancel()
            await asyncio.gather(authority_task, return_exceptions=True)
        for handled_signal in installed_signals:
            loop.remove_signal_handler(handled_signal)
        CONTROL_AUTHORITY = None
    return shutdown_completed


def main():
    """
    Main function to run the smart swarm mode.
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Smart Swarm Mode')
    add_log_arguments(parser)
    args = parser.parse_args()

    # Initialize unified logging
    apply_log_args(args)
    register_component("smart_swarm", "drone", "Smart swarm following mode")
    init_drone_logging()
    _logger = get_logger("smart_swarm")

    try:
        shutdown_completed = asyncio.run(run_smart_swarm_process(_logger))
        if not shutdown_completed:
            _logger.critical(
                "Smart Swarm exited without a confirmed PX4 safety handoff."
            )
            sys.exit(2)
    except Exception:
        _logger.exception("Unhandled exception in main")
        sys.exit(1)

if __name__ == "__main__":
    main()
