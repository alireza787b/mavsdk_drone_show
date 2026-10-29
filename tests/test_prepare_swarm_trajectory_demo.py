import json
import math

import pytest

from tools.prepare_swarm_trajectory_demo import (
    ENTRY_HOLD_S, MOTION_S, EXIT_HOLD_S, SAMPLE_STEP_S,
    backup_workspace, build_demo_rows, read_demo_origin,
)


def test_demo_is_closed_slow_and_has_explicit_msl_without_fake_terrain_evidence():
    rows = build_demo_rows(dict(lat=0, lon=0, alt=100))
    assert len(rows) == int((ENTRY_HOLD_S + MOTION_S + EXIT_HOLD_S) / SAMPLE_STEP_S) + 1
    assert rows[0]['TimeFromStart_s'] == 0
    assert rows[-1]['TimeFromStart_s'] == ENTRY_HOLD_S + MOTION_S + EXIT_HOLD_S
    assert rows[0]['Latitude'] == pytest.approx(rows[-1]['Latitude'])
    assert rows[0]['Longitude'] == pytest.approx(rows[-1]['Longitude'])
    assert all(row['Altitude_MSL_m'] == 120 and row['AltitudeReference'] == 'MSL' for row in rows)
    assert max(row['EstimatedSpeed_ms'] for row in rows) < 1.5
    assert all(row['Heading_deg'] == 0 and 'TerrainAccurate' not in row for row in rows)
    for row in [row for row in rows if row['TimeFromStart_s'] <= ENTRY_HOLD_S
                or row['TimeFromStart_s'] >= ENTRY_HOLD_S + MOTION_S]:
        assert row['Latitude'] == rows[0]['Latitude']
        assert row['Longitude'] == rows[0]['Longitude']
        assert row['EstimatedSpeed_ms'] == 0


def test_origin_uses_runtime_override_without_changing_it_and_preserves_zero(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    default = data / 'origin.sitl.default.json'
    default.write_text(json.dumps(dict(lat=35, lon=51, alt=1278)))
    assert read_demo_origin(tmp_path)['alt'] == 1278
    override = data / 'origin.json'
    original = json.dumps(dict(lat=0, lon=0, alt=0))
    override.write_text(original)
    assert read_demo_origin(tmp_path) == dict(lat=0, lon=0, alt=0)
    assert override.read_text() == original
    assert read_demo_origin(tmp_path, default)['lat'] == 35


@pytest.mark.parametrize('value', [math.nan, math.inf, -91, 91])
def test_bad_origin_does_not_authorize_a_demo(tmp_path, value):
    origin = tmp_path / 'origin.json'
    origin.write_text(json.dumps(dict(lat=value, lon=0, alt=0)))
    with pytest.raises(ValueError):
        read_demo_origin(tmp_path, origin)


def test_replacement_requires_explicit_choice_and_keeps_original_bytes(tmp_path):
    workspace = tmp_path / 'swarm_trajectory'
    workspace.mkdir()
    (workspace / 'edited.csv').write_bytes(b'operator draft\n')
    with pytest.raises(ValueError, match='--replace'):
        backup_workspace(workspace, tmp_path / 'backups')
    backup = backup_workspace(workspace, tmp_path / 'backups', replace=True)
    assert (backup / 'edited.csv').read_bytes() == b'operator draft\n'
    assert not workspace.exists()
