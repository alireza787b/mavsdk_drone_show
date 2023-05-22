"""
Script: offboard_from_csv.py

Description:
-------------
The offboard_from_csv.py script is responsible for controlling a drone in an offboard mode using a trajectory defined in a CSV file. The script establishes a connection with the drone, reads the trajectory data from the CSV file, and commands the drone to follow the trajectory. At the end of the trajectory, the drone returns to its home position and lands.

Prerequisites:
--------------
- The script requires the MAVSDK library to be installed. Refer to the MAVSDK documentation for installation instructions.
- Ensure that the drone is properly set up for offboard control and has a valid global position estimate.

Usage:
------
1. Connect the drone to the system running this script.
2. Ensure that the drone has a valid global position estimate.
3. Run the script using the command: python offboard_from_csv.py

Inputs:
-------
The offboard_from_csv.py script expects the following inputs:
- CSV file: The trajectory data in CSV format should be located at "shapes/active.csv" relative to the script's location.

Outputs:
--------
The script controls the drone to follow the trajectory defined in the CSV file. The drone performs the desired trajectory and returns to its home position to land.

Example Usage:
--------------
1. Ensure that the drone is connected to the system and has a valid global position estimate.
2. Place the trajectory data in CSV format in the "shapes/active.csv" file.
3. Run the script using the command: python offboard_from_csv.py

Additional Information:
-----------------------
- If you are unfamiliar with using the MAVSDK library for controlling drones, refer to the video tutorial provided in the GitHub repository (alireza787b) for a step-by-step guide.

Note:
-----
- Make sure that the drone is properly configured for offboard control before running this script.
- Adjust the time resolution (0.1 seconds) in the script if needed for your application.
- Uncomment the lines to change the flight mode or include additional functionality as required.
"""




import asyncio
import csv
import os

from mavsdk import System
from mavsdk.offboard import PositionNedYaw, VelocityNedYaw, AccelerationNed , OffboardError
from mavsdk.telemetry import LandedState
import subprocess
import signal


async def run():
    
    # Define a dictionary to map mode codes to their descriptions
    mode_descriptions = {
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
    grpc_port = 50040
    drone = System(mavsdk_server_address="127.0.0.1", port=grpc_port)
    await drone.connect(system_address="udp://:14540")

    print("Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("-- Connected to drone!")
            break

    print("Waiting for drone to have a global position estimate...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("-- Global position estimate OK")
            break

    print("-- Arming")
    await drone.action.arm()

    print("-- Setting initial setpoint")
    await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, 0.0, 0.0))

    print("-- Starting offboard")
    try:
        await drone.offboard.start()
    except OffboardError as error:
        print(f"Starting offboard mode failed with error code: {error._result.result}")
        print("-- Disarming")
        await drone.action.disarm()
        return

    waypoints = []

    # Read data from the CSV file
    with open("shapes/active.csv", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
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
            mode_code = int(row["mode"])  # Assuming the mode code is in a column named "mode"
        
        
            waypoints.append((t, px, py, pz, vx, vy, vz,ax,ay,az,mode_code))

    print("-- Performing trajectory")
    total_duration = waypoints[-1][0]  # Total duration is the time of the last waypoint
    t = 0  # Time variable
    last_mode = 0
    while t <= total_duration:
        # Find the current waypoint based on time
        current_waypoint = None
        for waypoint in waypoints:
            if t <= waypoint[0]:
                current_waypoint = waypoint
                break

        if current_waypoint is None:
            # Reached the end of the trajectory
            break

        position = current_waypoint[1:4]  # Extract position (px, py, pz)
        velocity = current_waypoint[4:7]  # Extract velocity (vx, vy, vz)
        acceleration = current_waypoint[7:10]  # Extract velocity (ax, ay, az)
        mode_code = current_waypoint[-1]
        if last_mode != mode_code:
                # Print the mode number and its description
                print(f" Mode number: {mode_code}, Description: {mode_descriptions[mode_code]}")
                last_mode = mode_code
                
        await drone.offboard.set_position_velocity_acceleration_ned(
            PositionNedYaw(*position, yaw),
            VelocityNedYaw(*velocity, yaw),
            AccelerationNed(*acceleration)
        )
        # await drone.offboard.set_position_velocity_ned(
        #     PositionNedYaw(*position, yaw),
        #     VelocityNedYaw(*velocity, yaw),
        # )

        await asyncio.sleep(0.1)  # Time resolution of 0.1 seconds
        t += 0.1

    print("-- Shape completed")

    # print("-- Returning to home")
    # await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, -10.0, 0.0))
    # await asyncio.sleep(5)  # Adjust as needed for a stable hover

    print("-- Landing")
    await drone.action.land()

    async for state in drone.telemetry.landed_state():
        if state == LandedState.ON_GROUND:
            break

    print("-- Stopping offboard")
    try:
        await drone.offboard.stop()
    except Exception as error:
        print(f"Stopping offboard mode failed with error: {error}")

    print("-- Disarming")
    await drone.action.disarm()

    # print("-- Changing flight mode")
    # await drone.action.set_flight_mode("MANUAL")

async def main():

    udp_port = 14540 

    # Start mavsdk_server 
    grpc_port = 50040 
    mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(grpc_port), f"udp://:{udp_port}"])
    # await asyncio.sleep(1)

    tasks = []
    tasks.append(asyncio.create_task(run()))

    await asyncio.gather(*tasks)

    # Kill  mavsdk_server 
    os.kill(mavsdk_server.pid, signal.SIGTERM)

    print("All tasks completed. Exiting program.")

if __name__ == "__main__":
    asyncio.run(main())