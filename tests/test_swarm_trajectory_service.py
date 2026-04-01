"""
Swarm trajectory service tests.
"""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from functions.swarm_analyzer import fetch_swarm_data
from functions.swarm_session_manager import SwarmSessionManager
from functions import swarm_trajectory_processor
from functions.swarm_trajectory_service import (
    SwarmTrajectoryError,
    clear_individual_drone_payload,
    get_processing_status_payload,
    save_uploaded_trajectory,
    validate_target_scope_for_swarm_trajectory,
)
from functions.swarm_trajectory_utils import get_project_root, get_swarm_trajectory_folders
from src.params import Params


def test_get_swarm_trajectory_folders_is_cwd_independent(monkeypatch, tmp_path):
    """Trajectory paths should resolve from the repo root, not the caller cwd."""
    monkeypatch.chdir(tmp_path)

    folders = get_swarm_trajectory_folders()
    expected_root = Path(get_project_root())

    assert Path(folders['base']).is_absolute()
    assert Path(folders['base']).parent.parent == expected_root


def test_get_swarm_trajectory_folders_prefers_shared_sitl_workspace(monkeypatch, tmp_path):
    shared_dir = tmp_path / 'shared_swarm_trajectory'
    monkeypatch.setattr(Params, 'sim_mode', True)
    monkeypatch.setattr(Params, 'SWARM_TRAJECTORY_SHARED_DIR', str(shared_dir))

    folders = get_swarm_trajectory_folders()

    assert folders == {
        'base': str(shared_dir.resolve()),
        'raw': str((shared_dir / 'raw').resolve()),
        'processed': str((shared_dir / 'processed').resolve()),
        'plots': str((shared_dir / 'plots').resolve()),
    }


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
        'swarm_config': {
            1: {'follow': 0},
            2: {'follow': 1},
            3: {'follow': 1},
            5: {'follow': 0},
            6: {'follow': 5},
        },
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
    (Path(folders['processed']) / 'Drone 1.csv').write_text(
        't,alt\n10,1450\n70,1465\n',
        encoding='utf-8',
    )
    (Path(folders['processed']) / 'Drone 2.csv').write_text(
        't,alt\n10,1455\n65,1462\n',
        encoding='utf-8',
    )

    structure = {
        'top_leaders': [1, 5],
        'hierarchies': {1: [2, 3], 5: [6]},
        'swarm_config': {
            1: {'follow': 0},
            2: {'follow': 1},
            3: {'follow': 1},
            5: {'follow': 0},
            6: {'follow': 5},
        },
    }

    monkeypatch.setattr('functions.swarm_trajectory_service.get_swarm_trajectory_folders', lambda: folders)
    monkeypatch.setattr('functions.swarm_trajectory_service._load_swarm_structure', lambda: structure)
    monkeypatch.setattr('functions.swarm_session_manager.get_swarm_trajectory_folders', lambda: folders)

    payload = get_processing_status_payload()
    status = payload['status']

    assert status['processed_trajectories'] == 2
    assert status['has_results'] is True
    assert status['plots_available'] is False
    assert status['expected_top_leaders'] == [1, 5]
    assert status['uploaded_leaders'] == [1]
    assert status['missing_uploaded_leaders'] == [5]
    assert status['orphan_uploaded_leaders'] == []
    assert status['follow_map'] == {1: 0, 2: 1, 3: 1, 5: 0, 6: 5}
    assert status['cluster_summary']['cluster_count'] == 2
    assert status['cluster_summary']['ready_cluster_count'] == 0
    assert status['cluster_summary']['partial_output_cluster_count'] == 1
    assert status['cluster_summary']['missing_upload_cluster_count'] == 1
    assert status['cluster_summary']['overall_state'] == 'partial'
    assert status['session']['exists'] is False
    assert status['session_changes']['has_previous_session'] is False
    assert status['session_changes']['requires_full_reprocess'] is True
    assert status['processing_recommendation']['action'] == 'recommended_full_reprocess'
    assert status['package_stats'] == {
        'available': True,
        'drone_count': 2,
        'drone_ids': [1, 2],
        'route_entry_time_s': 10.0,
        'mission_clock_s': 70.0,
        'route_motion_time_s': 60.0,
        'max_altitude_msl_m': 1465.0,
        'min_altitude_msl_m': 1450.0,
        'altitude_window_m': 15.0,
    }
    assert status['package_drone_stats'][1]['mission_clock_s'] == 70.0
    assert status['package_drone_stats'][2]['max_altitude_msl_m'] == 1462.0

    clusters = {cluster['leader_id']: cluster for cluster in status['clusters']}
    assert clusters[1]['leader_uploaded'] is True
    assert clusters[1]['leader_processed'] is True
    assert clusters[1]['processed_follower_ids'] == [2]
    assert clusters[1]['missing_follower_ids'] == [3]
    assert clusters[1]['ready'] is False
    assert clusters[1]['state'] == 'partial_outputs'
    assert clusters[1]['expected_drone_count'] == 3
    assert clusters[1]['processed_drone_count'] == 2
    assert clusters[1]['issues']
    assert clusters[1]['package_stats'] == {
        'available': True,
        'drone_count': 2,
        'drone_ids': [1, 2],
        'route_entry_time_s': 10.0,
        'mission_clock_s': 70.0,
        'route_motion_time_s': 60.0,
        'max_altitude_msl_m': 1465.0,
        'min_altitude_msl_m': 1450.0,
        'altitude_window_m': 15.0,
    }

    assert clusters[5]['leader_uploaded'] is False
    assert clusters[5]['leader_processed'] is False
    assert clusters[5]['missing_follower_ids'] == [6]
    assert clusters[5]['ready'] is False
    assert clusters[5]['state'] == 'missing_upload'
    assert clusters[5]['issues']
    assert clusters[5]['package_stats']['available'] is False


