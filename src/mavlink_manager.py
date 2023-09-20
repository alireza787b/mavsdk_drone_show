import subprocess
import logging

class MavlinkManager:
    def __init__(self, params, drone_config):
        self.params = params
        self.drone_config = drone_config
        self.mavlink_router_process = None
        logging.info("Initialized MavlinkManager")

    def initialize(self):
        try:
            if self.params.sim_mode:
                logging.info("Sim mode is enabled. Connecting to SITL...")
                if self.params.default_sitl:
                    mavlink_source = f"0.0.0.0:{self.params.sitl_port}"
                else:
                    mavlink_source = f"0.0.0.0:{self.drone_config.config['mavlink_port']}"
            else:
                if self.params.serial_mavlink:
                    logging.info("Real mode is enabled. Connecting to Pixhawk via serial...")
                    mavlink_source = f"/dev/{self.params.serial_mavlink}:{self.params.serial_baudrate}"
                else:
                    logging.info("Real mode is enabled. Connecting to Pixhawk via UDP...")
                    mavlink_source = f"127.0.0.1:{self.params.sitl_port}"

            logging.info(f"Using MAVLink source: {mavlink_source}")

            endpoints = [f"-e {device}" for device in self.params.extra_devices]

            if self.params.sim_mode:
                endpoints.append(f"-e {self.drone_config.config['gcs_ip']}:{self.params.mavsdk_port}")
            else:
                if self.params.serial_mavlink:
                    endpoints.append(f"-e 127.0.0.1:{self.params.mavsdk_port}")

                if self.params.shared_gcs_port:
                    endpoints.append(f"-e {self.drone_config.config['gcs_ip']}:{self.params.gcs_mavlink_port}")
                else:
                    endpoints.append(f"-e {self.drone_config.config['gcs_ip']}:{int(self.drone_config.config['mavlink_port'])}")

            mavlink_router_cmd = "mavlink-routerd " + ' '.join(endpoints) + ' ' + mavlink_source
            logging.info(f"Starting MAVLink router with command: {mavlink_router_cmd}")

            self.mavlink_router_process = subprocess.Popen(mavlink_router_cmd, shell=True)
            logging.info("MAVLink router process started")
        except Exception as e:
            logging.error(f"An error occurred in initialize(): {e}")

    def terminate(self):
        try:
            if self.mavlink_router_process:
                self.mavlink_router_process.terminate()
                logging.info("MAVLink router process terminated")
            else:
                logging.warning("MAVLink router process is not running")
        except Exception as e:
            logging.error(f"An error occurred in terminate(): {e}")
