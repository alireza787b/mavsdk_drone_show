import socket
import struct
import time
import threading

class CommunicationHandling:
    def __init__(self, drone_config, income_packet_check_interval, command_packet_size, telem_packet_size, command_struct_fmt, telem_struct_fmt):
        """
        The constructor starts a new thread which reads packets over a specified UDP port, 
        processes the packets based on their type, and updates the drone_config object accordingly.
        """
        self.drone_config = drone_config
        self.income_packet_check_interval = income_packet_check_interval
        self.command_packet_size = command_packet_size
        self.telem_packet_size = telem_packet_size
        self.command_struct_fmt = command_struct_fmt
        self.telem_struct_fmt = telem_struct_fmt

        udp_port = int(self.drone_config.config['debug_port'])
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', udp_port))
        
        # Start a thread to handle the packets
        self.thread = threading.Thread(target=self.read_packets)
        self.thread.start()

    def read_packets(self):
        """
        Reads and decodes new packets from the ground station over the debug vector.
        The packets can be either commands or telemetry data, depending on the header and terminator.
        """
        while True:
            data, addr = self.sock.recvfrom(1024)
            header, terminator = struct.unpack('BB', data[0:1] + data[-1:])

            # Check if it's a command packet
            if header == 55 and terminator == 66 and len(data) == self.command_packet_size:
                self.handle_command_packet(data)

            # Check if it's a telemetry packet
            elif header == 77 and terminator == 88 and len(data) == self.telem_packet_size:
                self.handle_telemetry_packet(data)
            else:
                print(f"Received packet of incorrect size or header.got {len(data)}.")

            time.sleep(self.income_packet_check_interval)

    def handle_command_packet(self, data):
        """
        Handles command packets, updating the drone_config object accordingly.
        """
        header, hw_id, pos_id, mission, state, trigger_time, terminator = struct.unpack(self.command_struct_fmt, data)
        print("Received command from GCS")

        self.drone_config.hw_id = hw_id
        self.drone_config.pos_id = pos_id
        self.drone_config.mission = mission
        self.drone_config.state = state
        self.drone_config.trigger_time = trigger_time

    def handle_telemetry_packet(self, data):
        """
        Handles telemetry packets, updating the drone_config object accordingly.
        """
        header, hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, yaw , battery_voltage, follow_mode, terminator = struct.unpack(self.telem_struct_fmt, data)
        print(f"Received telemetry from Drone {hw_id}")

        self.drone_config.state = state
        self.drone_config.mission = mission
        self.drone_config.trigger_time = trigger_time
        self.drone_config.mission = mission
        self.drone_config.position = {'lat': position_lat, 'long': position_long, 'alt': position_alt}
        self.drone_config.velocity = {'vel_n': velocity_north, 'vel_e': velocity_east, 'vel_d': velocity_down}
        self.drone_config.yaw = yaw
        self.drone_config.battery = battery_voltage
        self.drone_config.last_update_timestamp = time.time()

        if self.drone_config.mission == 2 and self.drone_config.state != 0 and int(self.drone_config.swarm.get('follow')) != 0:
            self.drone_config.calculate_setpoints()

    def __del__(self):
        """
        Destructor to ensure the thread is stopped when the object is deleted
        """
        if self.thread.is_alive():
            self.thread.join()
