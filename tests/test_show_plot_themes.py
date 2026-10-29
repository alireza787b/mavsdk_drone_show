import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from functions.plot_drone_paths import plot_drone_paths

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gcs-server'))
from show_management import list_show_plots_payload, validation_from_metrics


def test_generated_plot_variants_and_manifest(tmp_path):
    processed, plots = tmp_path / 'processed', tmp_path / 'plots'
    processed.mkdir()
    for drone_id, offset in ((1, 0), (2, 6)):
        pd.DataFrame({'px': [offset, offset + 1, offset + 2],
                      'py': [0, 1, 2], 'pz': [0, -2, -1]}).to_csv(
                          processed / f'Drone {drone_id}.csv', index=False)
    plot_drone_paths(str(tmp_path), processed_dir=str(processed), plots_dir=str(plots))
    manifest = list_show_plots_payload(str(plots))
    assert len(manifest['filenames']) == 3
    assert len(list(plots.glob('*.jpg'))) == 6
    assert manifest['revision'] != '0'
    for name in manifest['filenames']:
        assert not name.endswith('_dark.jpg')
        pair = manifest['variants'][name]
        light = np.asarray(Image.open(plots / pair['light']))
        dark = np.asarray(Image.open(plots / pair['dark']))
        assert light.shape == dark.shape
        assert light[5, 5].mean() > 230
        assert dark[5, 5].mean() < 50


def test_legacy_plots_keep_light_only_manifest(tmp_path):
    (tmp_path / 'combined_drone_paths.jpg').write_bytes(b'legacy')
    manifest = list_show_plots_payload(str(tmp_path))
    assert manifest['filenames'] == ['combined_drone_paths.jpg']
    assert manifest['variants']['combined_drone_paths.jpg'] == {'light': 'combined_drone_paths.jpg'}


@pytest.mark.parametrize('count', [1, 2, 50])
def test_normal_zero_launch_landing_produces_no_warning(count):
    from functions.drone_show_metrics import DroneShowMetrics
    engine = DroneShowMetrics('.')
    engine.drone_data = {str(i): pd.DataFrame({'t': [0, 1, 2, 3, 4],
        'px': [i * 5] * 5, 'py': [0] * 5, 'pz': [0, -.5, -10, -.5, 0],
        'mode': [70] * 5}) for i in range(count)}
    safety = engine.calculate_safety_metrics()
    report = validation_from_metrics({'safety_metrics': safety})
    assert safety['min_ground_clearance_m'] == 0
    assert report['validation_status'] == 'PASS'
    assert report['findings'] == []
    assert report['issues'] == []


def test_explicit_unsafe_or_unexplained_cautions_still_block():
    for fields in ({'collision_warnings_count': 1, 'min_ground_clearance_m': 0},
                   {'collision_warnings_count': 0, 'min_ground_clearance_m': -1},
                   {'collision_warnings_count': 0}):
        report = validation_from_metrics({'safety_metrics': {'safety_status': 'CAUTION', **fields}})
        assert report['validation_status'] == 'FAIL'


def test_single_aircraft_has_valid_safety_without_fabricated_pair():
    from functions.drone_show_metrics import DroneShowMetrics
    engine = DroneShowMetrics('.')
    engine.drone_data = {'1': pd.DataFrame({'t': [0, 1, 2], 'px': [0, 0, 0], 'py': [0, 0, 0], 'pz': [0, -2, -1]})}
    safety = engine.calculate_safety_metrics()
    assert safety['min_distance_details'] is None
    assert safety['collision_warnings_count'] == 0
    assert validation_from_metrics({'safety_metrics': safety})['validation_status'] == 'PASS'


def test_exact_aircraft_overlap_remains_a_real_blocker():
    from functions.drone_show_metrics import DroneShowMetrics
    engine = DroneShowMetrics('.')
    engine.drone_data = {
        '1': pd.DataFrame({'t': [0, 1, 2], 'px': [0, 0, 0], 'py': [0, 0, 0], 'pz': [0, -10, 0]}),
        '2': pd.DataFrame({'t': [0, 1, 2], 'px': [5, 0, 5], 'py': [0, 0, 0], 'pz': [0, -10, 0]}),
    }
    report = validation_from_metrics({'safety_metrics': engine.calculate_safety_metrics()})
    assert report['validation_status'] == 'FAIL'
    assert len(report['findings']) == 1
    finding = report['findings'][0]
    assert finding['threshold_m'] == 2
    assert finding['evidence'] == {'time_s': 1.0, 'drone_1': '1', 'drone_2': '2', 'distance_m': 0.0}


def test_show_origin_is_not_terrain():
    from functions.drone_show_metrics import DroneShowMetrics
    engine = DroneShowMetrics('.')
    engine.drone_data = {'1': pd.DataFrame({'t': [0, 1, 2], 'px': [0, 0, 0], 'py': [0, 0, 0], 'pz': [0, -10, 5]})}
    report = validation_from_metrics({'safety_metrics': engine.calculate_safety_metrics()})
    assert report['validation_status'] == 'PASS'


@pytest.mark.parametrize('problem', ['nan', 'missing', 'time'])
def test_invalid_or_unaligned_evidence_is_not_cleared(problem):
    from functions.drone_show_metrics import DroneShowMetrics
    engine = DroneShowMetrics('.')
    frame = pd.DataFrame({'t': [0, 1], 'px': [0, 0], 'py': [0, 0], 'pz': [0, -10]})
    second = frame.copy()
    if problem == 'nan':
        second.loc[1, 'pz'] = np.nan
    elif problem == 'missing':
        second = second.drop(columns=['pz'])
    else:
        second.loc[1, 't'] = 2
    engine.drone_data = {'1': frame, '2': second}
    report = validation_from_metrics({'safety_metrics': engine.calculate_safety_metrics()})
    assert report['validation_status'] == 'FAIL'
    assert 'P2:' in report['findings'][0]['detail']


@pytest.mark.parametrize('value', [None, {}])
def test_unavailable_safety_analysis_is_unknown_not_a_pass(value):
    assert validation_from_metrics({'safety_metrics': value})['validation_status'] == 'UNKNOWN'
