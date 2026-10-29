#!/usr/bin/env python3
"""Prepare a reviewed demo package, never dispatch flight commands.

Run on an idle GCS checkout. Existing trajectory assets are moved to an ignored
backup before replacement. The live swarm and formation origin are never edited.
"""

import argparse
import csv
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import shutil
import sys
import uuid

ENTRY_HOLD_S = 30
MOTION_S = 100
EXIT_HOLD_S = 30
SAMPLE_STEP_S = .5


def read_demo_origin(root, explicit_path=None):
    root = Path(root)
    path = Path(explicit_path) if explicit_path else root / 'data/origin.json'
    if not explicit_path and not path.exists():
        path = root / 'data/origin.sitl.default.json'
    value = json.loads(path.read_text())
    origin = {key: float(value[key]) for key in ('lat', 'lon', 'alt')}
    if (not all(math.isfinite(number) for number in origin.values())
            or abs(origin['lat']) > 90 or abs(origin['lon']) > 180):
        raise ValueError('Demo requires a finite WGS84/MSL origin')
    return origin


def build_demo_rows(origin, *, east=0.0, radius=10.0, height=20.0):
    """One slow closed loop, fixed heading, with 30-second entry/exit holds.

    A minimum-jerk phase ramp gives the sampled loop zero endpoint velocity and
    acceleration. The normal processor remains the owner of interpolation.
    """
    from pyproj import Geod

    if not all(math.isfinite(value) for value in (east, radius, height)) or radius <= 0 or height <= 0:
        raise ValueError('Demo radius and height must be finite and positive')
    rows = []
    geodesic = Geod(ellps='WGS84')
    for index in range(int((ENTRY_HOLD_S + MOTION_S + EXIT_HOLD_S) / SAMPLE_STEP_S) + 1):
        time_s = index * SAMPLE_STEP_S
        phase = min(1.0, max(0.0, (time_s - ENTRY_HOLD_S) / MOTION_S))
        ramp = phase ** 3 * (10 - 15 * phase + 6 * phase ** 2)
        angle = 2 * math.pi * ramp
        north_m = radius * (math.cos(angle) - 1)
        east_m = east + radius * math.sin(angle)
        longitude, latitude, _ = geodesic.fwd(origin['lon'], origin['lat'],
            math.degrees(math.atan2(east_m, north_m)), math.hypot(north_m, east_m))
        speed = radius * 2 * math.pi * 30 * phase ** 2 * (1 - phase) ** 2 / MOTION_S
        rows.append(dict(
            Name=f'Demo {index + 1}', Latitude=round(float(latitude), 12),
            Longitude=round(float(longitude), 12), Altitude_MSL_m=origin['alt'] + height,
            TimeFromStart_s=time_s, EstimatedSpeed_ms=round(speed, 4),
            Heading_deg=0.0, HeadingMode='manual', AltitudeReference='MSL',
            TimingMode='manual_time',
        ))
    return rows


def backup_workspace(base, backup_root, *, replace=False):
    base, backup_root = Path(base), Path(backup_root)
    if not base.exists():
        return None
    if not replace:
        raise ValueError('Workspace exists; use --replace to back it up and install the demo')
    backup = backup_root / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(base), str(backup))
    return backup


