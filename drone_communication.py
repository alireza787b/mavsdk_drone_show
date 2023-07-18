import socket
import threading
import csv
import struct
import logging
import time

from drone_config import DroneConfig

class DroneCommunicator:
    def __init__(self, drone_config, telem_send_interval, income_packet_check_interval, broadcast_mode, command_packet_size, telem_packet_size, command_struct_fmt, telem_struct_fmt):
        self.drone_config = drone_config
        self.telem_send_interval = telem_send_interval
        self.income_packet_check_interval = income_packet_check_interval
        self.broadcast_mode = broadcast_mode
        self.command_packet_size = command_packet_size
        self.telem_packet_size = telem_packet_size
        self.command_struct_fmt = command_struct_fmt
        self.telem_struct_fmt = telem_struct_fmt
        self.drones = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', int(self.drone_config.config['debug_port'])))
      
    def send_packet_to_node(self, packet, ip, port):
        self.sock.sendto(packet, (ip, port))

    def get_nodes(self):
        if hasattr(self.get_nodes, "nodes"):
            return self.get_nodes.nodes
        with open("config.csv", "r") as file:
            self.get_nodes.nodes = list(csv.DictReader(file))
        return self.get_nodes.nodes

    def set_drone_config(self, hw_id, pos_id, state, mission, trigger_time, position, velocity, yaw, battery, last_update_timestamp):
        drone = self.drones.get(hw_id, self.drone_config(hw_id))
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

    
    def process_packet(self,data):
        header, terminator = struct.unpack('BB', data[0:1] + data[-1:])  # get the header and terminator

        # Check if it's a command packet
        if header == 55 and terminator == 66 and len(data) == self.command_packet_size:
            header, hw_id, pos_id, mission, state, trigger_time, terminator = struct.unpack(self.command_struct_fmt, data)
            logging.info(f"Received command from GCS: hw_id: {hw_id}, pos_id: {pos_id}, mission: {mission}, state: {state}, trigger_time: {trigger_time}")

            self.drone_config.hw_id = hw_id
            self.drone_config.pos_id = pos_id
            self.drone_config.mission = mission
            self.drone_config.state = state
            self.drone_config.trigger_time = trigger_time

            # Add additional logic here to handle the received command
        elif header == 77 and terminator == 88 and len(data) == self.telem_packet_size:
            # Decode the data
            header, hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, yaw, battery_voltage, follow_mode, terminator = struct.unpack(self.telem_struct_fmt, data)
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

    # Function to get the current state of the drone
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
        "hw_id": int(self.drone_config.hw_id),
        "pos_id": int(self.drone_config.config['pos_id']),
        "state": int(self.drone_config.state),
        "mission": int(self.drone_config.mission),
        "trigger_time": int(self.drone_config.trigger_time),
        "position_lat": self.drone_config.position['lat'],
        "position_long": self.drone_config.position['long'],
        "position_alt": self.drone_config.position['alt'],
        "velocity_north": self.drone_config.velocity['vel_n'],
        "velocity_east": self.drone_config.velocity['vel_e'],
        "velocity_down": self.drone_config.velocity['vel_d'],
        "yaw": self.drone_config.yaw,
        "battery_voltage": self.drone_config.battery,
        "follow_mode": int(self.drone_config.swarm['follow'])
        }


        return drone_state


    def send_drone_state(self):
        """
        Sends the drone state over UDP to the GCS and optionally to other drones in the swarm.

        The state information includes hardware id, position id, current state, 
        trigger time, position, velocity, battery voltage, and follow mode.
        
        Each state variable is packed into a binary packet and sent every `TELEM_SEND_INTERVAL` seconds.
        If `broadcast_mode` is True, the state is also sent to all other drones in the swarm.

        The structure of the packet is as follows:
        - Start of packet (uint8)
        - Hardware ID (uint16)
        - Position ID (uint16)
        - State (uint8)
        - Trigger Time (uint32)
        - Latitude, Longitude, Altitude (double)
        - North, East, Down velocities (double)
        - yaw (double)
        - Battery Voltage (double)
        - Follow Mode (uint8)
        - End of packet (uint8)
        """
        udp_ip = self.drone_config.config['gcs_ip']  # IP address of the ground station
        udp_port = int(self.drone_config.config['debug_port'])  # UDP port to send telemetry data to

        while True:
            drone_state = self.get_drone_state()

            # Create a struct format string based on the data types
            telem_struct_fmt = '=BHHBBIddddddddBB'  # update this to match your data types
            # H is for uint16
            # B is for uint8
            # I is for uint32
            # d is for double (float64)
            # Pack the telemetry data into a binary packet
            #print(drone_state)
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
            telem_packet_size = len(packet)
            # If broadcast_mode is True, send to all nodes
            if self.broadcast_mode:
                nodes = self.get_nodes()
                # Send to all other nodes
                for node in nodes:
                    if int(node["hw_id"]) != drone_state['hw_id']:
                        self.send_packet_to_node(packet, node["ip"], int(node["debug_port"]))
                        #print(f'Sent telemetry {telem_packet_size} Bytes to drone {int(node["hw_id"])} with IP: {node["ip"]} ')


            # Always send to GCS
            self.send_packet_to_node(packet, udp_ip, udp_port)

            #print(f"Sent telemetry data to GCS: {packet}")
            #print(f"Sent telemetry {telem_packet_size} Bytes to GCS")
            #print(f"Values: hw_id: {drone_state['hw_id']}, state: {drone_state['state']}, Mission: {drone_state['mission']}, Latitude: {drone_state['position_lat']}, Longitude: {drone_state['position_long']}, Altitude : {drone_state['position_alt']}, follow_mode: {drone_state['follow_mode']}, trigger_time: {drone_state['trigger_time']}")
            current_time = int(time.time())
            #print(f"Current system time: {current_time}")
            
            # Update the global variable to keep track of the packet size

            time.sleep(self.telem_send_interval)  # send telemetry data every TELEM_SEND_INTERVAL seconds



    
    def read_packets(self):
        while True:
            data, addr = self.sock.recvfrom(1024)
            self.process_packet(data)
            if self.drone_config.mission == 2 and self.drone_config.state != 0 and int(self.drone_config.swarm.get('follow')) != 0:
                self.drone_config.calculate_setpoints()
            time.sleep(self.income_packet_check_interval)

    def start_threads(self):
        self.telemetry_thread = threading.Thread(target=self.send_drone_state)
        self.command_thread = threading.Thread(target=self.read_packets)
        self.telemetry_thread.start()
        self.command_thread.start()
