import logging
import struct
import socket
import time

from drone_config import DroneConfig


class DroneCommunicator:
    def __init__(self, params, drone_config, drones):
        self.params = params
        self.drone_config = drone_config
        self.drones = drones

    def process_packet(self, data):
        header, terminator = struct.unpack('BB', data[0:1] + data[-1:])  # get the header and terminator

        # Check if it's a command packet
        if header == 55 and terminator == 66 and len(data) == self.params.command_packet_size:
            header, hw_id, pos_id, mission, state, trigger_time, terminator = struct.unpack(self.params.command_struct_fmt, data)
            logging.info(f"Received command from GCS: hw_id: {hw_id}, pos_id: {pos_id}, mission: {mission}, state: {state}, trigger_time: {trigger_time}")

            self.drone_config.hw_id = hw_id
            self.drone_config.pos_id = pos_id
            self.drone_config.mission = mission
            self.drone_config.state = state
            self.drone_config.trigger_time = trigger_time

            # Add additional logic here to handle the received command
        elif header == 77 and terminator == 88 and len(data) == self.params.telem_packet_size:
            # Decode the data
            header, hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, yaw, battery_voltage, follow_mode, terminator = struct.unpack(self.params.telem_struct_fmt, data)
            logging.debug(f"Received telemetry from Drone {hw_id}")

            if hw_id not in self.drones:
                # Create a new instance for the drone
                logging.info(f"Receiving Telemetry from NEW Drone ID= {hw_id}")
                self.drones[hw_id] = DroneConfig(self.drones, hw_id)

            position = {'lat': position_lat, 'long': position_long, 'alt': position_alt}
            velocity = {'vel_n': velocity_north, 'vel_e': velocity_east, 'vel_d': velocity_down}
            
            self.set_drone_config(hw_id, pos_id, state, mission, trigger_time, position, velocity, yaw, battery_voltage, time.time())

            # Add processing of the received telemetry data here
        else:
            logging.error(f"Received packet of incorrect size or header. Got {len(data)} bytes.")

    def set_drone_config(self, hw_id, pos_id, state, mission, trigger_time, position, velocity, yaw, battery_voltage, last_update_timestamp):
        drone = self.drones.get(hw_id, DroneConfig(self.drones,hw_id))
        drone.pos_id = pos_id
        drone.state = state
        drone.mission = mission
        drone.trigger_time = trigger_time
        drone.position = position
        drone.velocity = velocity
        drone.yaw = yaw
        drone.battery = battery_voltage
        drone.last_update_timestamp = last_update_timestamp

        self.drones[hw_id] = drone

    def get_drone_state(self):
        """
        Fetches the current state of the drone, including hardware id (hw_id), 
        position id (pos_id), current state, trigger time, position, velocity,
        battery voltage, and follow mode.
        
        The state variable indicates: 
        0 for unset trigger time, 1 for set trigger time, 2 for flying
        The trigger time is set to 0 if it has not been set yet

        Returns:
        dict: A dictionary containing the current state of the drone
        """
        drone_state = {
            "hw_id": self.drone_config.hw_id,
            "pos_id": self.drone_config.pos_id,
            "state": self.drone_config.state,
            "mission": self.drone_config.mission,
            "trigger_time": self.drone_config.trigger_time,
            "position_lat": self.drone_config.position['lat'],
            "position_long": self.drone_config.position['long'],
            "position_alt": self.drone_config.position['alt'],
            "velocity_north": self.drone_config.velocity['vel_n'],
            "velocity_east": self.drone_config.velocity['vel_e'],
            "velocity_down": self.drone_config.velocity['vel_d'],
            "yaw": self.drone_config.yaw,
            "battery_voltage": self.drone_config.battery,
            "follow_mode": self.drone_config.swarm['follow'],
        }

        return drone_state

