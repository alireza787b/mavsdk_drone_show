#!/usr/bin/env python3
"""SITL-only two-aircraft formation Apply and Hold-preservation rehearsal.

Uses the existing field-rehearsal client and flight wait/cleanup helpers. No
automatic unavailable-aircraft confirmation, Git publication, or hardware mode.
"""
from __future__ import annotations

import argparse
import copy
import math
import sys
import time
from pathlib import Path

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
    parser.add_argument('--output-dir', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
