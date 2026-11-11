"""Custom preview regeneration is image-only; both themes preserve path colors."""
import hashlib
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from api_routes.show_management import create_show_management_router
from show_management import (
    build_custom_show_info_payload, custom_show_preview_path, generate_custom_show_preview,
    import_custom_show_csv, inspect_custom_show_csv, refresh_custom_show_preview,
)

CSV = b't,px,py,pz,vx,vy,vz,ax,ay,az,yaw,mode\n0,0,0,0,0,0,0,0,0,0,0,70\n1,2,1,-5,0,0,0,0,0,0,0,70\n'

def test_import_and_refresh_preserve_source_and_generate_both_themes(tmp_path):
    result = import_custom_show_csv(base_dir=str(tmp_path), shapes_dir=str(tmp_path / 'shapes'),
        filename='example.csv', content=CSV, git_auto_push=False,
        inspect_custom_show_csv_func=inspect_custom_show_csv,
        generate_custom_show_preview_func=generate_custom_show_preview, git_operations_func=lambda *args: {})
    shapes = tmp_path / 'shapes'
    assert result['success']
    before = (shapes / 'active.csv').stat()
    assert refresh_custom_show_preview(str(shapes))['preview_themes'] == {'light': True, 'dark': True}
    assert (shapes / 'active.csv').read_bytes() == CSV
    assert (shapes / 'active.csv').stat().st_mtime_ns == before.st_mtime_ns
    info = build_custom_show_info_payload(str(shapes))
    assert info['sha256'] == hashlib.sha256(CSV).hexdigest()
    assert info['preview_themes'] == {'light': True, 'dark': True}
    light, dark = [np.asarray(Image.open(custom_show_preview_path(str(shapes), theme)).convert('RGB')) for theme in ('light', 'dark')]
    assert light.shape == dark.shape
    assert light[5, 5].mean() > 230 and dark[5, 5].mean() < 50
    for pixels in (light, dark):
        # Blue path stays blue; no image inversion or semantic recoloring.
        assert np.any(np.all(pixels == [37, 99, 235], axis=-1))

def test_preview_routes_are_explicit_and_theme_input_is_bounded(tmp_path):
    (tmp_path / 'active.csv').write_bytes(CSV)
    app = FastAPI()
    app.include_router(create_show_management_router(SimpleNamespace(shapes_dir=str(tmp_path))))
    client = TestClient(app)
    assert client.get('/api/v1/shows/custom/preview?theme=dark').status_code == 404
    assert not (tmp_path / 'trajectory_plot.png').exists()  # GET never writes.
    assert client.get('/api/v1/shows/custom/preview?theme=../active.csv').status_code == 422
    assert client.post('/api/v1/shows/custom/preview', json={}).status_code == 200
    for theme in ('light', 'dark'):
        response = client.get('/api/v1/shows/custom/preview', params={'theme': theme})
        assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    (tmp_path / 'active.csv').unlink()
    assert client.post('/api/v1/shows/custom/preview', json={}).status_code == 404
