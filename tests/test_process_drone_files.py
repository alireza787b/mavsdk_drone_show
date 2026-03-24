import pandas as pd
import pytest

from functions.process_drone_files import process_drone_files


def _write_skybrush_csv(path):
    df = pd.DataFrame(
        {
            'Time [msec]': [0, 500, 1000],
            'x [m]': [0.0, 1.0, 2.0],
            'y [m]': [0.0, -0.5, -1.0],
            'z [m]': [0.0, 1.0, 2.0],
            'Red': [255, 255, 0],
            'Green': [0, 128, 255],
            'Blue': [0, 0, 255],
        }
    )
    df.to_csv(path, index=False)


def test_process_drone_files_short_trajectory_includes_final_timestamp(tmp_path):
    skybrush_dir = tmp_path / 'skybrush'
    processed_dir = tmp_path / 'processed'
    skybrush_dir.mkdir()
    processed_dir.mkdir()

    _write_skybrush_csv(skybrush_dir / 'Drone 1.csv')

    outputs = process_drone_files(str(skybrush_dir), str(processed_dir), method='cubic', dt=0.5)

    assert len(outputs) == 1

    processed = pd.read_csv(outputs[0])
    assert processed['t'].iloc[-1] == pytest.approx(1.0)
    assert {'px', 'py', 'pz', 'vx', 'vy', 'vz'}.issubset(processed.columns)


def test_process_drone_files_reads_nested_csvs(tmp_path):
    skybrush_dir = tmp_path / 'skybrush'
    nested_dir = skybrush_dir / 'nested'
    processed_dir = tmp_path / 'processed'
    nested_dir.mkdir(parents=True)
    processed_dir.mkdir()

    _write_skybrush_csv(nested_dir / 'Drone 2.csv')

    outputs = process_drone_files(str(skybrush_dir), str(processed_dir), method='linear', dt=0.5)

    assert len(outputs) == 1
    assert (processed_dir / 'Drone 2.csv').exists()
