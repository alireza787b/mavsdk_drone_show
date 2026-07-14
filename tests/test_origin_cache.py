"""Unit tests for local origin cache validation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest


@pytest.fixture
def cache_paths(tmp_path, monkeypatch):
    import src.origin_cache as oc

    cache_dir = tmp_path / "cache"
    cache_file = cache_dir / "origin_cache.json"
    monkeypatch.setattr(oc, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(oc, "CACHE_FILE", cache_file)
    return oc, cache_file


def test_save_and_load_roundtrip(cache_paths):
    oc, cache_file = cache_paths
    payload = {"lat": 35.1, "lon": -120.5, "alt": 100.0, "source": "test"}
    assert oc.save_origin_to_cache(payload) is True
    assert cache_file.exists()
    loaded = oc.load_origin_from_cache()
    assert loaded is not None
    assert loaded["lat"] == 35.1
    assert loaded["lon"] == -120.5
    assert loaded["alt"] == 100.0
    assert "cached_at" in loaded


@pytest.mark.parametrize(
    "bad",
    [
        {"lat": 91.0, "lon": 0.0, "alt": 1.0},
        {"lat": 0.0, "lon": 200.0, "alt": 1.0},
        {"lat": "n/a", "lon": 0.0, "alt": 1.0},
        {"lat": 0.0, "lon": 0.0, "alt": math.inf},
        {"lat": math.nan, "lon": 0.0, "alt": 1.0},
        {"lat": 0.0, "lon": 0.0},  # missing alt
    ],
)
def test_save_rejects_invalid_origin(cache_paths, bad):
    oc, cache_file = cache_paths
    assert oc.save_origin_to_cache(dict(bad)) is False
    assert not cache_file.exists()


def test_load_rejects_invalid_cached_values(cache_paths):
    oc, cache_file = cache_paths
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"lat": 12.0, "lon": -999.0, "alt": 10.0}))
    assert oc.load_origin_from_cache() is None
