import importlib.util
import sys
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "sitl_control_client.py"
    spec = importlib.util.spec_from_file_location("sitl_control_client", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_reconcile_request_uses_contiguous_drone_ids_and_env(monkeypatch):
    client = _load_module()
    monkeypatch.setenv("MDS_DOCKER_IMAGE", "custom-sitl:test")
    monkeypatch.setenv("MDS_SITL_DOCKER_NETWORK", "custom-net")
    monkeypatch.setenv("MDS_SITL_GIT_SYNC", "false")
    monkeypatch.setenv("MDS_SITL_REQUIREMENTS_SYNC", "true")

    payload = client.build_reconcile_request([4, 5, 6])

    assert payload == {
        "target_count": 3,
        "start_id": 4,
        "start_ip": 5,
        "git_sync_enabled": False,
        "requirements_sync_enabled": True,
        "image_ref": "custom-sitl:test",
        "docker_network_name": "custom-net",
    }


def test_run_reconcile_auto_falls_back_to_shell(tmp_path, monkeypatch):
    client = _load_module()

    monkeypatch.setattr(
        client,
        "is_api_usable",
        lambda base_url: (
            False,
            {
                "runtime_status": {
                    "mode": "sitl",
                    "configured_mode": "sitl",
                    "configured_sim_mode": True,
                    "restart_required": False,
                }
            },
            "policy unavailable",
        ),
    )
    monkeypatch.setattr(
        client,
        "run_shell_reconcile",
        lambda **kwargs: {
            "status": "passed",
            "execution_mode": "shell",
            "command": ["bash", "multiple_sitl/create_dockers.sh", "3"],
            "elapsed_sec": 1.23,
        },
    )

    payload = client.run_reconcile(
        base_url="http://127.0.0.1:5030",
        repo_root=tmp_path,
        drone_ids=[1, 2, 3],
        mode="auto",
        timeout_sec=180.0,
        poll_interval_sec=1.0,
    )

    assert payload["execution_mode"] == "shell"
    assert payload["api_fallback_reason"] == "policy unavailable"


def test_run_reconcile_refuses_remote_shell_fallback(tmp_path, monkeypatch):
    client = _load_module()
    monkeypatch.setattr(
        client,
        "is_api_usable",
        lambda base_url: (
            False,
            {
                "runtime_status": {
                    "mode": "sitl",
                    "configured_mode": "sitl",
                    "configured_sim_mode": True,
                    "restart_required": False,
                }
            },
            "policy unavailable",
        ),
    )

    try:
        client.run_reconcile(
            base_url="http://198.51.100.5:5030",
            repo_root=tmp_path,
            drone_ids=[1, 2],
            mode="auto",
            timeout_sec=180.0,
            poll_interval_sec=1.0,
        )
    except client.SitlControlClientError as exc:
        assert "shell fallback is prohibited for a remote target" in str(exc)
    else:
        raise AssertionError("remote shell fallback must fail closed")


def test_wait_for_operation_returns_final_success(monkeypatch):
    client = _load_module()

    operations = iter(
        [
            {
                "operation_id": "sitl-123",
                "status": "running",
                "log_lines": ["Launching"],
            },
            {
                "operation_id": "sitl-123",
                "status": "succeeded",
                "summary": "done",
                "detail": "fleet ready",
                "log_lines": ["Launching", "Ready"],
            },
        ]
    )

    monkeypatch.setattr(client, "get_operation", lambda *args, **kwargs: next(operations))
    monkeypatch.setattr(client.time, "sleep", lambda *_args, **_kwargs: None)

    payload = client.wait_for_operation(
        "http://127.0.0.1:5030",
        "sitl-123",
        timeout_sec=5.0,
        poll_interval_sec=0.01,
    )

    assert payload["status"] == "succeeded"
    assert payload["detail"] == "fleet ready"
