from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.validate_swarm_design_apply import apply_revision, verify_selected_resource, require_local_sitl_leader


def test_rehearsal_refuses_extra_aircraft_in_formation():
    with pytest.raises(RuntimeError, match='exactly the two'):
        verify_selected_resource({'assignments': [{'hw_id': 1}, {'hw_id': 2}, {'hw_id': 3}]}, [1, 2])


def test_rehearsal_rechecks_sitl_before_any_configuration_write():
    client = SimpleNamespace(require_sitl_runtime=Mock(side_effect=RuntimeError('REAL mode')),
                             get_swarm_resource=Mock(), put_swarm_resource=Mock())
    with pytest.raises(RuntimeError, match='REAL mode'):
        apply_revision(client, [], [1, 2], set())
    client.get_swarm_resource.assert_not_called()
    client.put_swarm_resource.assert_not_called()


def test_outage_rehearsal_refuses_real_runtime_before_docker(monkeypatch):
    run = Mock()
    monkeypatch.setattr('tools.validate_swarm_design_apply.subprocess.run', run)
    client = SimpleNamespace(require_sitl_runtime=Mock(side_effect=RuntimeError('REAL mode')))
    with pytest.raises(RuntimeError, match='REAL mode'):
        require_local_sitl_leader(client, 1)
    run.assert_not_called()


@pytest.mark.parametrize('base_url,port,allowed', [
    ('http://172.18.0.1:5031', '5031', True),
    ('http://remote.example:5031', '5031', False),
    ('http://172.18.0.1:5031', '5030', False),
])
def test_outage_rehearsal_checks_local_identity_and_callback_route(monkeypatch, base_url, port, allowed):
    import json
    data = [{'Config': {'Env': ['MDS_MODE=sitl', 'MDS_HW_ID=1', f'MDS_GCS_API_PORT={port}']},
             'NetworkSettings': {'Networks': {'lab': {'IPAddress': '172.18.0.2', 'Gateway': '172.18.0.1'}}}}]
    monkeypatch.setattr('tools.validate_swarm_design_apply.subprocess.run',
                        Mock(return_value=SimpleNamespace(stdout=json.dumps(data))))
    client = SimpleNamespace(base_url=base_url,
        require_sitl_runtime=Mock(return_value={'gcs_port': 5031}),
        get_json=Mock(return_value=[{'hw_id': 1, 'ip': '172.18.0.2'}]))
    if allowed:
        require_local_sitl_leader(client, 1)
    else:
        with pytest.raises(RuntimeError):
            require_local_sitl_leader(client, 1)
