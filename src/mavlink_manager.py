import subprocess

class MavlinkManager:
    def __init__(self, params, drone_config):
        self.params = params
        self.drone_config = drone_config
        self.mavlink_router_process = None

    def initialize(self):
        if self.params.sim_mode:
            mavlink_source = f"0.0.0.0:{self.params.sitl_port}"
        else:
            mavlink_source = f"/dev/{self.params.serial_mavlink}:{self.params.serial_baudrate}"

        endpoints = [f"-e {device}" for device in self.params.extra_devices]

        if self.params.sim_mode:
            endpoints.append(f"-e {self.drone_config.config['gcs_ip']}:{self.params.mavsdk_port}")
        else:
            endpoints.append(f"-e {self.drone_config.config['gcs_ip']}:{self.params.gcs_mavlink_port}")

        mavlink_router_cmd = "mavlink-routerd " + ' '.join(endpoints) + ' ' + mavlink_source
        self.mavlink_router_process = subprocess.Popen(mavlink_router_cmd, shell=True)

    def terminate(self):
        if self.mavlink_router_process:
            self.mavlink_router_process.terminate()
