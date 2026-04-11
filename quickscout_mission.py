#!/usr/bin/env python3
"""
QuickScout Mission Script

Executes a survey mission using PX4 Mission Mode.
Receives pre-computed waypoints from GCS, uploads as MAVSDK Mission items,
arms, and starts autonomous mission execution. Reports progress back to GCS.

Usage:
    python quickscout_mission.py --waypoints-file PATH --mission-id ID --hw-id HW_ID --return-behavior RTL
"""

import os
import sys
import json
import time
import asyncio
import argparse
import math
import socket
import subprocess
from contextlib import suppress

import requests
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight envs only
    psutil = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from drone_api_routes import DRONE_NAVIGATION_HOME_ROUTE, DRONE_STATE_ROUTE
from params import Params
from led_controller import LEDController
from mds_logging import get_logger
from mission_startup import arm_with_preflight_gate

logger = get_logger("quickscout")


def check_mavsdk_server_running(port):
    """Return whether a mavsdk_server is already bound to the requested gRPC port."""
    if psutil is None:
        return wait_for_port(port, timeout=0.2), None

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            for conn in proc.net_connections(kind="inet"):
                if conn.laddr.port == port:
                    return True, proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False, None


def wait_for_port(port, host="127.0.0.1", timeout=10.0):
    """Wait until a TCP port is reachable or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.1)
    return False


async def log_mavsdk_output(mavsdk_server):
    """Drain MAVSDK stdout/stderr so the subprocess does not block on filled pipes."""
    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stdout.readline)
            if not line:
                break
            logger.debug("MAVSDK Server: %s", line.decode().strip())
    except Exception:
        logger.exception("Error reading MAVSDK server stdout")

    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, mavsdk_server.stderr.readline)
            if not line:
                break
            logger.error("MAVSDK Server Error: %s", line.decode().strip())
    except Exception:
        logger.exception("Error reading MAVSDK server stderr")


def find_mavsdk_server():
    """Find the mavsdk_server binary in the current runtime checkout."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("MAVSDK_SERVER_PATH"),
        os.path.join(script_dir, "mavsdk_server"),
        os.path.join(os.path.dirname(script_dir), "mavsdk_server"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def start_mavsdk_server(grpc_port, udp_port):
    """Start a dedicated mavsdk_server for the QuickScout mission runtime."""
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        if psutil is None or pid is None:
            logger.info("Reusing existing MAVSDK server already listening on port %s", grpc_port)
            return None

        logger.info("MAVSDK server already running on port %s, terminating PID %s", grpc_port, pid)
        try:
            psutil.Process(pid).terminate()
            psutil.Process(pid).wait(timeout=5)
        except psutil.NoSuchProcess:
            logger.warning("MAVSDK server PID %s disappeared before termination", pid)
        except psutil.TimeoutExpired:
            logger.warning("MAVSDK server PID %s did not terminate gracefully; killing", pid)
            psutil.Process(pid).kill()
            psutil.Process(pid).wait(timeout=5)

    mavsdk_server_path = find_mavsdk_server()
    if not mavsdk_server_path:
        raise FileNotFoundError("mavsdk_server executable not found.")

    logger.info(
        "Starting MAVSDK server for QuickScout on gRPC:%s UDP:%s using %s",
        grpc_port,
        udp_port,
        mavsdk_server_path,
    )
    mavsdk_server = subprocess.Popen(
        [mavsdk_server_path, "-p", str(grpc_port), f"udp://:{udp_port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    asyncio.create_task(log_mavsdk_output(mavsdk_server))

    startup_timeout = max(float(getattr(Params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0)), 10.0)
    if not wait_for_port(grpc_port, timeout=startup_timeout):
        mavsdk_server.terminate()
        try:
            mavsdk_server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mavsdk_server.kill()
            mavsdk_server.wait(timeout=5)
        raise TimeoutError(f"MAVSDK server did not start listening on port {grpc_port} within {startup_timeout:.1f}s.")

    return mavsdk_server


def stop_mavsdk_server(mavsdk_server):
    """Stop a QuickScout-started mavsdk_server if it is still running."""
    if not mavsdk_server or mavsdk_server.poll() is not None:
        return
    logger.info("Stopping QuickScout MAVSDK server...")
    mavsdk_server.terminate()
    try:
        mavsdk_server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("QuickScout MAVSDK server did not terminate gracefully; killing it.")
        mavsdk_server.kill()
        mavsdk_server.wait(timeout=5)


async def wait_for_drone_connection(drone, timeout_sec):
    """Wait for MAVSDK connection confirmation with an explicit timeout."""
    deadline = time.monotonic() + timeout_sec
    connection_iter = drone.core.connection_state().__aiter__()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for MAVSDK connection.")
        try:
            state = await asyncio.wait_for(connection_iter.__anext__(), timeout=min(1.0, remaining))
        except asyncio.TimeoutError:
            continue
        except StopAsyncIteration as exc:
            raise RuntimeError("MAVSDK connection stream ended before the drone connected.") from exc
        if state.is_connected:
            return


async def wait_for_navigation_health(drone, timeout_sec):
    """Wait for global position and home position readiness with an explicit timeout."""
    deadline = time.monotonic() + timeout_sec
    health_iter = drone.telemetry.health().__aiter__()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for GPS fix and home position readiness.")
        try:
            health = await asyncio.wait_for(health_iter.__anext__(), timeout=min(1.0, remaining))
        except asyncio.TimeoutError:
            continue
        except StopAsyncIteration as exc:
            raise RuntimeError("Telemetry health stream ended before readiness was confirmed.") from exc
        if health.is_global_position_ok and health.is_home_position_ok:
            return


async def get_home_position(drone, timeout_sec):
    """Get the first home position sample with an explicit timeout."""
    home_iter = drone.telemetry.home().__aiter__()
    try:
        return await asyncio.wait_for(home_iter.__anext__(), timeout=timeout_sec)
    except asyncio.TimeoutError as exc:
        raise TimeoutError("Timed out waiting for home position sample.") from exc
    except StopAsyncIteration as exc:
        raise RuntimeError("Telemetry home-position stream ended before a sample was available.") from exc


def get_local_home_position(timeout: float = 1.0) -> dict:
    """Read the local drone API home position snapshot."""
    response = requests.get(
        f"http://127.0.0.1:{Params.drone_api_port}{DRONE_NAVIGATION_HOME_ROUTE}",
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Local home-position route did not return an object payload.")
    return payload


async def wait_for_local_startup_ready(timeout_sec: float, poll_sec: float = 0.5) -> dict:
    """Wait for the local drone API to report an armable, home-initialized startup state."""
    deadline = time.monotonic() + timeout_sec
    last_state = None

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"http://127.0.0.1:{Params.drone_api_port}{DRONE_STATE_ROUTE}",
                timeout=min(1.0, poll_sec),
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                last_state = payload
                if (
                    payload.get("is_ready_to_arm")
                    and payload.get("home_position_set")
                    and payload.get("readiness_status") == "ready"
                ):
                    return payload
        except requests.RequestException:
            pass

        await asyncio.sleep(poll_sec)

    raise TimeoutError(
        "Timed out waiting for local mission startup readiness. "
        f"Last state: {last_state!r}"
    )


def _great_circle_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 6371000.0 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _estimate_distance_from_positions(previous_position, current_position) -> float:
    if previous_position is None or current_position is None:
        return 0.0
    return _great_circle_distance_m(
        float(previous_position.latitude_deg),
        float(previous_position.longitude_deg),
        float(current_position.latitude_deg),
        float(current_position.longitude_deg),
    )


def _resolve_quickscout_runtime_param(name: str, default: float) -> float:
    raw_value = getattr(Params, name, default)
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return float(default)


async def _wait_for_mission_airborne(
    drone,
    *,
    min_gain_m: float,
    timeout_sec: float,
):
    """Confirm the aircraft actually climbed after mission start."""
    position_iter = drone.telemetry.position().__aiter__()
    deadline = time.monotonic() + timeout_sec
    last_position = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Timed out waiting for QuickScout mission takeoff / climb confirmation."
            )

        try:
            position = await asyncio.wait_for(position_iter.__anext__(), timeout=min(1.0, remaining))
        except asyncio.TimeoutError:
            continue
        except StopAsyncIteration:
            position_iter = drone.telemetry.position().__aiter__()
            continue

        last_position = position
        relative_altitude_m = float(getattr(position, "relative_altitude_m", 0.0) or 0.0)
        if relative_altitude_m >= min_gain_m:
            logger.info(
                "QuickScout climb confirmed at %.1fm relative altitude.",
                relative_altitude_m,
            )
            return position


async def _monitor_active_mission(
    drone,
    *,
    gcs_url: str,
    mission_id: str,
    hw_id: str,
    total_waypoints: int,
    startup_position,
):
    """
    Keep QuickScout ownership alive even if MissionProgress callbacks stall.

    MAVSDK MissionProgress has proven unreliable in some live SITL runs while PX4
    continues flying autonomously. The mission executor therefore treats progress
    callbacks as optional hints and uses `is_mission_finished()` plus telemetry
    polling as the canonical completion signal.
    """
    runtime_limit_sec = max(
        120.0,
        _resolve_quickscout_runtime_param("COMMAND_TRACKING_QUICKSCOUT_TIMEOUT_SEC", 900.0) - 30.0,
    )
    poll_interval_sec = max(
        0.5,
        _resolve_quickscout_runtime_param("QUICKSCOUT_PROGRESS_REPORT_INTERVAL_SEC", 2.0),
    )
    finished_check_timeout_sec = max(
        1.0,
        _resolve_quickscout_runtime_param("QUICKSCOUT_FINISHED_CHECK_TIMEOUT_SEC", 5.0),
    )
    progress_stream_timeout_sec = max(
        0.1,
        min(
            poll_interval_sec,
            _resolve_quickscout_runtime_param("QUICKSCOUT_PROGRESS_STREAM_TIMEOUT_SEC", 0.5),
        ),
    )

    deadline = time.monotonic() + runtime_limit_sec
    mission_progress_iter = drone.mission.mission_progress().__aiter__()
    position_iter = drone.telemetry.position().__aiter__()
    last_position = startup_position
    distance_covered_m = 0.0
    last_progress_current = 0
    last_progress_total = total_waypoints
    last_reported_signature = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"QuickScout mission runtime exceeded {runtime_limit_sec:.0f}s without finishing."
            )

        try:
            position = await asyncio.wait_for(position_iter.__anext__(), timeout=min(poll_interval_sec, remaining))
            if last_position is not None:
                distance_covered_m += _estimate_distance_from_positions(last_position, position)
            last_position = position
        except asyncio.TimeoutError:
            pass
        except StopAsyncIteration:
            position_iter = drone.telemetry.position().__aiter__()

        try:
            progress = await asyncio.wait_for(
                mission_progress_iter.__anext__(),
                timeout=min(progress_stream_timeout_sec, remaining),
            )
            current = int(getattr(progress, "current", 0) or 0)
            total = int(getattr(progress, "total", total_waypoints) or total_waypoints)
            if current != last_progress_current or total != last_progress_total:
                logger.info("QuickScout mission progress: waypoint %s/%s", current, total)
            last_progress_current = current
            last_progress_total = total
        except asyncio.TimeoutError:
            pass
        except StopAsyncIteration:
            mission_progress_iter = drone.mission.mission_progress().__aiter__()

        status_signature = (last_progress_current, last_progress_total, int(distance_covered_m))
        if status_signature != last_reported_signature:
            report_progress(
                gcs_url,
                mission_id,
                hw_id,
                last_progress_current,
                max(1, last_progress_total),
                distance_covered_m,
                state="executing",
            )
            last_reported_signature = status_signature

        finished = await asyncio.wait_for(
            drone.mission.is_mission_finished(),
            timeout=min(finished_check_timeout_sec, remaining),
        )
        if finished:
            logger.info(
                "QuickScout mission finished. Final progress=%s/%s, distance=%.1fm",
                last_progress_current,
                last_progress_total,
                distance_covered_m,
            )
            return {
                "current": max(last_progress_current, total_waypoints),
                "total": max(last_progress_total, total_waypoints),
                "distance_covered_m": distance_covered_m,
            }

        await asyncio.sleep(poll_interval_sec)


def parse_args():
    parser = argparse.ArgumentParser(description='QuickScout Mission Executor')
    parser.add_argument('--waypoints-file', required=True, help='Path to waypoints JSON file')
    parser.add_argument('--mission-id', required=True, help='Mission ID for progress reporting')
    parser.add_argument('--hw-id', required=True, help='Hardware ID of this drone')
    parser.add_argument('--return-behavior', default='return_home',
                        choices=['return_home', 'land_current', 'hold_position'],
                        help='End-of-mission behavior')
    parser.add_argument('--gcs-url', default=None, help='GCS server URL for progress reports')
    return parser.parse_args()


def load_waypoints(filepath):
    """Load waypoints from JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def coerce_optional_float(value, default):
    """Convert optional numeric payload fields to floats with an explicit fallback."""
    if value is None:
        return default
    return float(value)


def report_progress(gcs_url, mission_id, hw_id, waypoint_index, total_waypoints, distance_m=0, state=None):
    """Report progress to GCS server (best-effort, non-blocking)."""
    if not gcs_url:
        return
    try:
        data = {
            'hw_id': hw_id,
            'current_waypoint_index': waypoint_index,
            'total_waypoints': total_waypoints,
            'distance_covered_m': distance_m,
        }
        if state:
            data['state'] = state
        requests.post(
            f"{gcs_url}/api/sar/mission/{mission_id}/progress",
            json=data, timeout=2
        )
    except Exception:
        pass


async def run_mission(args):
    """Main mission execution."""
    led = None
    mavsdk_server = None
    try:
        led = LEDController.get_instance()
    except Exception:
        logger.warning("LED controller not available")

    if led:
        led.set_color(0, 0, 255)  # Blue: initializing

    logger.info(f"Loading waypoints from {args.waypoints_file}")
    waypoints = load_waypoints(args.waypoints_file)
    total_waypoints = len(waypoints)
    logger.info(f"Loaded {total_waypoints} waypoints for mission {args.mission_id}")

    if total_waypoints == 0:
        logger.error("No waypoints to execute")
        return 1

    gcs_url = args.gcs_url
    if not gcs_url:
        gcs_ip = os.environ.get('GCS_IP', '127.0.0.1')
        gcs_port = getattr(Params, 'gcs_port', 5000)
        gcs_url = f"http://{gcs_ip}:{gcs_port}"

    grpc_port = getattr(Params, 'DEFAULT_GRPC_PORT', 50040)
    connect_timeout = max(float(getattr(Params, 'LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC', 5.0)), 10.0)
    readiness_timeout = max(float(getattr(Params, 'PRE_FLIGHT_TIMEOUT', 80.0)), 30.0)
    mission_upload_timeout = max(
        5.0,
        _resolve_quickscout_runtime_param("QUICKSCOUT_MISSION_UPLOAD_TIMEOUT_SEC", 45.0),
    )
    mission_start_timeout = max(
        5.0,
        _resolve_quickscout_runtime_param("QUICKSCOUT_MISSION_START_TIMEOUT_SEC", 30.0),
    )
    mission_airborne_timeout = max(
        15.0,
        _resolve_quickscout_runtime_param("QUICKSCOUT_AIRBORNE_TIMEOUT_SEC", 120.0),
    )
    post_action_timeout = max(
        30.0,
        _resolve_quickscout_runtime_param("QUICKSCOUT_POST_ACTION_TIMEOUT_SEC", 240.0),
    )

    try:
        mavsdk_server = start_mavsdk_server(grpc_port, Params.mavsdk_port)
        drone = System(mavsdk_server_address="127.0.0.1", port=grpc_port)
        logger.info(f"Connecting to drone via MAVSDK on gRPC port {grpc_port}")
        await asyncio.wait_for(
            drone.connect(system_address=f"udp://:{Params.mavsdk_port}"),
            timeout=connect_timeout,
        )

        logger.info("Waiting for drone connection...")
        await wait_for_drone_connection(drone, connect_timeout)
        logger.info("Drone connected")

        logger.info("Waiting for local mission startup readiness...")
        await wait_for_local_startup_ready(readiness_timeout)
        logger.info("Local mission startup readiness confirmed")

        home_position = get_local_home_position()
        home_alt_msl = float(home_position["altitude"])
        logger.info(
            "Home position: %.6f, %.6f, alt=%.1fm MSL",
            float(home_position["latitude"]),
            float(home_position["longitude"]),
            home_alt_msl,
        )

        if led:
            led.set_color(255, 255, 0)  # Yellow: building mission

        MIN_SURVEY_ALT_AGL = 10.0  # Safety floor: minimum relative altitude (meters)
        mission_items = []
        camera_running = False
        for i, wp in enumerate(waypoints):
            lat = wp['lat']
            lng = wp['lng']
            alt_msl = coerce_optional_float(wp.get('alt_msl', 50.0), 50.0)
            is_survey = wp.get('is_survey_leg', True)
            speed = coerce_optional_float(wp.get('speed_ms', 5.0), 5.0)
            yaw = coerce_optional_float(wp.get('yaw_deg'), float('nan'))

            relative_alt = alt_msl - home_alt_msl

            # Camera control: start on first survey waypoint, stop when leaving survey
            camera_action = MissionItem.CameraAction.NONE
            if is_survey and not camera_running:
                camera_action = MissionItem.CameraAction.START_PHOTO_INTERVAL
                camera_running = True
            elif not is_survey and camera_running:
                camera_action = MissionItem.CameraAction.STOP_PHOTO_INTERVAL
                camera_running = False

            camera_interval = (
                coerce_optional_float(wp.get('camera_interval_s', 2.0), 2.0)
                if camera_action == MissionItem.CameraAction.START_PHOTO_INTERVAL
                else float('nan')
            )

            item = MissionItem(
                latitude_deg=lat,
                longitude_deg=lng,
                relative_altitude_m=max(relative_alt, MIN_SURVEY_ALT_AGL),
                speed_m_s=speed,
                is_fly_through=True,
                gimbal_pitch_deg=float('nan'),
                gimbal_yaw_deg=float('nan'),
                camera_action=camera_action,
                loiter_time_s=float('nan'),
                camera_photo_interval_s=camera_interval,
                acceptance_radius_m=3.0,
                yaw_deg=yaw,
                camera_photo_distance_m=float('nan'),
                vehicle_action=(
                    MissionItem.VehicleAction.TAKEOFF
                    if i == 0
                    else MissionItem.VehicleAction.NONE
                ),
            )
            mission_items.append(item)

        logger.info(f"Uploading mission with {len(mission_items)} items...")
        mission_plan = MissionPlan(mission_items)
        await asyncio.wait_for(
            drone.mission.upload_mission(mission_plan),
            timeout=mission_upload_timeout,
        )
        logger.info("Mission uploaded successfully")

        if led:
            led.set_color(255, 255, 255)  # White: ready

        logger.info("Arming drone...")
        await arm_with_preflight_gate(
            drone,
            require_global_position=True,
            logger=logger,
        )
        logger.info("Drone armed")

        logger.info("Starting mission...")
        await asyncio.wait_for(
            drone.mission.start_mission(),
            timeout=mission_start_timeout,
        )
        logger.info("Mission started")

        startup_position = await _wait_for_mission_airborne(
            drone,
            min_gain_m=max(
                0.5,
                _resolve_quickscout_runtime_param("QUICKSCOUT_AIRBORNE_MIN_GAIN_M", 2.0),
            ),
            timeout_sec=mission_airborne_timeout,
        )

        report_progress(gcs_url, args.mission_id, args.hw_id, 0, total_waypoints, state='executing')

        if led:
            led.set_color(0, 255, 0)  # Green: surveying

        mission_result = await _monitor_active_mission(
            drone,
            gcs_url=gcs_url,
            mission_id=args.mission_id,
            hw_id=args.hw_id,
            total_waypoints=total_waypoints,
            startup_position=startup_position,
        )
        distance_covered = float(mission_result["distance_covered_m"])
        completed_current = int(mission_result["current"])
        completed_total = int(mission_result["total"])

        logger.info(f"Mission complete. Total distance: {distance_covered:.0f}m")
        report_progress(
            gcs_url,
            args.mission_id,
            args.hw_id,
            completed_current,
            completed_total,
            distance_covered,
            state='completed',
        )

        if args.return_behavior == 'return_home':
            logger.info("Returning to home...")
            await drone.action.return_to_launch()
        elif args.return_behavior == 'land_current':
            logger.info("Landing at current position...")
            await drone.action.land()
        elif args.return_behavior == 'hold_position':
            logger.info("Holding position...")

        if args.return_behavior in ('return_home', 'land_current'):
            from mavsdk.telemetry import LandedState
            landed_iter = drone.telemetry.landed_state().__aiter__()
            deadline = time.monotonic() + post_action_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting for QuickScout post-mission {args.return_behavior} completion."
                    )
                landed_state = await asyncio.wait_for(
                    landed_iter.__anext__(),
                    timeout=min(1.0, remaining),
                )
                if landed_state == LandedState.ON_GROUND:
                    logger.info("Drone landed")
                    break
            try:
                await drone.action.disarm()
                logger.info("Drone disarmed")
            except Exception:
                pass

        if led:
            led.set_color(0, 255, 255)  # Cyan: complete

        logger.info("QuickScout mission completed successfully")
        return 0
    except Exception as e:
        logger.exception(f"QuickScout mission failed: {e}")
        if led:
            led.set_color(255, 0, 0)
        return 1
    finally:
        stop_mavsdk_server(mavsdk_server)


def main():
    args = parse_args()
    exit_code = asyncio.run(run_mission(args))
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
