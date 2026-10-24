from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.validate_swarm_design_apply import apply_revision, verify_selected_resource


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
