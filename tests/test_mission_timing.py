from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.enums import Mission
from src.mission_timing import (
    mission_commit_lead_seconds,
    mission_preparation_lead_seconds,
    resolve_show_preparation_seconds,
)


@pytest.mark.parametrize('mission', [Mission.DRONE_SHOW_FROM_CSV, Mission.CUSTOM_CSV_DRONE_SHOW, Mission.HOVER_TEST])
def test_only_synchronized_show_executors_get_the_preparation_budget(mission):
    params = SimpleNamespace(trigger_sooner_seconds=4, COMMAND_SYNC_DISPATCH_GUARD_SEC=1)
    assert mission_preparation_lead_seconds(mission, params=params) == 10
    assert mission_commit_lead_seconds(mission, params=params) == 11


@pytest.mark.parametrize('mission', [Mission.NONE, Mission.LAND, Mission.HOLD, Mission.RETURN_RTL,
    Mission.KILL_TERMINATE, Mission.TAKE_OFF, Mission.SMART_SWARM, Mission.SWARM_TRAJECTORY, Mission.QUICKSCOUT])
def test_other_missions_keep_their_existing_lead(mission):
    params = SimpleNamespace(trigger_sooner_seconds=4, SYNCHRONIZED_SHOW_PREPARATION_SEC=20,
        COMMAND_SYNC_DISPATCH_GUARD_SEC=1)
    assert mission_preparation_lead_seconds(mission, params=params) == 4
    assert mission_commit_lead_seconds(mission, params=params) == 5


@pytest.mark.parametrize('value', [None, 0, -1, float('nan'), float('inf'), True, 'invalid', Mock()])
def test_invalid_preparation_budgets_fall_back_to_the_finite_default(value):
    assert resolve_show_preparation_seconds(value) == 10


@pytest.mark.parametrize('value', [12, 12.5, '12.5'])
def test_preparation_budget_is_configurable_and_never_reduces_the_existing_lead(value):
    params = SimpleNamespace(trigger_sooner_seconds=4, SYNCHRONIZED_SHOW_PREPARATION_SEC=value)
    assert mission_preparation_lead_seconds(1, params=params) == float(value)
    params.trigger_sooner_seconds = 15
    assert mission_preparation_lead_seconds(1, params=params) == 15