def prepare_demo(root, mode, *, origin_path=None, replace=False):
    # Imports are delayed until main has selected MDS_MODE, before Params loads.
    import navpy
    import numpy as np
    import pandas as pd
    from config import load_swarm
    from functions.swarm_analyzer import analyze_swarm_structure
    from functions.swarm_trajectory_processor import process_swarm_trajectories
    from functions.swarm_trajectory_service import get_workspace_payload
    from functions.swarm_trajectory_utils import get_swarm_trajectory_folders
    from functions.trajectory_formation import read_formation, save_formation
    from src.params import Params
    from src.swarm_trajectory_contract import verify_local_package

    root = Path(root).resolve()
    if Params.sim_mode != (mode == 'sitl'):
        raise ValueError('Select MDS_MODE before importing mission services')
    expected = root / ('shapes_sitl' if Params.sim_mode else 'shapes') / 'swarm_trajectory'
    base = Path(get_swarm_trajectory_folders()['base']).resolve()
    if base != expected:
        raise ValueError('Demo preparation requires this checkout, not an external shared trajectory directory')
    origin = read_demo_origin(root, origin_path)
    # Explicitly seed this demo from configured roles, not an obsolete snapshot.
    assignments = load_swarm(str(root / Params.swarm_file_name))
    structure = analyze_swarm_structure(assignments)
    if not structure['top_leaders']:
        raise ValueError('No configured leader for the demo')
    span = sum(math.hypot(float(row.get('offset_x', 0)), float(row.get('offset_y', 0)))
               for row in assignments)
    spacing = 2 * span + 60  # Parallel clusters cannot cross each other's envelope.
    backup = backup_workspace(base, root / 'artifacts/trajectory-demo-backups' / mode, replace=replace)
    try:
        initial = read_formation(base, fallback=lambda: assignments)
        save_formation(assignments, initial['revision'], base, fallback=lambda: assignments)
        raw = base / 'raw'
        raw.mkdir(parents=True, exist_ok=True)
        leaders = sorted(structure['top_leaders'])
        for index, leader in enumerate(leaders):
            rows = build_demo_rows(origin, east=(index - (len(leaders) - 1) / 2) * spacing)
            with (raw / f'Drone {leader}.csv').open('w', newline='') as output:
                writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator='\n')
                writer.writeheader()
                writer.writerows(rows)
        result = process_swarm_trajectories(force_clear=True, auto_reload=False)
        if not result.get('success') or not result.get('published'):
            raise ValueError(f'Demo generation failed: {result}')
        workspace = get_workspace_payload()
        validation = workspace['validation']
        if not validation['ready'] or any(validation[key] for key in ('blockers', 'warnings', 'advisories')):
            raise ValueError(f'Demo review is not clean: {validation}')
        ids = validation['expected_drone_ids']
        positions, max_speed, max_acceleration = [], 0.0, 0.0
        reference_times = None
        for drone_id in ids:
            path = base / 'processed' / f'Drone {drone_id}.csv'
            verify_local_package(workspace['launch_identity'], drone_id, path)
            frame = pd.read_csv(path)
            times = frame['t'].to_numpy()
            if reference_times is None:
                reference_times = times
            if not np.array_equal(reference_times, times) or np.min(np.diff(times)) < 0.01:
                raise ValueError('Demo sample clocks are not aligned at a usable timestep')
            motion = frame[['vx', 'vy', 'vz', 'ax', 'ay', 'az']].to_numpy()
            if not np.isfinite(motion).all():
                raise ValueError('Non-finite demo motion')
            max_speed = max(max_speed, float(np.linalg.norm(motion[:, :3], axis=1).max()))
            max_acceleration = max(max_acceleration, float(np.linalg.norm(motion[:, 3:], axis=1).max()))
            positions.append(navpy.lla2ned(frame['lat'].to_numpy(), frame['lon'].to_numpy(),
                             frame['alt'].to_numpy(), origin['lat'], origin['lon'], origin['alt']))
        separation = min((float(np.linalg.norm(a - b, axis=1).min())
                          for index, a in enumerate(positions) for b in positions[index + 1:]), default=None)
        if max_speed > 2 or max_acceleration > 1 or (separation is not None and separation < 3):
            raise ValueError(f'Demo exceeds its review envelope: speed={max_speed}, acceleration={max_acceleration}, separation={separation}')
        manifest = dict(name='Home loop demo', mode=mode, origin=origin,
                        duration_s=ENTRY_HOLD_S + MOTION_S + EXIT_HOLD_S,
                        entry_hold_s=ENTRY_HOLD_S, exit_hold_s=EXIT_HOLD_S, radius_m=10, height_above_origin_m=20,
                        aircraft_ids=ids, max_speed_ms=round(max_speed, 3),
                        max_acceleration_mss=round(max_acceleration, 3),
                        minimum_separation_m=round(separation, 3) if separation is not None else None,
                        planning_ready=True, flight_validated=False)
        (base / 'demo.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return {**manifest, 'backup': str(backup) if backup else None,
                'session_revision': workspace['launch_identity']['revision']}
    except BaseException:
        # Preserve failed output as evidence and put the entire original back.
        if base.exists():
            failed = root / 'artifacts/trajectory-demo-backups' / f'failed-{uuid.uuid4().hex}'
            failed.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(base), str(failed))
        if backup:
            shutil.move(str(backup), str(base))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['real', 'sitl'], required=True)
    parser.add_argument('--origin', type=Path, help='Reviewed WGS84/MSL JSON; default: runtime origin, then stock origin')
    parser.add_argument('--replace', action='store_true', help='Back up and replace this mode’s trajectory package')
    args = parser.parse_args()
    os.environ['MDS_MODE'] = args.mode
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / 'gcs-server'), str(root / 'src')]
    logging.basicConfig(level=logging.WARNING)
    print(json.dumps(prepare_demo(root, args.mode, origin_path=args.origin, replace=args.replace), indent=2))


if __name__ == '__main__':
    main()
