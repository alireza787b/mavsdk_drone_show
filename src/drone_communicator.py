#src/drone_communicator.py
import socket
import threading
import csv
import struct
import logging
import select
import time
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from functions.data_utils import safe_float, safe_get, safe_int
from src.enums import Mission
from src.drone_config import DroneConfig
from src.flask_handler import FlaskHandler
from src.params import Params
from src.telemetry_subscription_manager import TelemetrySubscriptionManager

class DroneCommunicator:
    """
    Handles communication with drones, including telemetry and command processing.
    """

    def __init__(self, drone_config: DroneConfig, params: Params, drones: Dict[str, DroneConfig]):
        """
        Initialize the DroneCommunicator with configuration and drone data.

        Args:
            drone_config (DroneConfig): Configuration for the current drone.
            params (Params): Global parameters.
            drones (Dict[str, DroneConfig]): Dictionary of all drones.
        """
        self.drone_config = drone_config
        self.params = params
        self.drones = drones
        self.enable_udp_telemetry = params.enable_udp_telemetry
        self.sock = self._initialize_socket() if self.enable_udp_telemetry else None
        self.stop_flag = threading.Event()
        self.nodes: List[Dict[str, Any]] = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.drone_state: Dict[str, Any] = None

        # Initialize TelemetrySubscriptionManager
        self.subscription_manager = TelemetrySubscriptionManager(drones)

        # Subscribe to all drones if the parameter is enabled
        if params.enable_default_subscriptions:
            self.subscription_manager.subscribe_to_all()

        # Initialize flask_handler as None; it will be injected later
        self.flask_handler = None

    def set_flask_handler(self, flask_handler: FlaskHandler):
        """Setter for injecting FlaskHandler dependency after initialization."""
        self.flask_handler = flask_handler

    def _initialize_socket(self) -> socket.socket:
        """Initialize and return a UDP socket for telemetry."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', int(self.drone_config.config['debug_port'])))
        sock.setblocking(False)
        return sock

    def _initialize_socket(self) -> socket.socket:
        """Initialize and return a UDP socket for telemetry."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', int(self.drone_config.config['debug_port'])))
        sock.setblocking(False)
        return sock

    def send_telem(self, packet: bytes, ip: str, port: int) -> None:
        """
        Send telemetry packet to the specified IP and port.

        Args:
            packet (bytes): Telemetry data packet.
            ip (str): Destination IP address.
            port (int): Destination port number.
        """
        if self.enable_udp_telemetry and self.sock:
            try:
                self.sock.sendto(packet, (ip, port))
            except OSError as e:
                logging.error(f"Failed to send telemetry: {e}")

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Retrieve node information from config.csv file."""
        if self.nodes is None:
            try:
                with open("config.csv", "r") as file:
                    self.nodes = list(csv.DictReader(file))
            except FileNotFoundError:
                logging.error("config.csv file not found")
                self.nodes = []
            except csv.Error as e:
                logging.error(f"Error reading config.csv: {e}")
                self.nodes = []
        return self.nodes

    def update_drone_config(self, hw_id: str, **kwargs) -> None:
        """
        Update the configuration of a specific drone.

        Args:
            hw_id (str): Hardware ID of the drone to update.
            **kwargs: Arbitrary keyword arguments for drone configuration.
        """
        drone = self.drones.get(hw_id)
        if drone:
            for key, value in kwargs.items():
                setattr(drone, key, value)
            self.drones[hw_id] = drone
        else:
            logging.warning(f"Attempted to update non-existent drone: {hw_id}")

    def process_command(self, command_data: Dict[str, Any]) -> None:
        """
        Process incoming command data and update drone configuration.

        Args:
            command_data (Dict[str, Any]): A dictionary containing command information.

        Required fields:
            - missionType (int): The mission code.
            - triggerTime (str): The time to trigger the mission.

        Optional fields:
            - hw_id (str): Hardware ID.
            - pos_id (str): Position ID.
            - state (str): Drone state.
        """
        logging.info(f"Received command data: {command_data}")

        try:
            mission = int(command_data["missionType"])
            trigger_time = command_data["triggerTime"]
        except KeyError as e:
            logging.error(f"Missing required field in command data: {e}")
            return

        hw_id = command_data.get("hw_id", self.drone_config.hw_id)
        pos_id = command_data.get("pos_id", self.drone_config.pos_id)
        state = command_data.get("state", self.drone_config.state)

        self._update_drone_config(hw_id, pos_id, state, trigger_time)

        try:
            self._process_mission_command(mission, command_data)
        except ValueError as e:
            logging.warning(f"Invalid mission command: {e}")

        self._log_updated_configuration()
        self.drones[hw_id] = self.drone_config

    def _update_drone_config(self, hw_id: str, pos_id: str, state: int, trigger_time: int) -> None:
        """Update drone configuration with new values."""
        self.drone_config.hw_id = hw_id
        self.drone_config.pos_id = pos_id
        self.drone_config.state = state
        self.drone_config.trigger_time = trigger_time

    def _process_mission_command(self, mission: int, command_data: Dict[str, Any]) -> None:
        """Process the mission command based on its type."""
        # Log the incoming mission command and data
        logging.info(f"Processing mission command: {mission}, with data: {command_data}")

        if mission == Mission.TAKE_OFF.value:
            self._handle_takeoff_command(command_data)
        elif mission in Mission._value2member_map_:
            self._handle_standard_mission(mission)
        else:
            # Log the error before raising an exception
            logging.error(f"Unknown mission command: {mission}")
            raise ValueError(f"Unknown mission command: {mission}")
    

    def _handle_takeoff_command(self, command_data: Dict[str, Any]) -> None:
        """Handle the takeoff command, setting altitude and mission."""
        default_altitude = self.params.default_takeoff_alt
        assigned_altitude = command_data.get("takeoff_altitude", default_altitude)
        self.drone_config.takeoff_altitude = min(float(assigned_altitude), self.params.max_takeoff_alt)
        logging.info(f"Takeoff command received. Assigned altitude: {self.drone_config.takeoff_altitude}m")
        self.drone_config.mission = Mission.TAKE_OFF.value
        self.drone_config.state = 1 #double check

    def _handle_standard_mission(self, mission: int) -> None:
        """Handle standard (non-takeoff) mission commands."""
        mission_enum = Mission(mission)
        logging.info(f"{mission_enum.name.replace('_', ' ').title()} command received.")
        self.drone_config.mission = mission
        self.drone_config.state = 1 #double check

    def _log_updated_configuration(self) -> None:
        """Log the updated drone configuration."""
        logging.info(
            f"Updated drone configuration: "
            f"hw_id={self.drone_config.hw_id}, "
            f"pos_id={self.drone_config.pos_id}, "
            f"state={self.drone_config.state}, "
            f"mission={self.drone_config.mission}, "
            f"trigger_time={self.drone_config.trigger_time}"
        )

    def process_packet(self, data: bytes) -> None:
        """
        Process incoming telemetry packet.

        Args:
            data (bytes): Raw telemetry packet data.
        """
        try:
            header, terminator = struct.unpack('BB', data[0:1] + data[-1:])
            if header == 77 and terminator == 88 and len(data) == Params.telem_packet_size:
                telemetry_data = struct.unpack(Params.telem_struct_fmt, data)
                hw_id = telemetry_data[1]
                if hw_id not in self.drones:
                    logging.info(f"Receiving Telemetry from NEW Drone ID= {hw_id}")
                    self.drones[hw_id] = DroneConfig(self.drones, hw_id)
                self._update_drone_config_from_telemetry(hw_id, telemetry_data)
            else:
                logging.error(f"Received packet of incorrect size or header. Got {len(data)} bytes.")
        except struct.error as e:
            logging.error(f"Failed to unpack telemetry data: {e}")

    def _update_drone_config_from_telemetry(self, hw_id: str, telemetry_data: tuple) -> None:
        """
        Update drone configuration based on received telemetry data.

        Args:
            hw_id (str): Hardware ID of the drone.
            telemetry_data (tuple): Unpacked telemetry data.
        """
        position = {'lat': telemetry_data[6], 'long': telemetry_data[7], 'alt': telemetry_data[8]}
        velocity = {'north': telemetry_data[9], 'east': telemetry_data[10], 'down': telemetry_data[11]}
        self.drones[hw_id].update(
            pos_id=telemetry_data[2],
            state=telemetry_data[3],
            mission=telemetry_data[4],
            trigger_time=telemetry_data[5],
            position=position,
            velocity=velocity,
            yaw=telemetry_data[12],
            battery_voltage=telemetry_data[13],
            update_time=telemetry_data[15]
        )
        # TODO: Remember to also add hdop and flight mode using HTTP FLASK

    def get_drone_state(self) -> Dict[str, Any]:
        """
        Retrieve and return the current state of the drone.

        This includes various telemetry data such as position, velocity, yaw, 
        battery voltage, and MAVLink-specific fields like flight mode and system status.

        Returns:
            dict: A dictionary containing the current state of the drone.
        """
        

        self.drone_state = {
            "hw_id": safe_int(self.drone_config.hw_id),  # Hardware ID of the drone
            "pos_id": safe_int(safe_get(self.drone_config.config, 'pos_id')),  # Position ID
            "state": safe_int(self.drone_config.state),  # Current state of the drone
            "mission": safe_int(self.drone_config.mission),  # Current mission state
            "trigger_time": safe_int(self.drone_config.trigger_time),  # Time of the last trigger event
            "position_lat": safe_float(safe_get(self.drone_config.position, 'lat')),  # Latitude of the current position
            "position_long": safe_float(safe_get(self.drone_config.position, 'long')),  # Longitude of the current position
            "position_alt": safe_float(safe_get(self.drone_config.position, 'alt')),  # Altitude of the current position
            "velocity_north": safe_float(safe_get(self.drone_config.velocity, 'north')),  # Velocity towards north
            "velocity_east": safe_float(safe_get(self.drone_config.velocity, 'east')),  # Velocity towards east
            "velocity_down": safe_float(safe_get(self.drone_config.velocity, 'down')),  # Velocity downwards
            "yaw": safe_float(self.drone_config.yaw),  # Yaw angle of the drone
            "battery_voltage": safe_float(self.drone_config.battery),  # Current battery voltage
            "follow_mode": safe_int(safe_get(self.drone_config.swarm, 'follow')),  # Follow mode in swarm operation
            "update_time": safe_int(self.drone_config.last_update_timestamp),  # Timestamp of the last telemetry update
            "flight_mode_raw": safe_int(self.drone_config.mav_mode),  # MAVLink flight mode (raw value from MAV_MODE)
            "system_status": safe_int(self.drone_config.system_status),  # MAVLink system status (e.g., STANDBY, ACTIVE)
            "hdop": safe_float(self.drone_config.hdop),  # Horizontal dilution of precision
            "vdop": safe_float(self.drone_config.vdop)  # Vertical dilution of precision
        }

        return self.drone_state


    def send_drone_state(self) -> None:
        """Continuously send drone state as telemetry."""
        udp_ip = self.drone_config.config['gcs_ip']
        udp_port = int(self.drone_config.config['debug_port'])

        while not self.stop_flag.is_set():
            drone_state = self.get_drone_state()
            packet = self._create_telemetry_packet(drone_state)

            if Params.broadcast_mode:
                self._broadcast_telemetry(packet, drone_state['hw_id'])
            self.executor.submit(self.send_telem, packet, udp_ip, udp_port)
            time.sleep(Params.TELEM_SEND_INTERVAL)

    def _create_telemetry_packet(self, drone_state: Dict[str, Any]) -> bytes:
        """Create a telemetry packet from the drone state."""
        return struct.pack(
            Params.telem_struct_fmt,
            77,  # Header
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
            88  # Terminator
        )

    def _broadcast_telemetry(self, packet: bytes, sender_hw_id: int) -> None:
        """Broadcast telemetry to all nodes except the sender."""
        nodes = self.get_nodes()
        for node in nodes:
            if int(node["hw_id"]) != sender_hw_id:
                self.executor.submit(self.send_telem, packet, node["ip"], int(node["debug_port"]))

    def read_packets(self) -> None:
        """Continuously read incoming packets and process them."""
        while not self.stop_flag.is_set():
            if self.sock:
                ready = select.select([self.sock], [], [], Params.income_packet_check_interval)
                if ready[0]:
                    try:
                        data, addr = self.sock.recvfrom(1024)
                        self.process_packet(data)
                    except OSError as e:
                        logging.error(f"Error receiving packet: {e}")
            
            # Handle swarm mission if active
            if self.drone_config.mission == Mission.SMART_SWARM.value and self.drone_config.state != 0 and int(self.drone_config.swarm.get('follow', 0)) != 0:
                self.drone_config.calculate_setpoints()

    def start_communication(self) -> None:
        """Start communication threads for telemetry and command processing."""
        if Params.enable_udp_telemetry:
            self.telemetry_thread = threading.Thread(target=self.send_drone_state)
            self.command_thread = threading.Thread(target=self.read_packets)
            self.telemetry_thread.start()
            self.command_thread.start()

        # Start the Flask server for HTTP commands
        self.flask_handler_thread = threading.Thread(target=self.flask_handler.run)
        self.flask_handler_thread.start()

    def stop_communication(self) -> None:
        """Stop all communication threads and clean up resources."""
        self.stop_flag.set()
        if Params.enable_udp_telemetry:
            self.telemetry_thread.join()
            self.command_thread.join()
        self.flask_handler_thread.join()
        self.executor.shutdown()

        if self.sock:
            self.sock.close()