def test_validate_target_scope_for_swarm_trajectory_requires_processed_outputs_and_leader_chain():
    structure = {
        'swarm_config': {
            1: {'follow': 0},
            2: {'follow': 1},
            3: {'follow': 2},
            4: {'follow': 0},
        },
    }

    issues = validate_target_scope_for_swarm_trajectory(
        structure=structure,
        processed_drones=[1, 2, 4],
        target_drone_ids=[2, 3],
    )

    assert {'drone_id': 2, 'leader_id': 1, 'issue': 'leader_not_in_active_mission_set'} in issues
    assert {'drone_id': 3, 'issue': 'missing_processed_trajectory'} in issues
    assert {'drone_id': 3, 'leader_id': 2, 'issue': 'leader_not_in_active_mission_set'} not in issues


def test_validate_target_scope_for_swarm_trajectory_accepts_complete_selected_chain():
    structure = {
        'swarm_config': {
            1: {'follow': 0},
            2: {'follow': 1},
            3: {'follow': 2},
        },
    }

    issues = validate_target_scope_for_swarm_trajectory(
        structure=structure,
        processed_drones=[1, 2, 3],
        target_drone_ids=[1, 2, 3],
    )

    assert issues == []


def test_get_swarm_trajectory_file_path_prefers_shared_sitl_workspace(monkeypatch, tmp_path):
    shared_dir = tmp_path / 'shared_swarm_trajectory'
    processed_dir = shared_dir / 'processed'
    processed_dir.mkdir(parents=True)
    shared_file = processed_dir / 'Drone 7.csv'
    shared_file.write_text('t,lat,lon,alt\n0,35,51,1200\n', encoding='utf-8')

    monkeypatch.setattr(Params, 'sim_mode', True)
    monkeypatch.setattr(Params, 'SWARM_TRAJECTORY_SHARED_DIR', str(shared_dir))

    assert Params.get_swarm_trajectory_file_path(7) == str(shared_file)


def test_get_swarm_trajectory_file_path_falls_back_when_shared_file_missing(monkeypatch):
    monkeypatch.setattr(Params, 'sim_mode', True)
    monkeypatch.setattr(Params, 'SWARM_TRAJECTORY_SHARED_DIR', '/tmp/nonexistent_shared_swarm_trajectory')

    assert Params.get_swarm_trajectory_file_path(9) == 'shapes_sitl/swarm_trajectory/processed/Drone 9.csv'


