#!/usr/bin/env python3
"""SITL-only whole-cluster Start, follower stop/retry and reference rejection.

Uses existing native admission and command APIs. No PX4 parameters or saved
roles are changed; no uncertain POST is retried. The caller owns lab lifecycle.
"""
import argparse
import json
import sys
import urllib.parse
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.runtime_validation_support import fetch_and_require_sitl_runtime
from tools.validate_smart_swarm_runtime import (
    ApiClient, wait_for, wait_fleet_ready, wait_for_command, wait_idle_reset,
)


def run(client, cluster_id, output):
    fetch_and_require_sitl_runtime(client.base_url)
    preview = client.get_json('/api/v1/swarm/runtime/preview')
    cluster = next(c for c in preview['clusters'] if c['cluster_id'] == cluster_id)
    ids = [m['hw_id'] for m in cluster['members']]
    follower = next(m['hw_id'] for m in cluster['members'] if m['follow'] != '0')
    leader = cluster_id
    report = {'cluster': cluster, 'revision': preview['revision'], 'steps': {}}

    def status(cid):
        return client.get_json(f'/api/v1/commands/{cid}')

    def scoped_review(targets, ready=True):
        query = urllib.parse.urlencode([('cluster_id', cluster_id), ('check_start', 'true'),
                                       *[('target_hw_ids', hw) for hw in targets]])
        def check():
            value = client.get_json('/api/v1/swarm/runtime/preview?' + query)
            assert value['revision'] == preview['revision'], 'Formation changed'
            decisions = {**value['start_admissions'], **value.get('reference_admissions', {})}
            eligible = all(row['status'] == 'ready' and row['valid_for_ms'] > 0 for row in decisions.values())
            return value if eligible == ready else False
        return wait_for(check, label=f'native scoped review {targets}', timeout=60)

    def start(targets):
        review = scoped_review(targets)
        receipt = client.post_json('/api/v1/swarm/runtime/start', {
            'cluster_id': cluster_id, 'revision': preview['revision'],
            'target_hw_ids': targets, 'idempotency_key': str(uuid.uuid4()),
        })
        cid = receipt['command_id']
        def engaged():
            value = status(cid)
            runtime = value.get('swarm_runtime') or {}
            return value if set(runtime.get('active_hw_ids', [])) == set(targets) else False
        evidence = wait_for(engaged, label=f'selected role engagement {targets}', timeout=60)
        assert set(evidence['target_drones']) == set(targets)
        return cid, {'review': review, 'receipt': receipt, 'engaged': evidence}

    try:
        wait_fleet_ready(client, list(map(int, ids)), timeout=120)
        cid, _ = client.submit_command(10, list(map(int, ids)), 'Scoped Start rehearsal Takeoff')
        wait_for_command(client, cid, terminal=True, timeout=150)
        full, report['steps']['full_start'] = start(ids)
        before = client.get_json('/api/v1/swarm/runtime/preview')['runtime_nodes']
        hold, _ = client.submit_command(102, [int(follower)], 'Stop selected follower')
        wait_for_command(client, hold, terminal=True, timeout=60)
        retry, report['steps']['follower_retry'] = start([follower])
        after = client.get_json('/api/v1/swarm/runtime/preview')['runtime_nodes']
        assert after[follower]['command_id'] == retry
        for hw in ids:
            if hw != follower:
                assert after[hw]['command_id'] == before[hw]['command_id'] == full
                assert not after[hw]['stale'], f'Unselected role {hw} lost evidence'
        report['steps']['unchanged_other_roles'] = after

        # A settled, grounded source cannot authorize follower-only Start.
        stop, _ = client.submit_command(102, [int(follower)], 'Stop follower before source rejection')
        wait_for_command(client, stop, terminal=True, timeout=60)
        land, _ = client.submit_command(101, [int(leader)], 'Land reference for negative check')
        wait_for_command(client, land, terminal=True, timeout=150)
        blocked = scoped_review([follower], ready=False)
        assert blocked['reference_admissions'][leader]['status'] != 'ready'
        report['steps']['grounded_reference_blocked'] = blocked
        assert client.get_json('/api/v1/swarm/runtime/preview')['revision'] == preview['revision']
        report['passed'] = True
    except Exception as exc:
        report['passed'] = False
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        cid, _ = client.submit_command(101, list(map(int, ids)), 'Scoped rehearsal cleanup Land')
        wait_for_command(client, cid, terminal=True, timeout=150)
        wait_idle_reset(client, list(map(int, ids)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--cluster-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(ApiClient(args.base_url), args.cluster_id, args.output)
