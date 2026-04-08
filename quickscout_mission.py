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

import requests
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight envs only
    psutil = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from params import Params
from led_controller import LEDController
from mds_logging import get_logger

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

        logger.info("Waiting for GPS fix...")
        await wait_for_navigation_health(drone, readiness_timeout)
        logger.info("GPS fix and home position OK")

        home_position = await get_home_position(drone, connect_timeout)
        home_alt_msl = home_position.absolute_altitude_m
        logger.info(
            "Home position: %.6f, %.6f, alt=%.1fm MSL",
            home_position.latitude_deg,
            home_position.longitude_deg,
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
            alt_msl = wp.get('alt_msl', 50.0)
            is_survey = wp.get('is_survey_leg', True)
            speed = wp.get('speed_ms', 5.0)
            yaw = wp.get('yaw_deg', float('nan'))

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
                wp.get('camera_interval_s', 2.0)
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
            )
            mission_items.append(item)

        logger.info(f"Uploading mission with {len(mission_items)} items...")
        mission_plan = MissionPlan(mission_items)
        await drone.mission.upload_mission(mission_plan)
        logger.info("Mission uploaded successfully")

        if led:
            led.set_color(255, 255, 255)  # White: ready

        logger.info("Arming drone...")
        await drone.action.arm()
        logger.info("Drone armed")

        logger.info("Starting mission...")
        await drone.mission.start_mission()
        logger.info("Mission started")

        report_progress(gcs_url, args.mission_id, args.hw_id, 0, total_waypoints, state='executing')

        if led:
            led.set_color(0, 255, 0)  # Green: surveying

        distance_covered = 0.0
        last_wp_index = -1

        async for progress in drone.mission.mission_progress():
            current = progress.current
            total = progress.total

            if current != last_wp_index:
                logger.info(f"Mission progress: waypoint {current}/{total}")
                if last_wp_index >= 0 and last_wp_index < len(waypoints) and current < len(waypoints):
                    wp_prev = waypoints[last_wp_index]
                    wp_curr = waypoints[min(current, len(waypoints) - 1)]
                    dlat = math.radians(wp_curr['lat'] - wp_prev['lat'])
                    dlng = math.radians(wp_curr['lng'] - wp_prev['lng'])
                    a = (math.sin(dlat/2)**2 +
                         math.cos(math.radians(wp_prev['lat'])) * math.cos(math.radians(wp_curr['lat'])) *
                         math.sin(dlng/2)**2)
                    distance_covered += 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                last_wp_index = current
                report_progress(gcs_url, args.mission_id, args.hw_id, current, total, distance_covered)

            if current >= total - 1 and total > 0:
                logger.info("Mission waypoints complete")
                break

        logger.info(f"Mission complete. Total distance: {distance_covered:.0f}m")
        report_progress(
            gcs_url,
            args.mission_id,
            args.hw_id,
            total_waypoints,
            total_waypoints,
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
            async for landed_state in drone.telemetry.landed_state():
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
