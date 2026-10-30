#!/usr/bin/env python3
"""SITL-only coordinated Takeoff success/cancellation drill with recorded stages.

Uses the normal API and command journal. Never accepts a REAL runtime. Aircraft
are landed in finally; this is a validation tool, not a field-flight shortcut.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.runtime_validation_support import ValidationApiClient, fetch_and_require_sitl_runtime
from src.enums import Mission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--targets', nargs='+', default=['1', '2'])
    parser.add_argument('--scenario', choices=['success', 'cancel', 'cancel-armed', 'blocked'], default='success')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    api = ValidationApiClient(args.base_url)
    fetch_and_require_sitl_runtime(args.base_url, client=api)
    targets = args.targets
    if len(targets) < 2 or len(set(targets)) != len(targets):
        raise ValueError('This drill requires at least two distinct aircraft')
    evidence = dict(scenario=args.scenario, targets=targets, stages=[], passed=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def submit(mission, **extra):
        return api.post_json('/api/v1/commands', dict(mission_type=mission.value,
            target_drone_ids=targets, trigger_time=0, idempotency_key=str(uuid.uuid4()), **extra))

    def track(cid, seconds=130):
        deadline = time.monotonic() + seconds
        previous = None
        while time.monotonic() < deadline:
            status = api.get_json(f'/api/v1/commands/{cid}')
            summary = {key: status.get(key) for key in ('phase', 'outcome', 'coordinated_takeoff', 'executions', 'acks')}
            if summary != previous:
                evidence['stages'].append(dict(at_ms=int(time.time()*1000), command_id=cid, **summary))
                previous = summary
                print(json.dumps(dict(command_id=cid, phase=status.get('phase'),
                    outcome=status.get('outcome'), coordination=status.get('coordinated_takeoff'))), flush=True)
            if status.get('phase') == 'terminal':
                return status
            time.sleep(.15)
        raise TimeoutError(f'Command {cid} did not reach a terminal state')

    launched = False
    try:
        query = '&'.join(f'target_drone_ids={hw}' for hw in targets)
        deadline = time.monotonic() + 60
        while True:
            ready = api.get_json('/api/v1/commands/takeoff-readiness?' + query)
            if ready['ready'] or args.scenario == 'blocked' or time.monotonic() >= deadline:
                break
            time.sleep(1)
        evidence['readiness'] = ready
        if args.scenario == 'blocked':
            assert not ready['ready'] and any(row['status'] == 'blocked' for row in ready['targets']), ready
        else:
            assert ready['ready'] and all(row['coordinated_takeoff_supported'] for row in ready['targets']), ready
        receipt = submit(Mission.TAKE_OFF, takeoff_altitude=5, takeoff_mode='coordinated')
        launched = True
        cid = receipt['command_id']
        if args.scenario == 'cancel-armed':
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                observed = api.get_json(f'/api/v1/commands/{cid}')
                barrier = observed.get('coordinated_takeoff') or {}
                assert barrier.get('release_at_unix_ms') is None, 'Release won cancellation race; do not claim an armed-cancel pass'
                if any(row.get('armed') is True for row in barrier.get('targets', {}).values()):
                    evidence['armed_before_cancel'] = barrier
                    break
                time.sleep(.03)
            assert evidence.get('armed_before_cancel'), 'No aircraft reached armed waiting'
        if args.scenario in {'cancel', 'cancel-armed'}:
            evidence['cancel'] = api.post_json(f'/api/v1/commands/{cid}/cancel-launch', {})
        final = track(cid)
        evidence['final'] = final
        if args.scenario == 'success':
            assert final['outcome'] == 'completed', final
            assert final['coordinated_takeoff']['phase'] == 'airborne', final
            assert set(final['coordinated_takeoff']['targets']) == set(targets)
            assert all(row['state'] == 'airborne' for row in final['coordinated_takeoff']['targets'].values())
        elif args.scenario in {'cancel', 'cancel-armed'}:
            assert final['coordinated_takeoff']['phase'] == 'aborted', final
            assert final['coordinated_takeoff'].get('release_at_unix_ms') is None, final
            if args.scenario == 'cancel-armed':
                for result in final['executions']['details'].values():
                    assert result['action_result']['final_vehicle_state']['armed'] is False, result
        else:
            assert final['outcome'] == 'failed', final
            assert final['coordinated_takeoff']['release_at_unix_ms'] is None, final
            assert final['acks']['received'] == 0 and final['executions']['received'] == 0, final
        evidence['passed'] = True
    finally:
        if launched and args.scenario != 'blocked':
            try:
                evidence['landing'] = track(submit(Mission.LAND)['command_id'])
                assert evidence['landing']['outcome'] == 'completed', evidence['landing']
            except Exception as exc:
                evidence['passed'] = False
                evidence['landing_error'] = str(exc)
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    if not evidence['passed']:
        raise RuntimeError('Validation failed; inspect the evidence file')


if __name__ == '__main__':
    main()
