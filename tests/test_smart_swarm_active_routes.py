from pathlib import Path


def test_smart_swarm_uses_canonical_gcs_swarm_routes():
    content = Path("smart_swarm.py").read_text()

    assert "/get-swarm-data" not in content
    assert "/request-new-leader" not in content
    assert "GCS_CONFIG_SWARM_ROUTE" in content
    assert "GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE" in content
