import pytest
from pydantic import ValidationError

from src.command_contract import CommandPayloadRequest
from src.swarm_trajectory_contract import SwarmTrajectoryPackage
from src.swarm_trajectory_contract import verify_local_package


@pytest.mark.parametrize('identity,digest', [('0', 'a' * 64), ('01', 'a' * 64),
                                           ('../1', 'a' * 64), ('1', 'invalid'), ('1', 'A' * 64)])
def test_package_rejects_invalid_file_identity(identity, digest):
    with pytest.raises(ValidationError):
        SwarmTrajectoryPackage(revision='r1', files={identity: digest})


def test_package_contract_is_mission_specific():
    package = {'revision': 'r1', 'files': {'1': 'a' * 64}}
    assert CommandPayloadRequest(mission_type=4, swarm_trajectory=package).swarm_trajectory.files == package['files']
    with pytest.raises(ValidationError):
        CommandPayloadRequest(mission_type=10, swarm_trajectory=package)


def test_aircraft_verifies_reviewed_file_before_launch_admission(tmp_path):
    import hashlib
    route = tmp_path / 'Drone 7.csv'
    route.write_bytes(b'reviewed bytes')
    package = {'revision': 'r1', 'files': {'7': hashlib.sha256(b'reviewed bytes').hexdigest()}}
    verify_local_package(package, '7', route)
    with pytest.raises(ValueError, match='missing from'):
        verify_local_package(package, '8', route)
    route.write_bytes(b'changed bytes')
    with pytest.raises(ValueError, match='differs'):
        verify_local_package(package, '7', route)
    route.unlink()
    with pytest.raises(ValueError, match='unavailable'):
        verify_local_package(package, '7', route)
