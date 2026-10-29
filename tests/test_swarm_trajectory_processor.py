import navpy
import pandas as pd
import pytest

from functions import swarm_trajectory_processor


def _leader_waypoints():
    return pd.DataFrame({
        'Name': ['WP1', 'WP2', 'WP3'],
        'Latitude': [35.0, 35.0001, 35.0002],
        'Longitude': [51.0, 51.0001, 51.0002],
        'Altitude_MSL_m': [1200.0, 1205.0, 1205.0],
        'TimeFromStart_s': [0.0, 10.0, 20.0],
        'EstimatedSpeed_ms': [0.0, 2.0, 2.0],
        'Heading_deg': [0.0, 45.0, 45.0],
        'HeadingMode': ['manual', 'auto', 'auto'],
    })


@pytest.mark.parametrize('column', swarm_trajectory_processor.LEADER_TRAJECTORY_NUMERIC_COLUMNS)
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), 'invalid', ''])
def test_leader_validation_rejects_nonfinite_or_missing_numeric_values(column, value):
    waypoints = _leader_waypoints()
    waypoints[column] = waypoints[column].astype(object)
    waypoints.loc[1, column] = value

    with pytest.raises(ValueError, match=f'Leader 7 CSV has invalid numeric values in:.*{column}'):
        swarm_trajectory_processor.validate_leader_trajectory_dataframe(waypoints, leader_id=7)


@pytest.mark.parametrize('timestamps', [[0.0, 0.0, 20.0], [0.0, 10.0, 10.0], [0.0, 20.0, 10.0]])
def test_leader_validation_requires_strictly_increasing_time(timestamps):
    waypoints = _leader_waypoints()
    waypoints['TimeFromStart_s'] = timestamps

    with pytest.raises(ValueError, match='TimeFromStart_s must be strictly increasing'):
        swarm_trajectory_processor.validate_leader_trajectory_dataframe(waypoints)


def test_leader_validation_rejects_negative_time():
    waypoints = _leader_waypoints()
    waypoints['TimeFromStart_s'] = [-1.0, 10.0, 20.0]

    with pytest.raises(ValueError, match='TimeFromStart_s must be nonnegative'):
        swarm_trajectory_processor.validate_leader_trajectory_dataframe(waypoints)


@pytest.mark.parametrize('start_time', [0.0, 5.0])
def test_leader_validation_preserves_metadata_and_does_not_mutate_input(start_time):
    waypoints = _leader_waypoints()
    waypoints['TimeFromStart_s'] = [str(start_time + offset) for offset in (0.0, 10.0, 20.0)]
    waypoints['AltitudeReference'] = ['MSL', 'AGL', 'AGL']
    waypoints['TargetAgl_m'] = [None, 25.0, 25.0]
    waypoints['TimingMode'] = ['manual_time', 'auto_speed', 'manual_time']
    waypoints['OperatorNote'] = ['launch', '', 'end']
    original = waypoints.copy(deep=True)

    result = swarm_trajectory_processor.validate_leader_trajectory_dataframe(waypoints)

    pd.testing.assert_frame_equal(waypoints, original)
    assert result['TimeFromStart_s'].tolist() == [start_time, start_time + 10.0, start_time + 20.0]
    metadata = ['Name', 'HeadingMode', 'AltitudeReference', 'TargetAgl_m', 'TimingMode', 'OperatorNote']
    pd.testing.assert_frame_equal(result[metadata], original[metadata])


def _leader_relative_ned(follower_trajectory, leader_trajectory):
    follower_row = follower_trajectory.iloc[0]
    leader_row = leader_trajectory.iloc[0]
    return navpy.lla2ned(
        follower_row['lat'],
        follower_row['lon'],
        follower_row['alt'],
        leader_row['lat'],
        leader_row['lon'],
        leader_row['alt'],
        latlon_unit='deg',
        alt_unit='m',
        model='wgs84',
    )


def test_execute_processing_compounds_nested_follow_offsets(monkeypatch, tmp_path):
    folders = {
        'raw': str(tmp_path / 'raw'),
        'processed': str(tmp_path / 'processed'),
        'plots': str(tmp_path / 'plots'),
    }
    swarm_structure = {
        'top_leaders': [1],
        'hierarchies': {1: [2, 3]},
    }
    swarm_rows = [
        {'hw_id': 3, 'follow': 2, 'offset_x': 5, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        {'hw_id': 2, 'follow': 1, 'offset_x': 10, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
    ]

    saved = {}
    leader_trajectory = pd.DataFrame([{
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
    uploaded_waypoints = pd.DataFrame([{
        'Name': 'WP1',
        'Latitude': 35.0,
        'Longitude': 51.0,
        'Altitude_MSL_m': 1200.0,
        'TimeFromStart_s': 0.0,
        'EstimatedSpeed_ms': 5.0,
        'Heading_deg': 0.0,
        'HeadingMode': 'auto',
    }])

    class FakeSessionManager:
        def input_identity(self):
            return {}

        def create_processing_session(self, processed_leaders, total_drones, expected_inputs=None):
            return type('Session', (), {'session_id': 'sess-processor'})()

    monkeypatch.setattr(swarm_trajectory_processor, 'get_swarm_trajectory_folders', lambda: folders)
    monkeypatch.setattr(swarm_trajectory_processor, 'ensure_directory_exists', lambda directory: None)
    monkeypatch.setattr(swarm_trajectory_processor, 'analyze_swarm_structure', lambda rows: swarm_structure)
    monkeypatch.setattr(swarm_trajectory_processor, 'load_leader_trajectories', lambda raw_dir, valid_leaders: {1: uploaded_waypoints.copy()})
    monkeypatch.setattr(swarm_trajectory_processor, 'fetch_swarm_data', lambda: swarm_rows)
    monkeypatch.setattr(swarm_trajectory_processor, 'smooth_trajectory_with_waypoints', lambda waypoints_df: leader_trajectory.copy())
    monkeypatch.setattr(swarm_trajectory_processor, 'save_drone_trajectory', lambda hw_id, trajectory, processed_dir: saved.setdefault(hw_id, trajectory.copy()))
    monkeypatch.setattr(swarm_trajectory_processor, 'generate_swarm_plots', lambda all_trajectories, structure, plots_dir: None)

    result = swarm_trajectory_processor._execute_trajectory_processing(
        available_leaders=[1],
        session_manager=FakeSessionManager(),
        recommendation={'action': 'safe_incremental'},
        reloaded_leaders=[],
    )

    assert result['success'] is True
    assert result['processed_drone_list'] == [1, 2, 3]

    north_2, east_2, down_2 = _leader_relative_ned(saved[2], saved[1])
    north_3, east_3, down_3 = _leader_relative_ned(saved[3], saved[1])

    assert north_2 == pytest.approx(10.0, abs=0.05)
    assert east_2 == pytest.approx(0.0, abs=0.05)
    assert down_2 == pytest.approx(0.0, abs=0.05)
    assert north_3 == pytest.approx(15.0, abs=0.05)
    assert east_3 == pytest.approx(0.0, abs=0.05)
    assert down_3 == pytest.approx(0.0, abs=0.05)


def test_analyze_swarm_structure_rejects_circular_follow_chains():
    swarm_data = [
        {'hw_id': 1, 'follow': 2, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0},
        {'hw_id': 2, 'follow': 1, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0},
    ]

    with pytest.raises(ValueError, match='Circular dependency detected'):
        swarm_trajectory_processor.analyze_swarm_structure(swarm_data)
