import json

import origin


def test_load_origin_uses_packaged_sitl_default_when_runtime_missing(tmp_path, monkeypatch):
    runtime_origin = tmp_path / 'origin.json'
    default_origin = tmp_path / 'origin.sitl.default.json'
    default_origin.write_text(
        json.dumps(
            {
                'lat': 35.1,
                'lon': 51.2,
                'alt': 1278.0,
                'alt_source': 'sitl_default',
                'version': 2,
            }
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(origin, 'origin_file_path', str(runtime_origin))
    monkeypatch.setattr(origin, 'sitl_default_origin_file_path', str(default_origin))
    monkeypatch.setattr(origin.Params, 'sim_mode', True, raising=False)

    loaded = origin.load_origin()

    assert loaded['lat'] == 35.1
    assert loaded['lon'] == 51.2
    assert loaded['alt'] == 1278.0
    assert loaded['alt_source'] == 'sitl_default'
    assert not runtime_origin.exists()


def test_load_origin_prefers_runtime_origin_over_packaged_default(tmp_path, monkeypatch):
    runtime_origin = tmp_path / 'origin.json'
    default_origin = tmp_path / 'origin.sitl.default.json'

    runtime_origin.write_text(
        json.dumps(
            {
                'lat': 36.0,
                'lon': 52.0,
                'alt': 1300.0,
                'alt_source': 'manual',
                'timestamp': '2026-03-26T00:00:00',
                'version': 2,
            }
        ),
        encoding='utf-8',
    )
    default_origin.write_text(
        json.dumps({'lat': 35.1, 'lon': 51.2, 'alt': 1278.0, 'version': 2}),
        encoding='utf-8',
    )

    monkeypatch.setattr(origin, 'origin_file_path', str(runtime_origin))
    monkeypatch.setattr(origin, 'sitl_default_origin_file_path', str(default_origin))
    monkeypatch.setattr(origin.Params, 'sim_mode', True, raising=False)

    loaded = origin.load_origin()

    assert loaded['lat'] == 36.0
    assert loaded['lon'] == 52.0
    assert loaded['alt'] == 1300.0
    assert loaded['alt_source'] == 'manual'
    assert loaded['timestamp'] == '2026-03-26T00:00:00'
