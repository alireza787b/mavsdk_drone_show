import pytest
from pydantic import ValidationError

from src.command_contract import DroneCommandRequest, SubmitCommandRequest
from src.coordinated_takeoff_contract import TakeoffStageRequest, TakeoffStageResponse
from src.launch_preparation_protocol import LaunchPreparationBinding
from src.enums import Mission


def report(**changes):
    return dict(command_id='takeoff-1', hw_id='1', sequence=0, state='armed_ready',
                armed=True, landed_state='ON_GROUND', lease_remaining_ms=5000, **changes)


def test_takeoff_mode_is_explicit_typed_and_mission_specific():
    for mode in ('coordinated', 'independent'):
        command = SubmitCommandRequest(mission_type=10, target_drone_ids=['1', '2'], takeoff_mode=mode)
        assert command.takeoff_mode == mode
    with pytest.raises(ValidationError):
        SubmitCommandRequest(mission_type=10, target_drone_ids=['1'], takeoff_mode='force')
    with pytest.raises(ValidationError):
        SubmitCommandRequest(mission_type=101, target_drone_ids=['1'], takeoff_mode='coordinated')


def test_mode_is_bound_into_existing_preparation_identity():
    base = dict(mission_type=10, command_id='takeoff-1', target_hw_id='1',
                command_report_capability='x' * 43)
    a = LaunchPreparationBinding.from_command(DroneCommandRequest(**base, takeoff_mode='coordinated'))
    b = LaunchPreparationBinding.from_command(DroneCommandRequest(**base, takeoff_mode='independent'))
    assert a.immutable_payload_sha256 != b.immutable_payload_sha256


def test_conditional_hold_cannot_become_a_general_launch_or_recovery_override():
    value = SubmitCommandRequest(mission_type=Mission.HOLD.value, target_drone_ids=['1'],
                                 expected_control_command_id='takeoff-1')
    assert value.expected_control_command_id == 'takeoff-1'
    for mission in (Mission.TAKE_OFF, Mission.LAND, Mission.RETURN_RTL):
        with pytest.raises(ValidationError):
            SubmitCommandRequest(mission_type=mission.value, target_drone_ids=['1'],
                                 expected_control_command_id='takeoff-1')


@pytest.mark.parametrize('change', [
    dict(armed=False), dict(armed='true'), dict(landed_state='IN_AIR'),
    dict(lease_remaining_ms=0), dict(sequence=-1), dict(sequence=True),
    dict(hw_id=' 1'), dict(unknown='ignored'), dict(challenge='short'),
])
def test_armed_barrier_cannot_accept_invalid_or_coerced_evidence(change):
    with pytest.raises(ValidationError):
        TakeoffStageRequest.model_validate({**report(), **change})


def test_failed_report_carries_no_fabricated_ground_proof():
    value = TakeoffStageRequest.model_validate({**report(), 'state': 'failed', 'armed': False,
                                               'landed_state': 'UNKNOWN', 'lease_remaining_ms': 0})
    assert value.landed_state == 'UNKNOWN'


def test_release_must_include_shared_release_and_server_clock():
    with pytest.raises(ValidationError):
        TakeoffStageResponse(decision='release')
    with pytest.raises(ValidationError):
        TakeoffStageResponse(decision='abort', release_at_unix_ms=10)
    assert TakeoffStageResponse(decision='release', release_at_unix_ms=2000,
                               server_time_unix_ms=1000).decision == 'release'
