#!/usr/bin/env python3
"""SITL-only two-aircraft formation Apply and Hold-preservation rehearsal.

Uses the existing field-rehearsal client and flight wait/cleanup helpers. No
automatic unavailable-aircraft confirmation, Git publication, or hardware mode.
"""
from __future__ import annotations

import argparse
import copy
import math
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.px4_flight_modes import describe_px4_custom_mode
from src.smart_swarm_contract import topology_revision
from tools.analyze_smart_swarm_tracking import (
    FieldRehearsalClient, HOLD, LAND, TAKEOFF,
    build_two_drone_ned_assignments, build_temporary_swarm_resource,
    land_armed_targets_and_wait_idle,
)
from tools.runtime_validation_support import write_json_report
from tools.validate_smart_swarm_runtime import (
    require, wait_api_ready, wait_fleet_ready, wait_for, wait_for_command,
    wait_altitude, wait_formation, wait_idle_reset, cluster_assignments,
    require_full_acceptance, require_full_execution, latlon_to_ne,
    docker_control,
)


def fresh_rows(client, ids, *, grounded=False):
    telemetry = client.get_telemetry()
    now = time.time() * 1000
    selected = {}
    for hw in ids:
        row = telemetry.get(str(hw), {})
        stamp = float(row.get('telemetry_timestamp_ms') or row.get('update_time') or 0)
        if stamp < 10_000_000_000:
            stamp *= 1000
        require(row.get('telemetry_available') is not False and 0 <= now - stamp <= 5000,
                f'Aircraft {hw} telemetry is not fresh')
        if grounded:
            landed = str(row.get('landed_state')).upper()
            require(row.get('is_armed') is False and landed in {'1', 'ON_GROUND', 'LANDEDSTATE.ON_GROUND'},
                    f'Aircraft {hw} must be natively on ground and disarmed')
            age = row.get('landed_state_age_ms')
            require(age is not None and 0 <= float(age) <= 5000, f'Aircraft {hw} landed evidence is stale')
        selected[str(hw)] = row
    return selected


def verify_selected_resource(resource, ids):
    require({int(m['hw_id']) for m in resource['assignments']} == set(ids),
            'This rehearsal requires an isolated formation containing exactly the two selected SITL aircraft')


def require_local_sitl_leader(client, leader_id):
    """Do not pause an unrelated local container when validating a remote GCS."""
    runtime = client.require_sitl_runtime()
    fleet = client.get_json('/api/v1/config/fleet')
    leader = next((d for d in fleet if int(d['hw_id']) == leader_id), None)
    require(leader is not None, 'Leader is absent from the target fleet')
    inspected = subprocess.run(['docker', 'inspect', f'drone-{leader_id}'],
                               capture_output=True, text=True, check=True, timeout=10)
    container = json.loads(inspected.stdout)[0]
    env = dict(value.split('=', 1) for value in container['Config'].get('Env', []) if '=' in value)
    networks = list(container['NetworkSettings']['Networks'].values())
    require(env.get('MDS_MODE') == 'sitl' and env.get('MDS_HW_ID') == str(leader_id),
            'Local container is not the selected SITL aircraft')
    require(leader['ip'] in {n['IPAddress'] for n in networks}, 'Local container IP differs from target leader')
    require(urlparse(client.base_url).hostname in {'127.0.0.1', 'localhost', '::1', *[n['Gateway'] for n in networks]},
            'Outage rehearsal requires the local GCS or its Docker bridge address')
    require(str(runtime['gcs_port']) == env.get('MDS_GCS_API_PORT', '5030'),
            'Local simulator reports to a different GCS port')


def apply_revision(client, assignments, ids, owned_revisions):
    client.require_sitl_runtime()
    current = client.get_swarm_resource()
    verify_selected_resource(current, ids)
    revision = current.get('revision')
    require(bool(revision), 'GCS must expose the new revision-aware formation API')
    next_revision = topology_revision(assignments)
    owned_revisions.add(next_revision)  # Lost HTTP reply still requires restore.
    response = client.put_swarm_resource({
        'version': current['version'], 'revision': revision, 'assignments': assignments,
    })
    require(response['config']['revision'] == next_revision, 'Apply returned the wrong revision')
    return response


