from src.drone_communicator import DroneCommunicator
from src.swarm_runtime_state import write_runtime_swarm_assignment


class DummyDroneConfig:
    def __init__(self):
        self.hw_id = 3
        self._swarm = {
            "hw_id": 3,
            "follow": 1,
            "offset_x": 25.0,
            "offset_y": 0.0,
            "offset_z": 15.0,
            "frame": "body",
        }
        self.config = {"mavlink_port": 14540}

    @property
    def swarm(self):
        return dict(self._swarm)

    def read_swarm(self):
        return dict(self._swarm)


class DummyParams:
    enable_udp_telemetry = False
    enable_default_subscriptions = False


def test_drone_communicator_prefers_runtime_swarm_assignment(monkeypatch, tmp_path):
    path = tmp_path / "smart_swarm_assignment.json"
    monkeypatch.setenv("MDS_SWARM_RUNTIME_ASSIGNMENT_PATH", str(path))

    write_runtime_swarm_assignment(
        {
            "hw_id": 3,
            "follow": 2,
            "offset_x": 8.0,
            "offset_y": 6.0,
            "offset_z": 0.0,
            "frame": "body",
            "active": True,
            "session_id": "live-session",
        }
    )

    drone_config = DummyDroneConfig()
    communicator = DroneCommunicator(drone_config, DummyParams(), {})

    live_assignment = communicator._get_live_swarm_assignment()

    assert live_assignment["follow"] == 2


def test_inactive_runtime_assignment_does_not_resurrect_previous_follow_mode(monkeypatch, tmp_path):
    monkeypatch.setenv('MDS_SWARM_RUNTIME_ASSIGNMENT_PATH', str(tmp_path / 'assignment.json'))
    write_runtime_swarm_assignment({'hw_id': 3, 'follow': 2, 'active': False, 'session_id': 'ended'})
    communicator = DroneCommunicator(DummyDroneConfig(), DummyParams(), {})
    assert communicator._get_live_swarm_assignment()['follow'] == 1
