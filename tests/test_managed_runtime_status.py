from src.managed_runtime_status import resolve_dashboard_access


def test_resolve_dashboard_access_for_wildcard_listener_uses_node_ip():
    result = resolve_dashboard_access("10.0.0.21", "0.0.0.0:9070")

    assert result == {
        "dashboard_access_mode": "direct",
        "dashboard_url": "http://10.0.0.21:9070",
    }


def test_resolve_dashboard_access_for_loopback_listener_stays_local_only():
    result = resolve_dashboard_access("10.0.0.21", "127.0.0.1:9080")

    assert result == {
        "dashboard_access_mode": "local_only",
        "dashboard_url": None,
    }


def test_resolve_dashboard_access_for_explicit_remote_host_keeps_host():
    result = resolve_dashboard_access("10.0.0.21", "100.82.7.9:9070")

    assert result == {
        "dashboard_access_mode": "direct",
        "dashboard_url": "http://100.82.7.9:9070",
    }
