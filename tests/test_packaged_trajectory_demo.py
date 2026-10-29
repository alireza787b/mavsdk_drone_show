"""A fresh checkout must not ship an already-stale Mission 4 demo."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('mode', ['real', 'sitl'])
def test_bundled_demo_passes_canonical_review_in_a_fresh_mode_process(mode):
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'MDS_MODE': mode, 'MDS_SITL_SHARED_SWARM_TRAJECTORY_DIR': '',
                   'PYTHONPATH': os.pathsep.join(str(root / directory) for directory in ('gcs-server', 'src', '.'))}
    result = subprocess.run([sys.executable, '-c', '''
from functions.swarm_trajectory_service import get_workspace_payload
from config import load_config
w = get_workspace_payload()
v = w['validation']
assert v['ready'], v
assert not v['blockers'] and not v['warnings'] and not v['advisories'], v
assert set(v['processed_drone_ids']) == set(v['expected_drone_ids'])
assert set(v['expected_drone_ids']) == {int(row['hw_id']) for row in load_config()}
assert w['formation']['saved'] and w['launch_identity']['files']
assert len(w['preview']['drones']) == len(v['expected_drone_ids'])
'''], cwd=root, env=environment, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
