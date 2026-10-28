import sys
from pathlib import Path

import numpy as np
import pandas as pd
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


def test_ground_level_caution_is_actionable_not_unexplained_failure():
    report = validation_from_metrics({'safety_metrics': {'safety_status': 'CAUTION',
        'collision_warnings_count': 0, 'min_ground_clearance_m': 0}})
    assert report['validation_status'] == 'WARNING'
    assert 'launch/landing' in report['issues'][0]
    assert report['findings'][0]['severity'] == 'warning'


def test_collision_negative_clearance_and_unknown_cautions_still_block():
    for fields in ({'collision_warnings_count': 1, 'min_ground_clearance_m': 0},
                   {'collision_warnings_count': 0, 'min_ground_clearance_m': -1},
                   {'collision_warnings_count': 0}):
        report = validation_from_metrics({'safety_metrics': {'safety_status': 'CAUTION', **fields}})
        assert report['validation_status'] == 'FAIL'


def test_single_aircraft_has_valid_safety_without_fabricated_pair():
    from functions.drone_show_metrics import DroneShowMetrics
    engine = DroneShowMetrics('.')
    engine.drone_data = {'1': pd.DataFrame({'pz': [0, -2, -1]})}
    safety = engine.calculate_safety_metrics()
    assert safety['min_distance_details'] is None
    assert safety['collision_warnings_count'] == 0
    assert validation_from_metrics({'safety_metrics': safety})['validation_status'] == 'WARNING'
