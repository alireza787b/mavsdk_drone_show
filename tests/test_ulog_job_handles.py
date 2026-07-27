from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ulog_job_handles import (
    create_ulog_job_capability,
    issue_ulog_job_handle,
    require_raw_ulog_actor,
    resolve_ulog_job_handle,
)


def test_handle_is_bound_to_actor_and_drone(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MDS_AUTH_SESSION_SECRET_FILE",
        str(tmp_path / "session-secret"),
    )
    capability = create_ulog_job_capability(
        drone_id=3,
        owner_fingerprint="owner-a",
    )
    handle = issue_ulog_job_handle(
        drone_id=3,
        node_job_id="node-job-7",
        owner_fingerprint="owner-a",
        expires_at_ms=None,
        capability_nonce=capability.nonce,
    )

    resolved = resolve_ulog_job_handle(
        handle,
        drone_id=3,
        owner_fingerprint="owner-a",
    )

    assert resolved.node_job_id == "node-job-7"
    assert resolved.access_token == capability.access_token
    with pytest.raises(HTTPException) as cross_actor:
        resolve_ulog_job_handle(
            handle,
            drone_id=3,
            owner_fingerprint="owner-b",
        )
    assert cross_actor.value.status_code == 404
    with pytest.raises(HTTPException) as cross_drone:
        resolve_ulog_job_handle(
            handle,
            drone_id=4,
            owner_fingerprint="owner-a",
        )
    assert cross_drone.value.status_code == 404


def test_raw_job_access_rejects_viewer():
    request = SimpleNamespace(
        state=SimpleNamespace(
            mds_auth_context={
                "kind": "session",
                "role": "viewer",
                "username": "viewer",
                "sid": "session-a",
            }
        )
    )

    with pytest.raises(HTTPException) as denied:
        require_raw_ulog_actor(request)

    assert denied.value.status_code == 403