def run(args):
    ids = [args.leader_id, args.follower_id]
    require(all(i > 0 for i in ids) and len(set(ids)) == 2, 'Select two distinct positive aircraft IDs')
    outage_sec = float(getattr(args, 'leader_outage_seconds', 0))
    require(math.isfinite(outage_sec) and outage_sec >= 0, 'Outage duration must be finite and non-negative')
    expect_expired = bool(getattr(args, 'expect_recovery_expired', False))
    require(not expect_expired or outage_sec > 0, 'Expiry rehearsal requires an induced outage')
    client = FieldRehearsalClient(args.base_url, bearer_token_file=args.api_token_file, timeout_sec=60)
    result = {'status': 'failed', 'selected_ids': ids, 'events': []}
    original = None
    owned_revisions = set()
    flight_attempted = False
    config_attempted = False
    takeoff_id = None

    def evidence(stage, **facts):
        result['events'].append({'stage': stage, 'at_ms': int(time.time() * 1000), **facts})
        write_json_report(args.output_dir / 'summary.json', result)

    def command(mission, label):
        receipt = client.submit_command(mission, ids, label)
        status = wait_for_command(client, receipt['command_id'], terminal=True, timeout=240)
        evidence(label, command=status)
        require(status['status'] == 'completed', f'{label} did not complete')
        require_full_acceptance(status, 2, label)
        require_full_execution(status, 2, label)
        return status

    try:
        wait_api_ready(client)
        result['runtime'] = client.require_sitl_runtime()
        original = copy.deepcopy(client.get_swarm_resource())
        verify_selected_resource(original, ids)
        owned_revisions.add(original['revision'])
        result['original'] = original
        wait_fleet_ready(client, ids, timeout=120)
        baseline = fresh_rows(client, ids, grounded=True)
        evidence('baseline', telemetry=baseline)
        altitude = {hw: float(row['position_alt']) for hw, row in baseline.items()}
        replacements = build_two_drone_ned_assignments(*ids, 6.0)
        staged = build_temporary_swarm_resource(original, replacements)['assignments']
        config_attempted = True
        evidence('stage', application=apply_revision(client, staged, ids, owned_revisions))

        flight_attempted = True
        takeoff = client.submit_command(TAKEOFF, ids, 'Swarm Design Apply rehearsal Takeoff')
        takeoff_id = takeoff['command_id']
        status = wait_for_command(client, takeoff_id, terminal=True, timeout=180)
        evidence('takeoff', command=status)
        require(status['status'] == 'completed', 'Paired Takeoff did not complete')
        require_full_acceptance(status, 2, 'Takeoff')
        require_full_execution(status, 2, 'Takeoff')
        wait_altitude(client, ids, altitude, 4.0)
        start = client.start_saved_swarm(ids)
        status = wait_for_command(client, start['command_id'], desired_phase='in_progress', timeout=90)
        require_full_acceptance(status, 2, 'Start Swarm')
        evidence('start', command=status)

        def installed(revision):
            observed = client.get_json('/api/v1/config/swarm/status')
            evidence('configuration_readback', application=observed)
            return observed if observed['revision'] == revision and all(
                n['status'] == 'applied' for n in observed['nodes'] if int(n['hw_id']) in ids
            ) and {int(n['hw_id']) for n in observed['nodes']} == set(ids) else False

        def settled(assignments):
            fresh_rows(client, ids)
            return wait_formation(client, cluster_assignments(assignments, ids), ids,
                                  horizontal_tolerance=0.8, altitude_tolerance=0.6,
                                  minimum_timeout=60, stability_samples=4, max_velocity=3.0)

        wait_for(lambda: installed(topology_revision(staged)), label='initial effective configuration', timeout=30)
        evidence('initial_settled', errors=settled(staged))
        changed = copy.deepcopy(staged)
        next(m for m in changed if int(m['hw_id']) == args.follower_id)['offset_y'] = 2.0
        evidence('live_apply', application=apply_revision(client, changed, ids, owned_revisions))
        wait_for(lambda: installed(topology_revision(changed)), label='both nodes installed new revision', timeout=30)
        evidence('changed_settled', errors=settled(changed), telemetry=fresh_rows(client, ids))

        if getattr(args, 'exercise_frame_changes', False):
            for label, edits in (
                ('offset_10m', {'offset_x': 10.0}),
                ('body_frame', {'frame': 'body'}),
                ('ned_frame', {'frame': 'ned'}),
            ):
                next(m for m in changed if int(m['hw_id']) == args.follower_id).update(edits)
                applied_at = time.monotonic()
                evidence(label + '_apply', application=apply_revision(client, changed, ids, owned_revisions))
                wait_for(lambda: installed(topology_revision(changed)), label=label + ' installed', timeout=30)
                evidence(label + '_installed', elapsed_sec=time.monotonic() - applied_at)
                evidence(label + '_settled', errors=settled(changed), telemetry=fresh_rows(client, ids))

        if outage_sec:
            require_local_sitl_leader(client, args.leader_id)
            held = False
            try:
                docker_control('pause', args.leader_id)
                deadline = time.monotonic() + outage_sec
                while time.monotonic() < deadline:
                    follower = fresh_rows(client, [args.follower_id])[str(args.follower_id)]
                    held = held or describe_px4_custom_mode(follower.get('flight_mode')) == 'Hold'
                    evidence('leader_outage', follower=follower)
                    time.sleep(0.25)
            finally:
                docker_control('unpause', args.leader_id)
            require(held, 'Follower did not report protective Hold during the induced outage')
            def recovered_telemetry():
                try:
                    return fresh_rows(client, ids)
                except RuntimeError:
                    return False
            wait_for(recovered_telemetry, label='fresh telemetry after leader return', timeout=30)
            require(client.get_swarm_resource()['revision'] == topology_revision(changed),
                    'Temporary leader loss changed the saved formation')
            if expect_expired:
                for _ in range(6):
                    follower = fresh_rows(client, [args.follower_id])[str(args.follower_id)]
                    require(describe_px4_custom_mode(follower['flight_mode']) == 'Hold',
                            'Follower resumed automatically after the recovery window expired')
                    evidence('recovery_expiry_hold', follower=follower)
                    time.sleep(0.5)
                command(HOLD, 'Explicit Stop after recovery expiry')
                restarted = client.start_saved_swarm(ids)
                wait_for_command(client, restarted['command_id'], desired_phase='in_progress', timeout=90)
                wait_for(lambda: installed(topology_revision(changed)),
                         label='restarted roles installed', timeout=30)
                def follower_offboard():
                    follower = fresh_rows(client, [args.follower_id])[str(args.follower_id)]
                    return follower if describe_px4_custom_mode(follower['flight_mode']) == 'Offboard' else False
                wait_for(follower_offboard, label='restarted follower owns Offboard', timeout=30)
                evidence('explicit_recovery_restart', command_id=restarted['command_id'])
            evidence('leader_recovered', errors=settled(changed), telemetry=fresh_rows(client, ids))
            require(describe_px4_custom_mode(fresh_rows(client, [args.follower_id])[str(args.follower_id)]['flight_mode']) == 'Offboard',
                    'Follower did not rejoin Offboard after the intended recovery/restart')

        hold = command(HOLD, 'Hold Swarm before inactive Apply')
        details = hold.get('executions', {}).get('details', {})
        require(all(details.get(str(i), {}).get('action_result', {}).get('final_vehicle_state', {}).get('outcome') == 'held'
                    for i in ids), 'Hold lacks typed held proof for both aircraft')
        wait_for(lambda: all(n['status'] == 'inactive' for n in client.get_json('/api/v1/config/swarm/status')['nodes']),
                 label='swarm stopped after Hold', timeout=30)
        held_start = fresh_rows(client, ids)
        evidence('apply_while_held', application=apply_revision(client, staged, ids, owned_revisions))
        for _ in range(12):
            rows = fresh_rows(client, ids)
            application = client.get_json('/api/v1/config/swarm/status')
            evidence('hold_preserved', telemetry=rows, application=application)
            require(all(n['status'] == 'inactive' for n in application['nodes']), 'Apply reactivated a held swarm')
            for hw, row in rows.items():
                require(describe_px4_custom_mode(row.get('flight_mode')) == 'Hold', f'Aircraft {hw} left Hold')
                n, e = latlon_to_ne(row['position_lat'], row['position_long'],
                                   held_start[hw]['position_lat'], held_start[hw]['position_long'])
                require(math.hypot(n, e) < 1.0, f'Held aircraft {hw} moved after Apply')
            time.sleep(1)
        command(LAND, 'Swarm Design Apply rehearsal Land')
        wait_idle_reset(client, ids)
        fresh_rows(client, ids, grounded=True)
        result['scenario_passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        cleanup_ok = True
        if flight_attempted:
            try:
                # Fence a potentially accepted Takeoff whose HTTP receipt was lost.
                if takeoff_id is None:
                    command(HOLD, 'Rehearsal cleanup Hold')
                result['cleanup'] = land_armed_targets_and_wait_idle(
                    client, ids, wait_for_command=wait_for_command, wait_idle_reset=wait_idle_reset,
                    require_full_acceptance=require_full_acceptance, require_full_execution=require_full_execution,
                    pending_takeoff_id=takeoff_id,
                )
                fresh_rows(client, ids, grounded=True)
            except Exception as exc:
                cleanup_ok = False
                result['cleanup_error'] = str(exc)
        if original and config_attempted and cleanup_ok:
            try:
                client.require_sitl_runtime()
                current = client.get_swarm_resource()
                require(current['revision'] in owned_revisions, 'Concurrent external formation edit; not overwriting it')
                result['restored'] = apply_revision(client, original['assignments'], ids, owned_revisions)
                require(client.get_swarm_resource()['revision'] == original['revision'], 'Restore readback differs')
            except Exception as exc:
                result['restore_error'] = str(exc)
        result['status'] = 'passed' if result.get('scenario_passed') and cleanup_ok and not result.get('restore_error') else 'failed'
        write_json_report(args.output_dir / 'summary.json', result)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--leader-id', type=int, required=True)
    parser.add_argument('--follower-id', type=int, required=True)
    parser.add_argument('--api-token-file', type=Path)
    parser.add_argument('--exercise-frame-changes', action='store_true',
                        help='Also rehearse 10m spacing and Body/NED reference changes')
    parser.add_argument('--leader-outage-seconds', type=float, default=0,
                        help='Pause the verified local SITL leader, then verify protective Hold and recovery (e.g. 4.5)')
    parser.add_argument('--expect-recovery-expired', action='store_true',
                        help='Verify an expired recovery stays held until explicit Stop/Start (e.g. a 14s outage with defaults)')
    parser.add_argument('--output-dir', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
