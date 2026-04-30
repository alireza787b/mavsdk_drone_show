import json

from src.settings.env_status import build_node_env_summary
from src.settings.runtime import reset_preloaded_local_env_state


def test_build_node_env_summary_reports_safe_registry_posture(monkeypatch, tmp_path):
    local_env = tmp_path / "local.env"
    identity_file = tmp_path / "node_identity.json"
    local_env.write_text(
        "\n".join([
            "MDS_MODE=real",
            "MDS_HW_ID=7",
            "MDS_GCS_IP=100.64.1.10",
            "MDS_DRONE_API_PORT=7070",
            "OLD_NODE_KEY=value",
        ]),
        encoding="utf-8",
    )
    identity_file.write_text(json.dumps({"hw_id": 7, "node_uuid": "node-7"}), encoding="utf-8")

    reset_preloaded_local_env_state()
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(local_env))
    monkeypatch.setenv("MDS_NODE_IDENTITY_FILE", str(identity_file))

    summary = build_node_env_summary()

    assert summary["status_source"] == "registry"
    assert summary["local_env_present"] is True
    assert summary["node_identity_present"] is True
    assert summary["runtime_mode"] == "real"
    assert summary["hw_id"] == 7
    assert "OLD_NODE_KEY" in summary["unknown_keys"]
    assert summary["configured_node_key_count"] >= 3
    assert summary["registered_node_key_count"] > summary["configured_node_key_count"]
    assert summary["registry_hash"]

    reset_preloaded_local_env_state()
