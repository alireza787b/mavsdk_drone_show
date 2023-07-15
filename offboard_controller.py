import logging
from mavsdk import System
from mavsdk.offboard import OffboardError, PositionNedYaw, VelocityNedYaw
import asyncio

class OffboardController:
    """
    This class encapsulates the logic to control a drone in offboard mode
    using the MAVSDK library.
    """
    
    def __init__(self, drone_config, mavsdk_server_address='localhost', port=50051):
        """
        The constructor for OffboardController class.
        """
        self.drone_config = drone_config
        self.drone = System(mavsdk_server_address, port)
        self.offboard_follow_update_interval = 0.2 # 200ms, adjust to your needs

    async def connect(self):
        """
        Connect to the drone.
        """
        await self.drone.connect()

        logging.info("Waiting for drone to connect...")
        async for state in self.drone.core.connection_state():
            if state.is_connected:
                logging.info("Drone discovered")
                break

    async def set_initial_position(self):
        """
        Set initial setpoint to the current position of the drone.
        """
        initial_pos = PositionNedYaw(
            self.drone_config.position_setpoint_NED['north'], 
            self.drone_config.position_setpoint_NED['east'], 
            self.drone_config.position_setpoint_NED['down'], 
            self.drone_config.yaw_setpoint)
        await self.drone.offboard.set_position_ned(initial_pos)
        
        logging.info(f"Initial setpoint: {initial_pos}")

    async def start_offboard(self):
        """
        Start offboard mode.
        """
        try:
            await self.drone.offboard.start()
            logging.info("Offboard start")                    
        except OffboardError as error:
            logging.error(f"Starting offboard mode failed with error code: {error._result.result}")
            return

    async def maintain_position_velocity(self):
        """
        Continuously set position and velocity setpoints.
        """
        while True:
            pos_ned_yaw = PositionNedYaw(
                self.drone_config.position_setpoint_NED['north'],
                self.drone_config.position_setpoint_NED['east'],
                self.drone_config.position_setpoint_NED['down'],
                self.drone_config.target_drone.yaw_setpoint
            )

            vel_ned_yaw = VelocityNedYaw(
                self.drone_config.velocity_setpoint_NED['vel_n'],
                self.drone_config.velocity_setpoint_NED['vel_e'],
                self.drone_config.velocity_setpoint_NED['vel_d'],
                self.drone_config.yaw_setpoint
            )

            await self.drone.offboard.set_position_velocity_ned(pos_ned_yaw, vel_ned_yaw)
            logging.info(f"Setpoint sent | Position: [N:{self.drone_config.position_setpoint_NED.get('north')}, E:{self.drone_config.position_setpoint_NED.get('east')}, D:{self.drone_config.position_setpoint_NED.get('down')}] | Velocity: [N:{self.drone_config.velocity_setpoint_NED.get('vel_n')}, E:{self.drone_config.velocity_setpoint_NED.get('vel_e')}, D:{self.drone_config.velocity_setpoint_NED.get('vel_d')}] | yaw: {self.drone_config.yaw_setpoint} following drone {self.drone_config.target_drone.hw_id}, with offsets [N:{self.drone_config.swarm.get('offset_n', 0)},E:{self.drone_config.swarm.get('offset_e', 0)},Alt:{self.drone_config.swarm.get('offset_alt', 0)}]")
            await asyncio.sleep(self.offboard_follow_update_interval)
