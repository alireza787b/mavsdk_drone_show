import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ('config_name', 'show_dir'),
    [
        ('config.json', 'shapes/swarm'),
        ('config_sitl.json', 'shapes_sitl/swarm'),
    ],
)
def test_packaged_drone_show_assets_match_config(config_name, show_dir):
    config_path = PROJECT_ROOT / config_name
    show_root = PROJECT_ROOT / show_dir

    config = json.loads(config_path.read_text(encoding='utf-8'))
    expected_pos_ids = sorted(int(drone['pos_id']) for drone in config['drones'])

    expected_csv_names = {f'Drone {pos_id}.csv' for pos_id in expected_pos_ids}
    expected_plot_names = {f'drone_{pos_id}_path.jpg' for pos_id in expected_pos_ids}
    expected_plot_names.add('combined_drone_paths.jpg')

    skybrush_names = {path.name for path in (show_root / 'skybrush').glob('Drone *.csv')}
    processed_names = {path.name for path in (show_root / 'processed').glob('Drone *.csv')}
    plot_names = {path.name for path in (show_root / 'plots').glob('*.jpg')}

    metrics = json.loads((show_root / 'comprehensive_metrics.json').read_text(encoding='utf-8'))

    assert skybrush_names == expected_csv_names
    assert processed_names == expected_csv_names
    assert plot_names == expected_plot_names
    assert metrics.get('basic_metrics', {}).get('drone_count') == len(expected_pos_ids)
