"""
    
    The initial position of each drone is determined by the spawn_model function in the script. The X and Y coordinates are set as follows:
X coordinate: X=${X:=0.0}
Y coordinate: Y=${Y:=$((3*${N}))}
Here, N is the instance number of the drone. The X coordinate is set to 0.0, and the Y coordinate is set to 3 times the instance number. This means that the drones are spawned in a straight line along the Y-axis, with a distance of 3 units between each drone.
"""
import os
import asyncio
from mavsdk import System
import csv
from mavsdk.offboard import PositionNedYaw, VelocityNedYaw, AccelerationNed, OffboardError
from mavsdk.telemetry import LandedState
from mavsdk.action import ActionError
from mavsdk.telemetry import *
import subprocess
import signal
global_position_telemetry = {}


async def get_global_position_telemetry(drone_id, drone):
    async for global_position in drone.telemetry.position():
        global_position_telemetry[drone_id] = global_position
        break
    


async def get_global_position_telemetry(drone_id, drone):
    async for global_position in drone.telemetry.position():
        global_position_telemetry[drone_id] = global_position
        break

async def run_drone(drone_id, trajectory_offset, udp_port, time_offset, altitude_offset):
    grpc_port = 50040 + drone_id
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
    drone = System(mavsdk_server_address="127.0.0.1", port=grpc_port)
    await drone.connect(system_address=f"udp://:{udp_port}")
    print(f"Drone connecting with UDP: {udp_port}")
    
    
    #ensure futuretelem data
    asyncio.ensure_future(get_global_position_telemetry(drone_id, drone))
    
    
    
    # Add time offset before starting the maneuver
    await asyncio.sleep(time_offset)
    # Check if the drone is connected
    async for state in drone.core.connection_state():
        if state.is_connected:
            print(f"Drone id {drone_id} connected on Port: {udp_port} and grpc Port: {grpc_port}")
            break
    # Wait for the drone to have a global position estimate
    async for health in drone.telemetry.health():
        if health.is_global_position_ok:
            print(f"Global position estimate ok {drone_id}")
            break
    global_position_telemetry[drone_id] = global_position_telemetry[drone_id]
    print(f"Home Position of {drone_id} set to: {global_position_telemetry[drone_id]}")
    print(f"-- Arming {drone_id}")
    await drone.action.arm()
    print(f"-- Setting initial setpoint {drone_id}")
    await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, 0.0, 0.0))
    

    print(f"-- Starting offboard {drone_id}")
    try:
        await drone.offboard.start()
    except OffboardError as error:
        # print(f"Starting offboard mode {drone_id} failed with error code: {error._result.result}")
        print(f"-- Disarming {drone_id}")
        await drone.action.disarm()
        return

    waypoints = []

    # Read data from the CSV file
    with open("shapes/active.csv", newline="") as csvfile:
        
        reader = csv.DictReader(csvfile)
        for row in reader:
            t = float(row["t"])
            px = float(row["px"]) + trajectory_offset[0]
            py = float(row["py"]) + trajectory_offset[1]
            pz = float(row["pz"]) + trajectory_offset[2] -  altitude_offset
            vx = float(row["vx"])
            vy = float(row["vy"])
            vz = float(row["vz"])
            ax = float(row["ax"])
            ay = float(row["ay"])
            az = float(row["az"])
            yaw = float(row["yaw"])
            mode_code = int(row["mode"])  # Assuming the mode code is in a column named "mode"
            
        
            waypoints.append((t, px, py, pz, vx, vy, vz,ax,ay,az,mode_code))

    print(f"-- Performing trajectory {drone_id}")
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
        acceleration = current_waypoint[7:10]  # Extract acceleration (ax, ay, az)
        mode_code = current_waypoint[-1]
        if last_mode != mode_code:
                # Print the mode number and its description
                print(f"Drone id: {drone_id}: Mode number: {mode_code}, Description: {mode_descriptions[mode_code]}")
                last_mode = mode_code
                
        await drone.offboard.set_position_velocity_acceleration_ned(
            PositionNedYaw(*position, yaw),
            VelocityNedYaw(*velocity, yaw),
            AccelerationNed(*acceleration)
        )

        await asyncio.sleep(0.1)  # Time resolution of 0.1 seconds
        t += 0.1

    print(f"-- Shape completed {drone_id}")

    # print(f"-- Returning to home {drone_id}")
    # await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, -10.0, 0.0))
    # await asyncio.sleep(5)  # Adjust as needed for a stable hover

    print(f"-- Landing {drone_id}")
    await drone.action.land()

    async for state in drone.telemetry.landed_state():
        if state == LandedState.ON_GROUND:
            break

    print(f"-- Stopping offboard {drone_id}")
    try:
        await drone.offboard.stop()
    except Exception as error:
        print(f"Stopping offboard mode failed with error: {error}")

    print(f"-- Disarming {drone_id}")
    await drone.action.disarm()

async def main():
    num_drones = 5 + 1
    time_offset = 1

    # Define altitude offsets for each drone
    altitude_steps = 0.5
    altitude_offsets = [altitude_steps*i for i in range(num_drones)]

    #relative to drone 0
    home_positions = [(0, 3*i, 0) for i in range(num_drones)]
    traejctory_offset = [(0, 0, 0) for i in range(num_drones)]
    udp_ports = [14540 + i for i in range(num_drones)]

    # Start mavsdk_server instances for each drone
    mavsdk_servers = []
    for i in range(num_drones):
        port = 50040 + i
        mavsdk_server = subprocess.Popen(["./mavsdk_server", "-p", str(port), f"udp://:{udp_ports[i]}"])
        mavsdk_servers.append(mavsdk_server)
        # await asyncio.sleep(1)

    tasks = []
    for i in range(num_drones):
        tasks.append(asyncio.create_task(run_drone(i, traejctory_offset[i], udp_ports[i], i*time_offset, altitude_offsets[i])))

    await asyncio.gather(*tasks)

    # Kill all mavsdk_server processes
    for mavsdk_server in mavsdk_servers:
        os.kill(mavsdk_server.pid, signal.SIGTERM)

    print("All tasks completed. Exiting program.")

if __name__ == "__main__":
    asyncio.run(main())