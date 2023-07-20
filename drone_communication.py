import csv
import logging
import socket
import struct
import time
from threading import Thread

from drone_config import DroneConfig
from config import Config as config

class DroneCommunicator:
    """
    Handles sending and receiving MAVLink packets for a drone.

    Attributes:
        config: Configuration object containing network settings.
        sock: Socket for sending/receiving packets.
        telem_thread: Thread for sending telemetry packets. 
        cmd_thread: Thread for receiving command packets.

    Methods:
        send_telemetry: Sends a telemetry packet to GCS/drones.
        receive_commands: Receives command packets from GCS.
        send_packet: Sends a packet to given IP/port.
        process_packet: Decodes and handles an incoming packet.
    """

    def __init__(self, config=config):
        """Initializes the drone communicator."""
        self.config = config

        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Threads for telemetry and commands
        self.telem_thread = Thread(target=self.send_telemetry)
        self.cmd_thread = Thread(target=self.receive_commands)

        # Start the threads
        self.telem_thread.start()
        self.cmd_thread.start()

    def send_telemetry(self):
        """Sends telemetry packets to GCS/drones."""
        udp_ip = self.config.gcs_ip
        udp_port = int(self.config.debug_port)

        while True:
            drone_state = self.get_drone_state()

            # Create a struct format string based on the data types
            telem_struct_fmt = '=BHHBBIddddddddBB'
            # H is for uint16
            # B is for uint8
            # I is for uint32
            # d is for double (float64)

            # Pack the telemetry data into a binary packet
            packet = struct.pack(telem_struct_fmt,
                                 77,  # start of packet
                                 drone_state['hw_id'],
                                 drone_state['pos_id'],
                                 drone_state['state'],
                                 drone_state['mission'],
                                 drone_state['trigger_time'],
                                 drone_state['position_lat'],
                                 drone_state['position_long'],
                                 drone_state['position_alt'],
                                 drone_state['velocity_north'],
                                 drone_state['velocity_east'],
                                 drone_state['velocity_down'],
                                 drone_state['yaw'],
                                 drone_state['battery_voltage'],
                                 drone_state['follow_mode'],
                                 88)  # end of packet

            # If broadcast_mode is True, send to all nodes
            if self.config.broadcast_mode:
                nodes = self.get_nodes()
                # Send to all other nodes
                for node in nodes:
                    if int(node["hw_id"]) != drone_state['hw_id']:
                        self.send_packet(packet, node["ip"], int(node["debug_port"]))

            # Always send to GCS
            self.send_packet(packet, udp_ip, udp_port)

            time.sleep(self.config.TELEM_SEND_INTERVAL)

    def receive_commands(self):
        """Receives command packets from GCS."""
        udp_port = int(self.config.debug_port)

        self.sock.bind(('0.0.0.0', udp_port))

        while True:
            data, addr = self.sock.recvfrom(1024)
            self.process_packet(data)

            if self.drone_state['mission'] == 2 and self.drone_state['state'] != 0 and int(self.drone_state['follow_mode']) != 0:
                self.calculate_setpoints()

            time.sleep(self.config.income_packet_check_interval)

    def send_packet(self, packet, ip, port):
        """Sends a packet to the given IP/port."""
        self.sock.sendto(packet, (ip, port))

    def process_packet(self, data):
        """Decodes and handles an incoming packet."""
        header, terminator = struct.unpack('BB', data[0:1] + data[-1:])

        # Check if it's a command packet
        if header == 55 and terminator == 66 and len(data) == self.config.command_packet_size:
            header, hw_id, pos_id, mission, state, trigger_time, terminator = struct.unpack(self.config.command_struct_fmt, data)
            logging.info(f"Received command from GCS: hw_id: {hw_id}, pos_id: {pos_id}, mission: {mission}, state: {state}, trigger_time: {trigger_time}")

            self.drone_state['hw_id'] = hw_id
            self.drone_state['pos_id'] = pos_id
            self.drone_state['mission'] = mission
            self.drone_state['state'] = state
            self.drone_state['trigger_time'] = trigger_time

            # Add additional logic here to handle the received command
        elif header == 77 and terminator == 88 and len(data) == self.config.telem_packet_size:
            # Decode the data
            header, hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, yaw, battery_voltage, follow_mode, terminator = struct.unpack(self.config.telem_struct_fmt, data)
            logging.debug(f"Received telemetry from Drone {hw_id}")

            if hw_id not in self.drones:
                # Create a new instance for the drone
                self.drones[hw_id] = DroneConfig(hw_id)

            position = {'lat': position_lat, 'long': position_long, 'alt': position_alt}
            velocity = {'vel_n': velocity_north, 'vel_e': velocity_east, 'vel_d': velocity_down}

            self.set_drone_config(hw_id, pos_id, state, mission, trigger_time, position, velocity, yaw, battery_voltage, time.time())

            # Add processing of the received telemetry data here
        else:
            logging.error(f"Received packet of incorrect size or header. Got {len(data)} bytes.")

    def get_nodes(self):
        """Reads the node information from the config file."""
        # Cache nodes to avoid reading the file every time
        if hasattr(self.get_nodes, "nodes"):
            return self.get_nodes.nodes

        with open("config.csv", "r") as file:
            self.get_nodes.nodes = list(csv.DictReader(file))

        return self.get_nodes.nodes

    def set_drone_config(self, hw_id, pos_id, state, mission, trigger_time, position, velocity, yaw, battery, last_update_timestamp):
        drone = self.drones.get(hw_id, DroneConfig(hw_id))
        drone.pos_id = pos_id
        drone.state = state
        drone.mission = mission
        drone.trigger_time = trigger_time
        drone.position = position
        drone.velocity = velocity
        drone.yaw = yaw
        drone.battery = battery
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
            "hw_id": int(self.drone_config['hw_id']),
            "pos_id": int(self.drone_config['pos_id']),
            "state": int(self.drone_config['state']),
            "mission": int(self.drone_config['mission']),
            "trigger_time": int(self.drone_config['trigger_time']),
            "position_lat": self.drone_config['position']['lat'],
            "position_long": self.drone_config['position']['long'],
            "position_alt": self.drone_config['position']['alt'],
            "velocity_north": self.drone_config['velocity']['vel_n'],
            "velocity_east": self.drone_config['velocity']['vel_e'],
            "velocity_down": self.drone_config['velocity']['vel_d'],
            "yaw": self.drone_config['yaw'],
            "battery_voltage": self.drone_config['battery'],
            "follow_mode": int(self.drone_config['follow'])
        }

        return drone_state
