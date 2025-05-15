"""
===========================================================================
 Project: MavSDK Drone Show (smart_swarm)
 Repository: https://github.com/alireza787b/mavsdk_drone_show

 Description:
   Central orchestrator for smart swarm behavior using MAVSDK. Supports leader and
   follower roles with dynamic reconfiguration, Kalman-filtered leader tracking,
   PD-control offboard velocity commands, and failsafe procedures.

 Features:
   - Reads drone config from CSV (IP, ports, GCS) and initial swarm formation from CSV.
   - Fetches dynamic swarm config via HTTP from GCS endpoint (role, offsets, body_coord).
   - Supports runtime role flips: follower→leader and leader→follower.
   - Leader election on unreachable leader, with GCS notification and commit.
   - Kalman filter for leader state estimation; PD + low-pass filter for follower control.
   - Telemetry origin and HTTP fallback for home position; sets NED reference.
   - Robust offboard control with failsafe on stale data.
   - Detailed logging (console + per-session file).
========================================================================="""

import os
import sys
import time
import asyncio
import csv
import subprocess
import logging
import socket
import psutil
import argparse
from datetime import datetime
from mavsdk import System
from mavsdk.offboard import VelocityBodyYawspeed, VelocityNedYaw, OffboardError
from tenacity import retry, stop_after_attempt, wait_fixed
import aiohttp
import numpy as np

from src.led_controller import LEDController
from src.params import Params
from smart_swarm_src.kalman_filter import LeaderKalmanFilter
from smart_swarm_src.pd_controller import PDController
from smart_swarm_src.low_pass_filter import LowPassFilter
from smart_swarm_src.utils import (
    transform_body_to_nea,
    is_data_fresh,
    fetch_home_position,
    lla_to_ned
)

# ----------------------------- #
#     Utility Functions        #
# ----------------------------- #

def configure_logging():
    logs_dir = os.path.join('..', 'logs', 'smart_swarm_logs')
    os.makedirs(logs_dir, exist_ok=True)
    fmt = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    datefmt = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    session = datetime.now().strftime('%Y%m%d_%H%M%S')
    fh = logging.FileHandler(os.path.join(logs_dir, f'smart_swarm_{session}.log'))
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    root.addHandler(fh)


def read_hw_id() -> str:
    files = [f for f in os.listdir('.') if f.endswith('.hwID')]
    if not files:
        logging.getLogger(__name__).error('HW ID file not found.')
        return None
    return os.path.splitext(files[0])[0]


def read_config_csv(path: str) -> dict:
    logger = logging.getLogger(__name__)
    cfg = {}
    try:
        with open(path, newline='') as f:
            for row in csv.DictReader(f):
                hw = str(int(row['hw_id']))
                cfg[hw] = row
        logger.info(f'Loaded {len(cfg)} drone configs from {path}')
    except Exception as e:
        logger.exception(f'Error reading config CSV: {e}')
        sys.exit(1)
    return cfg


def read_swarm_csv(path: str) -> dict:
    logger = logging.getLogger(__name__)
    sc = {}
    try:
        with open(path, newline='') as f:
            for row in csv.DictReader(f):
                hw = str(int(row['hw_id']))
                sc[hw] = {
                    'follow': row['follow'],
                    'offset_n': float(row['offset_n']),
                    'offset_e': float(row['offset_e']),
                    'offset_alt': float(row['offset_alt']),
                    'body_coord': row['body_coord']=='1'
                }
        logger.info(f'Loaded {len(sc)} swarm entries from {path}')
    except Exception as e:
        logger.exception(f'Error reading swarm CSV: {e}')
        sys.exit(1)
    return sc


def get_mavsdk_server_path() -> str:
    return os.path.join(os.path.expanduser('~'), 'mavsdk_drone_show', 'mavsdk_server')


