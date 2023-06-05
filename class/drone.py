import csv
from mavsdk.system import System


class Drone:
    def __init__(self, config):
        self.hw_id = config.hw_id
        self.pos_id = config.pos_id
        self.x = config.x
        self.y = config.y
        self.ip = config.ip
        self.mavlink_port = config.mavlink_port
        self.debug_port = config.debug_port
        self.gcs_ip = config.gcs_ip
        self.grpc_port = 50040 + int(self.hw_id)
        self.drone = System(mavsdk_server_address="127.0.0.1", port=self.grpc_port)
        self.waypoints = []
        self.mode_descriptions = {
            0: "On the ground",
            10: "Initial climbing state",
            20: "Initial holding after climb",
            30: "Moving to start point",
            40: "Holding at start point",
            50: "Moving to maneuvering start point",
            60: "Holding at maneuver start point",
            70: "Maneuvering (trajectory)",
            80: "Holding at the end of the trajectory coordinate",
            90: "Returning to home coordinate",
            100: "Landing"
        }
        self.home_position = None
        self.trajectory_offset = (0, 0, 0)
        self.altitude_offset = 0
        self.time_offset = 0

    async def connect(self):
        await self.drone.connect(system_address=f"udp://{self.mavlink_port}")
        print(f"Drone connecting with UDP: {self.mavlink_port}")
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

                self.waypoints.append((t, px, py, pz, vx, vy, vz,ax,ay,az,mode_code))
    async def perform_trajectory(self):
        print(f"Drone {self.hw_id} starting trajectory.")
        for waypoint in self.waypoints:
            t, px, py, pz, vx, vy, vz, ax, ay, az, mode_code = waypoint

            if mode_code == 70:  # If the mode code is for maneuvering (trajectory)
                print(f"Drone {self.hw_id} maneuvering.")
                # Send the waypoint to the drone
                await self.drone.action.goto_location(px, py, pz, yaw)

            # Add any other conditions for different mode codes as necessary
            # ...

            # You can add a delay here if necessary, for example to wait until the drone reaches the waypoint
            # before sending the next one. The length of the delay will depend on your specific requirements.

        print(f"Drone {self.hw_id} finished trajectory.")