"""
Swarm trajectory service tests.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from functions.swarm_analyzer import fetch_swarm_data
from functions.swarm_session_manager import SwarmSessionManager
from functions import swarm_trajectory_processor
from functions.swarm_trajectory_service import (
    SwarmTrajectoryError,
    clear_individual_drone_payload,
    get_processing_status_payload,
    save_uploaded_trajectory,
)
from functions.swarm_trajectory_utils import get_project_root, get_swarm_trajectory_folders


def test_get_swarm_trajectory_folders_is_cwd_independent(monkeypatch, tmp_path):
    """Trajectory paths should resolve from the repo root, not the caller cwd."""
    monkeypatch.chdir(tmp_path)

    folders = get_swarm_trajectory_folders()
    expected_root = Path(get_project_root())

    assert Path(folders['base']).is_absolute()
    assert Path(folders['base']).parent == expected_root


def test_fetch_swarm_data_prefers_local_config():
    """Swarm analysis should not need a self-HTTP call when config is local."""
    local_swarm = [{'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0}]

    with patch('config.load_swarm', return_value=local_swarm):
        with patch('requests.get') as mock_get:
            result = fetch_swarm_data()

    assert result == local_swarm
    mock_get.assert_not_called()


def test_clear_individual_drone_rejects_cluster_leader():
    """Leaders must be cleared at cluster scope to avoid inconsistent outputs."""
    swarm_data = [
        {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0},
        {'hw_id': 2, 'follow': 1, 'offset_x': 1, 'offset_y': 0, 'offset_z': 0},
    ]

    with patch('functions.swarm_trajectory_service.fetch_swarm_data', return_value=swarm_data):
        try:
            clear_individual_drone_payload(1)
        except SwarmTrajectoryError as exc:
            assert exc.status_code == 400
            assert 'cluster clear action' in exc.message
        else:
            raise AssertionError('Expected leader clear to be rejected')


def test_session_manager_detects_raw_csv_content_changes(monkeypatch, tmp_path):
    """Changing a raw leader CSV must force a fresh reprocess recommendation."""
    folders = {
        'base': str(tmp_path),
        'raw': str(tmp_path / 'raw'),
        'processed': str(tmp_path / 'processed'),
        'plots': str(tmp_path / 'plots'),
    }
    for directory in folders.values():
        Path(directory).mkdir(parents=True, exist_ok=True)

    swarm_data = [
        {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        {'hw_id': 2, 'follow': 1, 'offset_x': 1, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
    ]

    monkeypatch.setattr('functions.swarm_session_manager.get_swarm_trajectory_folders', lambda: folders)
    monkeypatch.setattr('functions.swarm_session_manager.fetch_swarm_data', lambda: swarm_data)

    manager = SwarmSessionManager()
    raw_file = Path(folders['raw']) / 'Drone 1.csv'
    raw_file.write_text('version-a', encoding='utf-8')
    manager.create_processing_session([1], total_drones=2)

    raw_file.write_text('version-b', encoding='utf-8')
    changes = manager.detect_changes()

    assert changes['trajectory_files_changed'] is True
    assert changes['requires_full_reprocess'] is True
    assert changes['safe_to_incremental'] is False


def test_save_uploaded_trajectory_rejects_non_top_leader():
    """Uploads must target a current top-level leader, not an arbitrary follower."""
    structure = {
        'top_leaders': [1, 5],
        'hierarchies': {1: [2, 3], 5: [6]},
    }

    with patch('functions.swarm_trajectory_service._load_swarm_structure', return_value=structure):
        with pytest.raises(SwarmTrajectoryError) as exc_info:
            save_uploaded_trajectory(2, 'test.csv', b'a,b,c\n')

    assert exc_info.value.status_code == 400
    assert 'top-level leader' in exc_info.value.message
    assert '1, 5' in exc_info.value.message


def test_processing_status_reports_truthful_cluster_readiness(monkeypatch, tmp_path):
    """Status payload must reflect real per-cluster upload/processed state."""
    folders = {
        'base': str(tmp_path),
        'raw': str(tmp_path / 'raw'),
        'processed': str(tmp_path / 'processed'),
        'plots': str(tmp_path / 'plots'),
    }
    for directory in folders.values():
        Path(directory).mkdir(parents=True, exist_ok=True)

    (Path(folders['raw']) / 'Drone 1.csv').write_text('raw', encoding='utf-8')
    (Path(folders['processed']) / 'Drone 1.csv').write_text('processed', encoding='utf-8')
    (Path(folders['processed']) / 'Drone 2.csv').write_text('processed', encoding='utf-8')

    structure = {
        'top_leaders': [1, 5],
        'hierarchies': {1: [2, 3], 5: [6]},
    }

    monkeypatch.setattr('functions.swarm_trajectory_service.get_swarm_trajectory_folders', lambda: folders)
    monkeypatch.setattr('functions.swarm_trajectory_service._load_swarm_structure', lambda: structure)

    payload = get_processing_status_payload()
    status = payload['status']

    assert status['processed_trajectories'] == 2
    assert status['has_results'] is True
    assert status['plots_available'] is False

    clusters = {cluster['leader_id']: cluster for cluster in status['clusters']}
    assert clusters[1]['leader_uploaded'] is True
    assert clusters[1]['leader_processed'] is True
    assert clusters[1]['processed_follower_ids'] == [2]
    assert clusters[1]['missing_follower_ids'] == [3]
    assert clusters[1]['ready'] is False

    assert clusters[5]['leader_uploaded'] is False
    assert clusters[5]['leader_processed'] is False
    assert clusters[5]['missing_follower_ids'] == [6]
    assert clusters[5]['ready'] is False


def test_process_swarm_trajectories_reports_auto_reloaded_leaders(monkeypatch):
    """Auto-reloaded leader IDs should survive through to the returned payload."""

    class FakeSessionManager:
        def get_processing_recommendation(self):
            return {'action': 'safe_incremental'}

        def get_uploaded_leaders(self):
            return [1]

    monkeypatch.setattr(swarm_trajectory_processor, 'SwarmSessionManager', FakeSessionManager)
    monkeypatch.setattr(swarm_trajectory_processor, 'auto_reload_missing_leaders', lambda uploaded: [5])

    def fake_execute(available_leaders, session_manager, recommendation, reloaded_leaders=None):
        return {
            'success': True,
            'available_leaders': available_leaders,
            'auto_reloaded': reloaded_leaders,
        }

    monkeypatch.setattr(swarm_trajectory_processor, '_execute_trajectory_processing', fake_execute)

    result = swarm_trajectory_processor.process_swarm_trajectories(force_clear=False, auto_reload=True)

    assert result['success'] is True
    assert result['available_leaders'] == [1, 5]
    assert result['auto_reloaded'] == [5]