def start_mavsdk_server(udp_port: int):
    logger = logging.getLogger(__name__)
    port = Params.DEFAULT_GRPC_PORT
    # terminate existing server
    for proc in psutil.process_iter(['pid']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    proc.terminate(); proc.wait(2)
        except Exception:
            pass
    path = get_mavsdk_server_path()
    if not os.path.isfile(path):
        logger.error(f'mavsdk_server not found at {path}'); sys.exit(1)
    if not os.access(path, os.X_OK): os.chmod(path, 0o755)
    proc = subprocess.Popen([path, '-p', str(port), f'udp://:{udp_port}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    logger.info(f'Started MAVSDK server on gRPC={port}, UDP={udp_port}')
    return proc

# ----------------------------- #
#      Swarm Controller        #
# ----------------------------- #
class SwarmController:
    def __init__(self, hw_id, drone_cfg, params, initial_swarm, ref_pos):
        self.hw_id = hw_id
        self.drone_cfg = drone_cfg
        self.params = params
        self.swarm_config = initial_swarm.copy()
        self.reference_pos = ref_pos
        self.leader_hw = None
        self.leader_ip = None
        self.kf = None
        self.unreachable = 0
        self.tasks = {}
        self.drone = None

    async def start(self, drone: System):
        self.drone = drone
        # initial static swarm loaded
        # start dynamic updates
        url = f"http://{self.drone_cfg['gcs_ip']}:{self.params.flask_telem_socket_port}/get-swarm-data"
        self.tasks['swarm'] = asyncio.create_task(self._periodic_swarm_update(url))
        # initial role
        if not self._is_leader():
            self._enter_follower()

    def _is_leader(self) -> bool:
        return self.swarm_config[self.hw_id]['follow']=='0'

    async def _periodic_swarm_update(self, url):
        logger = logging.getLogger(__name__)
        async with aiohttp.ClientSession() as sess:
            while True:
                try:
                    async with sess.get(url) as resp:
                        data = await resp.json()
                    self.swarm_config = {str(e['hw_id']): e for e in data}
                    entry = self.swarm_config[self.hw_id]
                    new_leader = entry['follow']; new_role = (new_leader=='0')
                    # role flip
                    if new_role != self._is_leader():
                        if new_role: self._cancel_follower()
                        else:       self._enter_follower()
                    # leader change only
                    if not new_role and new_leader!=self.leader_hw:
                        logger.info(f'Config: leader change → {new_leader}')
                        self._enter_follower()
                    # offsets/body_coord update can be handled here
                except Exception:
                    logger.exception('Swarm update error')
                await asyncio.sleep(self.params.CONFIG_UPDATE_INTERVAL)

    def _enter_follower(self):
        logger = logging.getLogger(__name__)
        # cancel old tasks
        for key in ('lead','own','ctrl'):
            t = self.tasks.get(key)
            if t and not t.done(): t.cancel()
        # setup leader
        entry = self.swarm_config[self.hw_id]
        self.leader_hw = str(entry['follow'])
        self.leader_ip = self.drone_cfg[self.leader_hw]['ip']
        self.kf = LeaderKalmanFilter()
        self.unreachable = 0
        # spawn tasks
        self.tasks['lead'] = asyncio.create_task(self._update_leader_state())
        self.tasks['own']  = asyncio.create_task(self._update_own_state())
        self.tasks['ctrl'] = asyncio.create_task(self._control_loop())
        logger.info(f'Follower: now following {self.leader_hw} @ {self.leader_ip}')

    def _cancel_follower(self):
        logger=logging.getLogger(__name__)
        for key in ('lead','own','ctrl'):
            t = self.tasks.get(key)
            if t and not t.done(): t.cancel()
        logger.info('Leader: follower tasks cancelled')

    async def _update_leader_state(self):
        logger=logging.getLogger(__name__)
        freq = 1/self.params.LEADER_UPDATE_FREQUENCY
        async with aiohttp.ClientSession() as sess:
            while True:
                try:
                    url = f"http://{self.leader_ip}:{self.params.drones_flask_port}/{self.params.get_drone_state_URI}"
                    async with sess.get(url, timeout=1) as resp:
                        data = await resp.json()
                    self.unreachable=0
                    if 'update_time' in data:
                        n,e,d = lla_to_ned(data['position_lat'], data['position_long'], data['position_alt'],
                                            self.reference_pos['latitude'], self.reference_pos['longitude'], self.reference_pos['altitude'])
                        meas = {'pos_n':n,'pos_e':e,'pos_d':d,
                                'vel_n':data['velocity_north'],'vel_e':data['velocity_east'],'vel_d':data['velocity_down']}
                        self.kf.update(meas, data['update_time'])
                    else:
                        logger.error('Leader JSON missing update_time')
                except Exception:
                    self.unreachable+=1
                    if self.unreachable>=self.params.MAX_LEADER_UNREACHABLE_ATTEMPTS:
                        await self._elect_new_leader()
                await asyncio.sleep(freq)

    async def _elect_new_leader(self):
        logger=logging.getLogger(__name__)
        new = str(int(self.leader_hw)+1)  # example logic
        ok = await self._notify_gcs(new)
        if ok:
            self.swarm_config[self.hw_id]['follow']=new
            self._enter_follower()
            logger.info(f'Elected new leader {new}')
        else:
            logger.warning('Leader election rejected')

    async def _notify_gcs(self, new):
        logger=logging.getLogger(__name__)
        url = f"http://{self.drone_cfg['gcs_ip']}:{self.params.flask_telem_socket_port}/request-new-leader"
        payload = {**self.swarm_config[self.hw_id], 'follow':new}
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload) as resp:
                    data=await resp.json()
            return data.get('status')=='success'
        except Exception:
            logger.exception('Notify GCS failed')
            return False

    async def _update_own_state(self):
        logger=logging.getLogger(__name__)
        async for pv in self.drone.telemetry.position_velocity_ned():
            pos,vel = pv.position, pv.velocity
            self.own_state={'pos_n':pos.north_m,'pos_e':pos.east_m,'pos_d':pos.down_m,
                            'vel_n':vel.north_m_s,'vel_e':vel.east_m_s,'vel_d':vel.down_m_s}

    async def _control_loop(self):
        logger=logging.getLogger(__name__)
        loop = 1/self.params.CONTROL_LOOP_FREQUENCY
        pd = PDController(self.params.PD_KP, self.params.PD_KD, self.params.MAX_VELOCITY)
        lp = LowPassFilter(self.params.LOW_PASS_FILTER_ALPHA)
        stale = None
        while True:
            now = time.time()
            if self.kf and is_data_fresh(self.kf.last_time, self.params.DATA_FRESHNESS_THRESHOLD):
                stale=None
                st = self.kf.predict(now)
                yaw = self.kf.yaw if hasattr(self.kf,'yaw') else 0.0
                off = self.swarm_config[self.hw_id]
                if off['body_coord']:
                    off_n,off_e = transform_body_to_nea(off['offset_n'], off['offset_e'], yaw)
                else:
                    off_n,off_e = off['offset_n'], off['offset_e']
                des_n = st[0]+off_n; des_e = st[1]+off_e; des_d = -1*(st[2]+off['offset_alt'])
                cur = self.own_state
                err = np.array([des_n-cur['pos_n'], des_e-cur['pos_e'], des_d-cur['pos_d']])
                vel_cmd = pd.compute(err, loop)
                filt = lp.filter(vel_cmd)
                await self.drone.offboard.set_velocity_ned(VelocityNedYaw(filt[0], filt[1], filt[2], yaw))
            else:
                if stale is None: stale=now
                elif now-stale>=self.params.MAX_STALE_DURATION:
                    await self._exec_failsafe()
            await asyncio.sleep(loop)

    async def _exec_failsafe(self):
        logger=logging.getLogger(__name__)
        LEDController.get_instance().set_color(255,0,0)
        try:
            await self.drone.offboard.set_velocity_ned(VelocityNedYaw(0,0,0,0))
            logger.info('Failsafe: holding')
        except Exception:
            logger.exception('Failsafe error')

# ----------------------------- #
#       Drone Init & Main      #
# ----------------------------- #

@retry(stop=stop_after_attempt(Params.PREFLIGHT_MAX_RETRIES), wait=wait_fixed(2))
async def initialize_drone():
    logger=logging.getLogger(__name__)
    led=LEDController.get_instance()
    led.set_color(0,0,255)
    drone=System(port=Params.DEFAULT_GRPC_PORT)
    await drone.connect(system_address=f'udp://:{Params.mavsdk_port}')
    # wait for connection & health checks omitted for brevity
    await drone.offboard.set_velocity_body(VelocityBodyYawspeed(0,0,0,0))
    await drone.offboard.start()
    led.set_color(0,255,0)
    return drone

async def run_smart_swarm():
    configure_logging()
    hw=read_hw_id();
    if not hw: sys.exit(1)
    dc=read_config_csv('config.csv')
    sc=read_swarm_csv('swarm.csv')
    cfg=dc.get(hw)
    if not cfg: logging.getLogger(__name__).error('Missing drone config'); sys.exit(1)

    # start MAVSDK server
    srv=start_mavsdk_server(Params.mavsdk_port)
    await asyncio.sleep(2)

    # init drone
    drone=await initialize_drone()

    # fetch home origin
    try:
        origin=await drone.telemetry.get_gps_global_origin()
        own_pos={'latitude':origin.latitude_deg,'longitude':origin.longitude_deg,'altitude':origin.altitude_m}
    except:
        own_pos=None
    if not own_pos:
        fb=fetch_home_position(cfg['ip'], Params.drones_flask_port, Params.get_drone_gps_origin_URI)
        own_pos=fb or sys.exit(1)
    ref=own_pos

    # launch controller
    controller=SwarmController(hw, cfg, Params, sc, ref)
    await controller.start(drone)

    try:
        while True: await asyncio.sleep(1)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info('Shutting down')


def main():
    arg=argparse.ArgumentParser(); arg.parse_args()
    try: asyncio.run(run_smart_swarm())
    except Exception:
        logging.exception('Unhandled exception'); sys.exit(1)

if __name__=='__main__': main()
