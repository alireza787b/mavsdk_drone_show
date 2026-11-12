"""
Drone Class
===========
Represents a single drone in the swarm show system.

This module provides the Drone class which encapsulates drone configuration,
MAVSDK connection, trajectory waypoints, and flight control methods.
"""

import csv
from mavsdk_grpc.system import System

from src.constants import NetworkDefaults, TrajectoryState


class Drone:
    """
    Represents a single drone in the swarm system.

    Each Drone instance manages:
    - Connection to MAVSDK server via gRPC
    - Trajectory waypoints loaded from CSV
    - Home position and offset tracking
    - Flight mode descriptions

    Attributes:
        hw_id: Hardware ID of the drone
        pos_id: Position ID for show choreography
        x, y: Initial position coordinates
        ip: Network IP address
        mavlink_port: MAVLink communication port
        grpc_port: gRPC port for MAVSDK connection
        drone: MAVSDK System instance
        waypoints: List of trajectory waypoints
        home_position: GPS home position
        trajectory_offset: (x, y, z) offset for trajectory
        altitude_offset: Altitude adjustment in meters
        time_offset: Time offset for synchronization
    """

    def __init__(self, config):
        """
        Initialize a Drone instance.

        Args:
            config: Configuration object with drone settings including
                    hw_id, pos_id, x, y, ip, and mavlink_port
        """
        self.hw_id = config.hw_id
        self.pos_id = config.pos_id
        self.x = config.x
        self.y = config.y
        self.ip = config.ip
        self.mavlink_port = config.mavlink_port
        # Note: debug_port and gcs_ip removed - now centralized in Params.py
        self.grpc_port = NetworkDefaults.GRPC_BASE_PORT + int(self.hw_id)
        self.drone = System(mavsdk_server_address="127.0.0.1", port=self.grpc_port)
        self.waypoints = []
        # Mode descriptions now come from TrajectoryState enum
        self.mode_descriptions = {
            0: "On the ground",
            TrajectoryState.INITIAL_CLIMB: TrajectoryState.get_description(TrajectoryState.INITIAL_CLIMB),
            TrajectoryState.HOLDING_AFTER_CLIMB: TrajectoryState.get_description(TrajectoryState.HOLDING_AFTER_CLIMB),
            TrajectoryState.MOVING_TO_START: TrajectoryState.get_description(TrajectoryState.MOVING_TO_START),
            TrajectoryState.HOLDING_AT_START: TrajectoryState.get_description(TrajectoryState.HOLDING_AT_START),
            TrajectoryState.MOVING_TO_MANEUVER: TrajectoryState.get_description(TrajectoryState.MOVING_TO_MANEUVER),
            TrajectoryState.HOLDING_AT_MANEUVER: TrajectoryState.get_description(TrajectoryState.HOLDING_AT_MANEUVER),
            TrajectoryState.MANEUVERING: TrajectoryState.get_description(TrajectoryState.MANEUVERING),
            TrajectoryState.HOLDING_AT_END: TrajectoryState.get_description(TrajectoryState.HOLDING_AT_END),
            TrajectoryState.RETURNING_HOME: TrajectoryState.get_description(TrajectoryState.RETURNING_HOME),
            TrajectoryState.LANDING: TrajectoryState.get_description(TrajectoryState.LANDING)
        }
        self.home_position = None
        self.trajectory_offset = (0, 0, 0)
        self.altitude_offset = 0
        self.time_offset = 0

    async def connect(self):
        """
        Connect to the drone via MAVSDK.

        Establishes UDP connection to the drone's MAVLink port and waits
        for connection confirmation and valid global position estimate.
        Sets the home_position once GPS is available.
        """
        # For SITL/local connections, mavlink_port is just the port number
        # mavlink-router handles routing, so we connect via localhost
        system_address = f"udp://127.0.0.1:{self.mavlink_port}"
        await self.drone.connect(system_address=system_address)
        print(f"Drone connecting with UDP: {system_address}")
        async for state in self.drone.core.connection_state():
            if state.is_connected:
                print(f"Drone id {self.hw_id} connected on Port: {self.mavlink_port} and grpc Port: {self.grpc_port}")
                break
        async for health in self.drone.telemetry.health():
            if health.is_global_position_ok:
                print(f"Global position estimate ok {self.hw_id}")
                async for global_position in self.drone.telemetry.position():
                    self.home_position = global_position
                    print(f"Home Position of {self.hw_id} set to: {self.home_position}")
                    break
                break

    async def read_trajectory(self, filename):
        """
        Load trajectory waypoints from a CSV file.

        Reads waypoint data including position, velocity, acceleration,
        yaw, and mode code. Applies trajectory and altitude offsets.

        Args:
            filename: Path to the trajectory CSV file

        The CSV must have columns: t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode
        """
        # Read data from the CSV file
        with open(filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                t = float(row["t"])
                px = float(row["px"]) + self.trajectory_offset[0]
                py = float(row["py"]) + self.trajectory_offset[1]
                pz = float(row["pz"]) + self.trajectory_offset[2] -  self.altitude_offset
                vx = float(row["vx"])
                vy = float(row["vy"])
                vz = float(row["vz"])
                ax = float(row["ax"])
                ay = float(row["ay"])
                az = float(row["az"])
                yaw = float(row["yaw"])
                mode_code = int(row["mode"])  # Assuming the mode code is in a column named "mode"

                self.waypoints.append((t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode_code))
    async def perform_trajectory(self):
        """
        Execute the loaded trajectory waypoints.

        Iterates through waypoints and sends goto commands for maneuvering
        waypoints. Uses TrajectoryState to determine when the drone is
        actively maneuvering vs holding position.
        """
        print(f"Drone {self.hw_id} starting trajectory.")
        for waypoint in self.waypoints:
            t, px, py, pz, vx, vy, vz, ax, ay, az, yaw, mode_code = waypoint

            if TrajectoryState.is_maneuvering(mode_code):  # If the mode code is for maneuvering (trajectory)
                print(f"Drone {self.hw_id} maneuvering.")
                # Send the waypoint to the drone
                await self.drone.action.goto_location(px, py, pz, yaw)

            # Add any other conditions for different mode codes as necessary
            # ...

            # You can add a delay here if necessary, for example to wait until the drone reaches the waypoint
            # before sending the next one. The length of the delay will depend on your specific requirements.

        print(f"Drone {self.hw_id} finished trajectory.")