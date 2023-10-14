
import socket
import threading
import os
import time
import csv
import struct
import logging
import select
import subprocess
from concurrent.futures import ThreadPoolExecutor
from src.drone_config import DroneConfig 

class DroneCommunicator:
    def __init__(self, drone_config, params, drones):
        self.drone_config = drone_config
        self.params = params
        self.drones = drones
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', int(self.drone_config.config['debug_port'])))
        self.sock.setblocking(0)  # This sets the socket to non-blocking mode
        self.stop_flag = threading.Event()
        self.nodes = None
        self.executor = ThreadPoolExecutor(max_workers=10)

    def send_telem(self, packet, ip, port):
        self.sock.sendto(packet, (ip, port))
        
    def send_packet_to_node(self, packet, ip, port):
        self.sock.sendto(packet, (ip, port))

    def get_nodes(self):
        if self.nodes is not None:  # modify this line
            return self.nodes
        with open("config.csv", "r") as file:
            self.nodes = list(csv.DictReader(file))  # modify this line
        return self.nodes

    def set_drone_config(self, hw_id, pos_id, state, mission, trigger_time, position, velocity, yaw, battery, last_update_timestamp):
        drone = self.drones.get(hw_id)
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





    def process_packet(self, data):
        header, terminator = struct.unpack('BB', data[0:1] + data[-1:])
        
        if header == 55 and terminator == 66 and len(data) == self.params.command_packet_size:
            header, hw_id, pos_id, mission, state, trigger_time, terminator = struct.unpack(self.params.command_struct_fmt, data)
            logging.info(f"Received command from GCS: hw_id: {hw_id}, pos_id: {pos_id}, mission: {mission}, state: {state}, trigger_time: {trigger_time}")

            self.drone_config.hw_id = hw_id
            self.drone_config.pos_id = pos_id
            self.drone_config.state = state
            self.drone_config.trigger_time = trigger_time

            # Handle TAKE_OFF with altitude
            if 10 <= mission < 60:
                altitude = mission - 10
                if altitude > 50:
                    altitude = 50
                print(f"Takeoff command received. Altitude: {altitude}m")
                
                # Update mission code to default TAKE_OFF code after extracting altitude
                self.drone_config.mission = mission  # Change this to your default TAKE_OFF code
                
            elif mission == 1:
                print("Drone Show command received.")
                self.drone_config.mission = mission
                
            elif mission == 2:
                print("Smart Swarm command received.")
                self.drone_config.mission = mission
                
            elif mission == self.params.Mission.LAND.value:
                print("Land command received.")
                self.drone_config.mission = mission
                
            elif mission == self.params.Mission.HOLD.value:
                print("Hold command received.")
                self.drone_config.mission = mission
                
            elif mission == self.params.Mission.TEST.value:
                print("Test command received.")
                self.drone_config.mission = mission
            else:
                print(f"Unknown mission command received: {mission}")
                self.drone_config.mission = self.params.Mission.NONE.value




            # Add additional logic here to handle the received command
        elif header == 77 and terminator == 88 and len(data) == self.params.telem_packet_size:
            # Decode the data
            header, hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, yaw, battery_voltage, follow_mode, update_time ,  terminator = struct.unpack(self.params.telem_struct_fmt, data)
            logging.debug(f"Received telemetry from Drone {hw_id}")

            if hw_id not in self.drones:
                # Create a new instance for the drone
                logging.info(f"Receiving Telemetry from NEW Drone ID= {hw_id}")
                self.drones[hw_id] = DroneConfig(self.drones, hw_id)

            position = {'lat': position_lat, 'long': position_long, 'alt': position_alt}
            velocity = {'north': velocity_north, 'east': velocity_east, 'down': velocity_down}
            self.set_drone_config(hw_id, pos_id, state, mission, trigger_time, position, velocity, yaw, battery_voltage, update_time)
            # Add processing of the received telemetry data here
        else:
            logging.error(f"Received packet of incorrect size or header. Got {len(data)} bytes.")
    
    # Fetches the current state of the drone
    def get_drone_state(self):
        drone_state = {
        "hw_id": int(self.drone_config.hw_id),
        "pos_id": int(self.drone_config.config['pos_id']),
        "state": int(self.drone_config.state),
        "mission": int(self.drone_config.mission),
        "trigger_time": int(self.drone_config.trigger_time),
        "position_lat": self.drone_config.position['lat'],
        "position_long": self.drone_config.position['long'],
        "position_alt": self.drone_config.position['alt'],
        "velocity_north": self.drone_config.velocity['north'],
        "velocity_east": self.drone_config.velocity['east'],
        "velocity_down": self.drone_config.velocity['down'],
        "yaw": self.drone_config.yaw,
        "battery_voltage": self.drone_config.battery,
        "follow_mode": int(self.drone_config.swarm['follow']),
        "update_time": int(self.drone_config.last_update_timestamp)
        }

        return drone_state


    def send_drone_state(self):
        udp_ip = self.drone_config.config['gcs_ip']  # IP address of the ground station
        udp_port = int(self.drone_config.config['debug_port'])  # UDP port to send telemetry data to

        while not self.stop_flag.is_set():
            drone_state = self.get_drone_state()

            # Create a struct format string based on the data types
            telem_struct_fmt = '=BHHBBIddddddddBIB'  # update this to match your data types
            packet = struct.pack(telem_struct_fmt,
                                    77,
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
                                    drone_state['update_time'],
                                    88)
            telem_packet_size = len(packet)

            # If broadcast_mode is True, send to all nodes
            if self.params.broadcast_mode:
                nodes = self.get_nodes()
                for node in nodes:
                    if int(node["hw_id"]) != drone_state['hw_id']:
                        future = self.executor.submit(self.send_telem, packet,  node["ip"], int(node["debug_port"]))
            # Always send to GCS
            self.executor.submit(self.send_telem, packet, udp_ip, udp_port)

            time.sleep(self.params.TELEM_SEND_INTERVAL)
        
    def read_packets(self):
        while not self.stop_flag.is_set():
            ready = select.select([self.sock], [], [], self.params.income_packet_check_interval)
            if ready[0]:
                data, addr = self.sock.recvfrom(1024)
                self.process_packet(data)
            if self.drone_config.mission == 2 and self.drone_config.state != 0 and int(self.drone_config.swarm.get('follow')) != 0:
                    self.drone_config.calculate_setpoints()

    def start_communication(self):
        self.telemetry_thread = threading.Thread(target=self.send_drone_state)
        self.command_thread = threading.Thread(target=self.read_packets)
        self.telemetry_thread.start()
        self.command_thread.start()

    def stop_communication(self):
        self.stop_flag.set()
        self.telemetry_thread.join()
        self.command_thread.join()
        self.executor.shutdown()

