from copy import deepcopy

from swarm_return_scope import omitted_followers


def running(targets=('1', '2')):
    return {'command_id': 'swarm-1', 'mission_type': 2, 'target_drones': list(targets),
            'params': {'smart_swarm': {'assignments': [
                {'hw_id': '1', 'follow': '0'}, {'hw_id': '2', 'follow': '1'},
                {'hw_id': '3', 'follow': '2'}, {'hw_id': '4', 'follow': '0'},
                {'hw_id': '5', 'follow': '4'},
            ]}}}


def test_pair_return_ignores_never_started_offline_configuration_member():
    assert omitted_followers([running()], ['1', '2']) == []


def test_returning_a_leader_requires_its_active_or_pending_follower():
    assert omitted_followers([running()], ['1']) == ['2']
    assert omitted_followers([running(('3',))], ['1']) == ['3']
    assert omitted_followers([running(('3',))], ['2']) == ['3']


def test_follower_can_return_without_its_leader_or_an_independent_cluster():
    assert omitted_followers([running()], ['2']) == []
    assert omitted_followers([running(('5',))], ['1']) == []


def test_failed_or_missing_execution_is_not_proof_of_released_control():
    command = running()
    command['executions'] = {'details': {'2': {'success': False, 'outcome': 'failed'}}}
    assert omitted_followers([command], ['1']) == ['2']


def test_only_matching_typed_native_release_removes_an_old_producer():
    command = running()
    release = dict(schema_version=1, kind='control_release', command_id='swarm-1', ownership_token='owner',
                   hw_id='2', producers_stopped=True, offboard_stop_completed=True, hold_accepted=True,
                   observed_mode='HOLD', external_control_preserved=False)
    command['executions'] = {'details': {'2': {'control_release': release}}}
    assert omitted_followers([command], ['1']) == []
    for field, value in [('hw_id', '3'), ('command_id', 'another'), ('producers_stopped', False)]:
        wrong = deepcopy(command)
        wrong['executions']['details']['2']['control_release'][field] = value
        assert omitted_followers([wrong], ['1']) == ['2']
