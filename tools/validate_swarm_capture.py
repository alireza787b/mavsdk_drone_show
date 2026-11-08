#!/usr/bin/env python3
"""SITL-only rehearsal of ground/hover capture, Body following and return.

Uses the canonical command, capture and Apply APIs. Never runs on REAL mode;
existing flight cleanup owns safe landing if a later assertion fails.
"""
from __future__ import annotations

import argparse
import copy
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.enums import Mission
from src.smart_swarm_contract import resolve_clusters
from tools.analyze_smart_swarm_tracking import FieldRehearsalClient, land_armed_targets_and_wait_idle
from tools.runtime_validation_support import ValidationHttpError, require, write_json_report
from tools.validate_smart_swarm_runtime import (
    cluster_assignments, require_full_acceptance, require_full_execution,
    wait_api_ready, wait_fleet_ready, wait_for, wait_for_command,
    wait_formation, wait_idle_reset,
)


def run(args):
    client = FieldRehearsalClient(args.base_url, timeout_sec=30)
    result = {'status': 'failed', 'events': []}
    original, ids, takeoff_id, flight_attempted = None, [], None, False
    owned_revisions = set()

    def evidence(stage, **facts):
        result['events'].append({'stage': stage, 'at_ms': int(time.time() * 1000), **facts})
        write_json_report(args.output_dir / 'summary.json', result)
        print(stage, flush=True)

    def capture(frame='body', height_mode='keep', leader=None):
        current = client.get_swarm_resource()
        cluster = next(c for c in resolve_clusters(current['assignments'])
                       if {int(m['hw_id']) for m in c['members']} == set(ids))
        snapshot = client.post_json('/api/v1/config/swarm/capture-preview', {
            'revision': current['revision'], 'assignments': current['assignments'],
            'cluster_id': cluster['cluster_id'], 'frame': frame, 'height_mode': height_mode,
            **({'leader_hw_id': str(leader)} if leader is not None else {}),
        })
        require(snapshot['saved'] is False and snapshot['commands_sent'] is False,
                'Capture must not save or dispatch')
        require(client.get_swarm_resource()['revision'] == current['revision'],
                'Read-only capture changed the saved formation')
        require(set(snapshot['observations']) == {str(hw) for hw in ids}, 'Capture omitted a member')
        return snapshot

    def apply(snapshot):
        current = client.get_swarm_resource()
        owned_revisions.add(current['revision'])
        from src.smart_swarm_contract import topology_revision
        owned_revisions.add(topology_revision(snapshot['assignments']))
        response = client.put_swarm_resource({
            'revision': current['revision'], 'assignments': snapshot['assignments'],
            'require_inactive_hw_ids': [str(hw) for hw in ids],
        })
        evidence('apply', application=response)
        return response

    def command(mission, label, targets=None, extra=None):
        receipt = client.submit_command(mission, targets or ids, label, extra_fields=extra)
        status = wait_for_command(client, receipt['command_id'], terminal=True, timeout=240)
        evidence(label, command=status)
        require(status['status'] == 'completed', f'{label} did not complete')
        require_full_acceptance(status, len(targets or ids), label)
        require_full_execution(status, len(targets or ids), label)
        return status

    def start_and_settle():
        receipt = client.start_saved_swarm(ids)
        status = wait_for_command(client, receipt['command_id'], desired_phase='in_progress', timeout=90)
        require_full_acceptance(status, len(ids), 'Start Swarm')
        evidence('start', command=status)
        # Captured targets already match current positions, so geometry alone
        # can appear settled before the role barrier has engaged any follower.
        # Wait for native role/installation reports before exercising the leader.
        revision = client.get_swarm_resource()['revision']
        def engaged():
            observed = client.get_json('/api/v1/commands/' + receipt['command_id'])
            if observed.get('status') in {'failed', 'cancelled', 'timeout'}:
                raise RuntimeError(f"Swarm startup failed: {observed.get('error_summary')}")
            runtime = observed.get('swarm_runtime') or {}
            reports = runtime.get('nodes') or {}
            return observed if (runtime.get('leader_session_active') is True and all(
                reports.get(str(hw), {}).get('phase') in {'active', 'acquiring', 'settling', 'tracking'}
                and reports[str(hw)].get('applied_revision') == revision for hw in ids)) else False
        evidence('engaged', command=wait_for(engaged, label='native roles engaged', timeout=90))
        errors = wait_formation(client, cluster_assignments(client.get_swarm(), ids), ids,
            horizontal_tolerance=0.8, altitude_tolerance=0.6, minimum_timeout=90,
            stability_samples=3, max_velocity=3.)
        evidence('settled', errors=errors, telemetry=client.get_telemetry())

    try:
        wait_api_ready(client)
        result['runtime'] = client.require_sitl_runtime()
        original = copy.deepcopy(client.get_swarm_resource())
        clusters = resolve_clusters(original['assignments'])
        cluster = next((c for c in clusters if c['cluster_id'] == str(args.cluster_id)), None)
        require(cluster is not None, 'Select an existing complete cluster')
        ids = sorted(int(m['hw_id']) for m in cluster['members'])
        require(len(ids) >= 2, 'Capture rehearsal needs a leader and follower')
        result['ids'] = ids
        wait_fleet_ready(client, ids, timeout=120)
        baseline = client.get_telemetry()
        require(all(baseline[str(hw)].get('is_armed') is False for hw in ids), 'Begin disarmed')
        for frame in ('ned', 'body'):
            snapshot = capture(frame)
            require(snapshot['flight_state'] == 'grounded' and snapshot['recommended_height_mode'] == 'level',
                    'Grounded cluster must recommend Same height from native evidence')
            evidence('ground_capture_' + frame, capture=snapshot)
        if args.ground_inspect_seconds:
            evidence('ground_inspection_window', duration_sec=args.ground_inspect_seconds)
            time.sleep(args.ground_inspect_seconds)
        apply(snapshot)
        flight_attempted = True
        receipt = client.submit_command(Mission.TAKE_OFF.value, ids, 'Capture rehearsal coordinated Takeoff',
            extra_fields={'takeoff_altitude': 8, 'takeoff_mode': 'coordinated'})
        takeoff_id = receipt['command_id']
        status = wait_for_command(client, takeoff_id, terminal=True, timeout=240)
        evidence('takeoff', command=status)
        require(status['status'] == 'completed', 'Coordinated Takeoff failed')
        require_full_execution(status, len(ids), 'Takeoff')
        start_and_settle()
        try:
            capture()
        except ValidationHttpError as exc:
            require(exc.status_code == 409, 'Active capture must reject without mutating')
            evidence('active_capture_rejected', detail=exc.payload)
        else:
            raise RuntimeError('Capture unexpectedly accepted active following')
        leader = int(next(m['hw_id'] for m in client.get_swarm() if int(m['follow']) == 0 and int(m['hw_id']) in ids))
        command(Mission.PRECISION_MOVE.value, 'Leader translation', [leader], {'precision_move': {
            'frame': 'ned', 'translation_m': {'north': 2., 'east': 0., 'up': 0.},
            'yaw': {'mode': 'hold_current'}, 'speed_m_s': 1.}})
        errors = wait_formation(client, cluster_assignments(client.get_swarm(), ids), ids,
            horizontal_tolerance=0.8, altitude_tolerance=0.6, minimum_timeout=90,
            stability_samples=3, max_velocity=3.)
        evidence('translation_followed', errors=errors, telemetry=client.get_telemetry())
        command(Mission.PRECISION_MOVE.value, 'Leader yaw rotation', [leader], {'precision_move': {
            'frame': 'ned', 'translation_m': {'north': 0., 'east': 0., 'up': 0.},
            'yaw': {'mode': 'relative_delta', 'degrees': 30.}, 'speed_m_s': 1.}})
        errors = wait_formation(client, cluster_assignments(client.get_swarm(), ids), ids,
            horizontal_tolerance=0.8, altitude_tolerance=0.6, minimum_timeout=90,
            stability_samples=3, max_velocity=3.)
        evidence('body_rotation_followed', errors=errors, telemetry=client.get_telemetry())
        command(Mission.HOLD.value, 'Hold before hover capture')
        # Establish a nonzero physical height difference: Current must be
        # measured, not merely equal to an already-level planned formation.
        command(Mission.PRECISION_MOVE.value, 'Establish measured height difference', [ids[0]], {'precision_move': {
            'frame': 'ned', 'translation_m': {'north': 0., 'east': 0., 'up': .75},
            'yaw': {'mode': 'hold_current'}, 'speed_m_s': .5}})
        def current_capture():
            try:
                return capture(height_mode='current')
            except ValidationHttpError:
                return False
        current = wait_for(current_capture, label='settled current-height capture', timeout=45, interval=2)
        by_id = current['observations']
        require(current['current_heights_available'] is True, 'Current height capability not confirmed')
        require(current['flight_state'] == 'airborne' and current['recommended_height_mode'] == 'current',
                'Settled airborne cluster must recommend Current heights')
        for member in current['assignments']:
            hw, parent = str(member['hw_id']), str(member['follow'])
            if int(hw) in ids and parent != '0':
                expected_up = by_id[hw]['altitude_msl_m'] - by_id[parent]['altitude_msl_m']
                require(abs(member['offset_z'] - expected_up) < 1e-6, 'Current height used a different altitude datum')
        evidence('hover_capture_current_heights', capture=current)
        if args.hover_inspect_seconds:
            evidence('hover_inspection_window', duration_sec=args.hover_inspect_seconds)
            time.sleep(args.hover_inspect_seconds)
        apply(current)
        start_and_settle()
        command(Mission.HOLD.value, 'Hold before level reroot capture')
        # Two timestamped capture samples, not a blind sleep, establish settling.
        last_error = None
        def settled_capture():
            nonlocal last_error
            try:
                return capture(height_mode='level', leader=ids[0])
            except ValidationHttpError as exc:
                last_error = exc.payload
                return False
        snapshot = wait_for(settled_capture, label='settled airborne capture', timeout=45, interval=2)
        require(all(m['offset_z'] == 0 for m in snapshot['assignments'] if int(m['hw_id']) in ids),
                'Same height must zero planned relative offsets')
        evidence('hover_capture_reroot_level', capture=snapshot)
        apply(snapshot)
        start_and_settle()
        if args.inspect_seconds:
            evidence('inspection_window', duration_sec=args.inspect_seconds)
            time.sleep(args.inspect_seconds)
        client.require_sitl_runtime()
        queue = client.post_json('/api/v1/swarm/runtime/sequential-return', {
            'target_drone_ids': [str(hw) for hw in ids], 'delay_sec': 10,
            'idempotency_key': str(uuid.uuid4()),
        })
        evidence('managed_return', queue=queue)
        wait_idle_reset(client, ids, timeout=240)
        evidence('landed', telemetry=client.get_telemetry())
        result['status'] = 'passed'
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        if flight_attempted:
            result['cleanup'] = land_armed_targets_and_wait_idle(client, ids,
                wait_for_command=wait_for_command, wait_idle_reset=wait_idle_reset,
                require_full_acceptance=require_full_acceptance, require_full_execution=require_full_execution,
                pending_takeoff_id=takeoff_id)
        if original is not None:
            client.require_sitl_runtime()
            current = client.get_swarm_resource()
            require(current['revision'] in owned_revisions or current['revision'] == original['revision'],
                    'Saved formation changed externally; refusing to overwrite it during restore')
            if current['revision'] != original['revision']:
                client.put_swarm_resource({'assignments': original['assignments'], 'revision': current['revision']})
            result['restored'] = client.get_swarm_resource()['revision'] == original['revision']
        write_json_report(args.output_dir / 'summary.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5031')
    parser.add_argument('--cluster-id', type=int, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--inspect-seconds', type=int, choices=range(0, 61), default=0)
    parser.add_argument('--ground-inspect-seconds', type=int, choices=range(0, 121), default=0)
    parser.add_argument('--hover-inspect-seconds', type=int, choices=range(0, 121), default=0)
    run(parser.parse_args())
