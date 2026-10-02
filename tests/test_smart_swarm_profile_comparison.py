from pathlib import Path

from tools.compare_smart_swarm_motion_profiles import braking, profiles
from src.px4_param_models import Px4ParamPatchEntry
import json


ROOT = Path(__file__).resolve().parents[1]


def test_profile_comparison_uses_registered_stock_and_repo_example():
    values = profiles(ROOT / 'deployment/examples/smart-swarm-responsive.env')
    assert values['stock']['max_vertical_speed_m_s'] == .75
    assert values['responsive']['max_jerk_m_s3'] == 6
    for speed in (1, 3, 5):
        old, _ = braking(values['stock'], speed)
        new, _ = braking(values['responsive'], speed)
        assert new['seconds_to_005_m_s'] < old['seconds_to_005_m_s']
        assert new['commanded_travel_m'] < old['commanded_travel_m']


def test_navigation_profile_only_changes_logging_and_uses_typed_entries():
    data = json.loads((ROOT / 'resources/px4_param_profiles/navigation_diagnostics.json').read_text())
    entries = [Px4ParamPatchEntry.model_validate(row) for row in data['entries']]
    assert {entry.name: entry.value for entry in entries} == {'SDLOG_PROFILE': 9, 'SDLOG_MODE': 2}