def test_session_manager_recommendation_includes_expected_and_missing_leader_truth(monkeypatch, tmp_path):
    """Recommendations should expose expected/uploaded/missing leader IDs for the UI."""
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
        {'hw_id': 5, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        {'hw_id': 2, 'follow': 1, 'offset_x': 1, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
    ]

    monkeypatch.setattr('functions.swarm_session_manager.get_swarm_trajectory_folders', lambda: folders)
    monkeypatch.setattr('functions.swarm_session_manager.fetch_swarm_data', lambda: swarm_data)

    raw_file = Path(folders['raw']) / 'Drone 1.csv'
    raw_file.write_text('leader-1', encoding='utf-8')

    manager = SwarmSessionManager()
    recommendation = manager.get_processing_recommendation()

    assert recommendation['expected_top_leaders'] == [1, 5]
    assert recommendation['uploaded_leaders'] == [1]
    assert recommendation['missing_uploaded_leaders'] == [5]
    assert recommendation['orphan_uploaded_leaders'] == []
    assert recommendation['action'] == 'recommended_full_reprocess'


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


def test_execute_trajectory_processing_marks_partial_when_swarm_outputs_are_incomplete(monkeypatch, tmp_path):
    """Processing should report partial outcome when expected drones are not fully generated."""

    folders = {
        'base': str(tmp_path),
        'raw': str(tmp_path / 'raw'),
        'processed': str(tmp_path / 'processed'),
        'plots': str(tmp_path / 'plots'),
    }
    for directory in folders.values():
        Path(directory).mkdir(parents=True, exist_ok=True)

    swarm_structure = {
        'top_leaders': [1, 5],
        'hierarchies': {1: [2], 5: [6]},
    }

    swarm_rows = [
        {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        {'hw_id': 2, 'follow': 1, 'offset_x': 1, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        {'hw_id': 5, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        {'hw_id': 6, 'follow': 5, 'offset_x': 1, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
    ]

    class FakeSessionManager:
        def create_processing_session(self, processed_leaders, total_drones):
            return type('Session', (), {'session_id': 'sess-1'})()

    trajectory_df = pd.DataFrame([{
        't': 0.0,
        'lat': 35.0,
        'lon': 51.0,
        'alt': 1200.0,
        'vx': 0.0,
        'vy': 0.0,
        'vz': 0.0,
        'ax': 0.0,
        'ay': 0.0,
        'az': 0.0,
        'yaw': 0.0,
        'mode': 70,
        'ledr': 255,
        'ledg': 0,
        'ledb': 0,
    }])

    monkeypatch.setattr(swarm_trajectory_processor, 'get_swarm_trajectory_folders', lambda: folders)
    monkeypatch.setattr(swarm_trajectory_processor, 'ensure_directory_exists', lambda directory: None)
    monkeypatch.setattr(swarm_trajectory_processor, 'analyze_swarm_structure', lambda: swarm_structure)
    monkeypatch.setattr(swarm_trajectory_processor, 'load_leader_trajectories', lambda raw_dir, valid_leaders: {1: pd.DataFrame([{
        'Name': 'WP1',
        'Latitude': 35.0,
        'Longitude': 51.0,
        'Altitude_MSL_m': 1200.0,
        'TimeFromStart_s': 0.0,
        'EstimatedSpeed_ms': 5.0,
        'Heading_deg': 0.0,
        'HeadingMode': 'auto',
    }])})
    monkeypatch.setattr(swarm_trajectory_processor, 'fetch_swarm_data', lambda: swarm_rows)
    monkeypatch.setattr(swarm_trajectory_processor, 'smooth_trajectory_with_waypoints', lambda waypoints_df: trajectory_df.copy())
    monkeypatch.setattr(swarm_trajectory_processor, 'calculate_follower_trajectory', lambda leader_trajectory, drone_config: trajectory_df.copy())
    monkeypatch.setattr(swarm_trajectory_processor, 'save_drone_trajectory', lambda hw_id, trajectory, processed_dir: None)
    monkeypatch.setattr(swarm_trajectory_processor, 'generate_swarm_plots', lambda all_trajectories, structure, plots_dir: None)

    result = swarm_trajectory_processor._execute_trajectory_processing(
        available_leaders=[1],
        session_manager=FakeSessionManager(),
        recommendation={'action': 'safe_incremental'},
        reloaded_leaders=[],
    )

    assert result['success'] is True
    assert result['outcome'] == 'partial'
    assert result['processed_drone_list'] == [1, 2]
    assert result['expected_drone_list'] == [1, 2, 5, 6]
    assert result['skipped_drone_ids'] == [5, 6]
    assert result['missing_leaders'] == [5]
    assert 'Some clusters still need attention before launch' in result['message']
