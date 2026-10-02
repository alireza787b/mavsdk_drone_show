#!/usr/bin/env python3
"""Offline controller/plant sensitivity comparison; never sends flight commands.

This is a first-order synthetic plant, NOT an identified F550 model or a
counterfactual prediction of the recorded flight. Live PX4 SITL remains a
separate acceptance step. Both profiles run the same production controller.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_swarm_src.follower_controller import FollowerMotionController
from smart_swarm_src.formation_guard import FormationGuard
from smart_swarm_src.velocity_command_shaper import NedVelocityCommandShaper
from smart_swarm_src.utils import transform_body_to_nea
from src.settings.env_files import read_env_assignments
from src.settings.env_registry import load_env_registry

DT = 1 / 15
KEYS = {
    'max_horizontal_speed_m_s': 'MDS_SMART_SWARM_MAX_HORIZONTAL_SPEED_M_S',
    'max_vertical_speed_m_s': 'MDS_SMART_SWARM_MAX_VERTICAL_SPEED_M_S',
    'max_acceleration_m_s2': 'MDS_SMART_SWARM_MAX_ACCELERATION_M_S2',
    'max_jerk_m_s3': 'MDS_SMART_SWARM_MAX_JERK_M_S3',
}


def profiles(path):
    registry = load_env_registry()
    stock = {key: float(registry.require(env).default) for key, env in KEYS.items()}
    overrides = read_env_assignments(path)
    candidate = {key: float(overrides.get(env, stock[key])) for key, env in KEYS.items()}
    # Validate before running anything, including non-finite profile input.
    for profile in (stock, candidate):
        NedVelocityCommandShaper(**profile, max_dt_s=.1)
    return {'stock': stock, 'responsive': candidate}


def braking(profile, speed):
    shaper = NedVelocityCommandShaper(**profile, max_dt_s=.1, seed_velocity_ned=(speed, 0, 0))
    trace = []
    for i in range(400):
        velocity = shaper.shape((0, 0, 0), DT)
        trace.append(((i+1)*DT, float(velocity[0])))
        if np.linalg.norm(velocity) < .05:
            return {'seconds_to_005_m_s': trace[-1][0],
                    'commanded_travel_m': sum(v*DT for _, v in trace)}, trace
    raise RuntimeError('Braking did not settle')


def synthetic_tracking(profile, speed, *, body=False, delay=.08, plant_tau=.6,
                       position_gain=.5, velocity_gain=.35, position_filter_s=.35):
    controller = FollowerMotionController(
        position_gain=position_gain, velocity_gain=velocity_gain, leader_velocity_feedforward=1,
        position_filter_time_constant_s=position_filter_s,
        max_yaw_rate_deg_s=30, max_dt_s=.1, seed_yaw_deg=0,
        formation_guard=FormationGuard(capture_horizontal_m=2, capture_vertical_m=1.5,
                                      capture_stable_sec=1, tracking_horizontal_m=6, tracking_vertical_m=3),
        velocity_shaper=NedVelocityCommandShaper(**profile, max_dt_s=.1),
    )
    leader_shaper = NedVelocityCommandShaper(max_horizontal_speed_m_s=5,
        max_vertical_speed_m_s=1.25, max_acceleration_m_s2=3, max_jerk_m_s3=8, max_dt_s=.1)
    leader_pos = np.array([0., 0., -10.])
    follower_pos = np.array([6., 0., -10.])
    follower_vel = np.zeros(3)
    history = []
    trace = []
    random = np.random.default_rng(42)
    for i in range(750):
        t = i*DT
        request = (speed if 3 <= t < 15 else -speed if 23 <= t < 35 else 0)
        vertical = -1.0 if 7 <= t < 10 else 1.0 if 27 <= t < 30 else 0
        leader_vel = leader_shaper.shape((request, 0, vertical), DT)
        leader_pos += leader_vel*DT
        yaw = min(60, max(0, (t-3)*5)) if body else 0
        yaw_rate = math.radians(5) if body and 3 < t < 15 else 0
        history.append((leader_pos.copy(), leader_vel.copy(), yaw, yaw_rate))
        sample = history[max(0, i-round(delay/DT))]
        sample_pos, sample_vel, sample_yaw, omega = sample
        north, east = transform_body_to_nea(6, 0, sample_yaw)
        target = sample_pos + sample_vel*delay + np.array([north, east, 0])
        feedforward = sample_vel + np.array([-east*omega, north*omega, 0])
        decision = controller.compute(desired_position_ned=target,
            own_position_ned=follower_pos+random.normal(0, .03, 3),
            own_velocity_ned=follower_vel, leader_velocity_ned=feedforward,
            target_yaw_deg=sample_yaw, confidence=1, dt_s=DT, now_s=100+t)
        follower_vel += (1-math.exp(-DT/plant_tau))*(decision.velocity_ned-follower_vel)
        follower_pos += follower_vel*DT
        truth_offset = np.array([*transform_body_to_nea(6, 0, yaw), 0])
        error = follower_pos-(leader_pos+truth_offset)
        trace.append([t, np.linalg.norm(leader_vel[:2]), np.linalg.norm(decision.velocity_ned[:2]),
                      np.linalg.norm(follower_vel[:2]), np.linalg.norm(error[:2]), abs(error[2]),
                      np.linalg.norm((follower_pos-leader_pos)[:2])])
    values = np.array(trace)
    metrics = {'rms_horizontal_error_m': float(np.sqrt(np.mean(values[:,4]**2))),
               'max_horizontal_error_m': float(values[:,4].max()),
               'max_vertical_error_m': float(values[:,5].max()),
               'min_estimated_separation_m': float(values[:,6].min()),
               'final_hover_speed_rms_m_s': float(np.sqrt(np.mean(values[-90:,3]**2)))}
    return metrics, values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-file', type=Path, default=ROOT/'deployment/examples/smart-swarm-responsive.env')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    profiles_by_name = profiles(args.profile_file)
    report = {'model': 'Synthetic first-order velocity plant, tau=0.6s; not identified F550 dynamics',
              'profiles': profiles_by_name, 'braking': {}, 'tracking': {}}
    traces = {}
    for name, profile in profiles_by_name.items():
        report['braking'][name] = {}
        for speed in (1, 3, 5):
            result, trace = braking(profile, speed)
            report['braking'][name][str(speed)] = result
            if speed == 5:
                traces[name] = trace
        report['tracking'][name] = {}
        for speed in (1, 3, 5):
            for body in (False, True):
                for delay in (.08, .3):
                    key = f'{speed}m_s_{"body" if body else "ned"}_{delay}s'
                    result, _ = synthetic_tracking(profile, speed, body=body, delay=delay)
                    report['tracking'][name][key] = result
    # Explicit checks are controller-model checks, not aircraft clearance.
    report['checks'] = {
        'faster_braking_all_speeds': all(report['braking']['responsive'][str(s)]['seconds_to_005_m_s'] < report['braking']['stock'][str(s)]['seconds_to_005_m_s'] for s in (1,3,5)),
        'lower_tracking_rms_all_cases': all(v['rms_horizontal_error_m'] < report['tracking']['stock'][k]['rms_horizontal_error_m'] for k,v in report['tracking']['responsive'].items()),
        'responsive_min_separation_at_least_2m': all(v['min_estimated_separation_m'] >= 2 for v in report['tracking']['responsive'].values()),
        'responsive_final_hover_below_005m_s': all(v['final_hover_speed_rms_m_s'] < .05 for v in report['tracking']['responsive'].values()),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'motion-profile-comparison.json').write_text(json.dumps(report, indent=2))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    fig, ax = plt.subplots(figsize=(8,4))
    for name, trace in traces.items():
        ax.plot(*zip(*trace), label=name)
    ax.set(xlabel='Seconds after zero-velocity request', ylabel='Shaped command (m/s)',
           title='5 m/s braking: production shaper, not measured aircraft stopping')
    ax.legend(); ax.grid(alpha=.3); fig.tight_layout()
    fig.savefig(args.output_dir/'motion-profile-braking.png', dpi=160)
    plt.close(fig)
    print(json.dumps({'checks':report['checks'], 'braking':report['braking']}, indent=2))
    return 0 if all(report['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
