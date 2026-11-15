from types import SimpleNamespace
from unittest.mock import Mock

from src.drone_communicator import DroneCommunicator
from src.swarm_state_cache import SwarmAssignmentCache


def test_installed_assignment_is_immutable_detached_and_content_revisioned():
    initial = {"follow": 1, "metadata": {"name": "first"}}
    cache = SwarmAssignmentCache(initial)
    initial["metadata"]["name"] = "changed"
    returned = cache.snapshot()
    returned["metadata"]["name"] = "reader"
    assert cache.snapshot()["metadata"]["name"] == "first"
    assert not cache.install_saved({"metadata": {"name": "first"}, "follow": 1})
    assert cache.saved_revision == 0
    assert cache.install_saved({"follow": 2})
    assert cache.snapshot() == {"follow": 2}
    assert cache.saved_revision == 1


def test_runtime_cache_expires_independently_and_reveals_latest_saved_revision():
    now = [10.0]
    cache = SwarmAssignmentCache({"follow": 1}, clock=lambda: now[0])
    cache.install_runtime({"follow": 2, "active": True})
    cache.install_saved({"follow": 3})
    assert cache.snapshot()["follow"] == 2
    now[0] = 11.01
    assert cache.snapshot() == {"follow": 3}
    cache.install_runtime({"follow": 4, "active": True})
    cache.install_runtime(None)
    assert cache.snapshot() == {"follow": 3}


def test_hot_assignment_reads_do_not_read_files_or_network_and_refresh_is_visible(monkeypatch):
    monkeypatch.setattr('src.drone_communicator.read_runtime_swarm_assignment', lambda **_: None)
    read = Mock(return_value={"hw_id": 3, "follow": 1})
    config = SimpleNamespace(hw_id=3, swarm={"follow": 0}, read_swarm=read)
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False,
                             offline_swarm=True, swarm_url=None)
    communicator = DroneCommunicator(config, params, {})
    assert read.call_count == 1
    for _ in range(50):
        assert communicator._get_live_swarm_assignment()["follow"] == 1
    assert read.call_count == 1
    read.return_value = {"hw_id": 3, "follow": 2}
    communicator._refresh_saved_swarm_assignment()
    assert communicator._get_live_swarm_assignment()["follow"] == 2
    read.side_effect = OSError("missing desired state")
    communicator._refresh_saved_swarm_assignment()
    assert communicator._get_live_swarm_assignment()["follow"] == 2


def test_online_assignment_acquisition_is_bounded_worker_only_and_never_blocks_runtime(monkeypatch):
    runtime = [None]
    monkeypatch.setattr('src.drone_communicator.read_runtime_swarm_assignment', lambda **_: runtime[0])
    config = SimpleNamespace(hw_id=3, swarm={"hw_id": 3, "follow": 0}, read_swarm=Mock())
    params = SimpleNamespace(enable_udp_telemetry=False, enable_default_subscriptions=False,
                             offline_swarm=False, swarm_url="http://configured/swarm")
    client = Mock()
    client.get.return_value.json.return_value = {"assignments": [{"hw_id": 3, "follow": 1}]}
    communicator = DroneCommunicator(config, params, {})
    config.read_swarm.assert_not_called()
    assert communicator._get_live_swarm_assignment()["follow"] == 0
    communicator._refresh_saved_swarm_assignment(session=client)
    client.get.assert_called_once_with(params.swarm_url, timeout=(0.5, 1.5))
    assert communicator._get_live_swarm_assignment()["follow"] == 1
    runtime[0] = {"hw_id": 3, "follow": 2, "active": True}
    communicator._refresh_runtime_swarm_assignment()
    client.get.side_effect = TimeoutError("unavailable")
    communicator._refresh_saved_swarm_assignment(session=client)
    assert communicator._get_live_swarm_assignment()["follow"] == 2
    runtime[0] = None
    communicator._refresh_runtime_swarm_assignment()
    assert communicator._get_live_swarm_assignment()["follow"] == 1
