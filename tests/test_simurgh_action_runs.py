from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
from threading import Barrier
from pathlib import Path

import agent_runtime.action_runs as action_runs_module
import pytest
from agent_runtime.action_runs import (
    ActionRunOwnershipError,
    ActionRunResourceConflict,
    ActionRunStore,
    ActionRunTerminalStateError,
    MIN_RUNNER_LEASE_SECONDS,
)


def sample_plan():
    return {
        "draft_id": "act-12345678",
        "draft_type": "flight_action",
        "tool_id": "mds.flight.command.execute",
        "steps": [
            {"kind": "flight_command", "label": "Take off to 10 m"},
            {"kind": "delay", "label": "Wait 5 seconds"},
        ],
    }


def test_action_run_rejects_runner_lease_below_supported_minimum(tmp_path):
    store = ActionRunStore(tmp_path / "action-runs.sqlite3")
    with pytest.raises(ValueError, match=f"at least {MIN_RUNNER_LEASE_SECONDS}"):
        store.create_or_get(
            actor="operator",
            session_id="session-1",
            draft_id="act-short-lease",
            plan_hash="plan-short-lease",
            plan=sample_plan(),
            total_steps=2,
            runner_lease_seconds=MIN_RUNNER_LEASE_SECONDS - 1,
        )


def test_action_run_confirmation_is_idempotent(tmp_path):
    store = ActionRunStore(tmp_path / "action-runs.sqlite3")

    first, first_created = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-12345678",
        plan_hash="plan-hash",
        plan=sample_plan(),
        total_steps=2,
    )
    second, second_created = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-12345678",
        plan_hash="plan-hash",
        plan=sample_plan(),
        total_steps=2,
    )

    assert first_created is True
    assert second_created is False
    assert second.run_id == first.run_id
    assert second.plan_hash == first.plan_hash


def test_action_run_events_replay_after_cursor(tmp_path):
    store = ActionRunStore(tmp_path / "action-runs.sqlite3")
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-12345678",
        plan_hash="plan-hash",
        plan=sample_plan(),
        total_steps=2,
    )
    started = store.append_event(
        run.run_id,
        event_type="run_started",
        payload={"stage": "action", "state": "running", "label": "Started"},
        state="running",
    )
    store.append_event(
        run.run_id,
        event_type="progress",
        payload={"stage": "monitor", "state": "running", "label": "Monitoring"},
        current_step=1,
    )

    replay = store.list_events(run.run_id, after_id=started.id)

    assert [event.event_type for event in replay] == ["progress"]
    assert replay[0].payload["label"] == "Monitoring"


def test_action_run_payloads_publish_typed_controls_and_interruption_policy(tmp_path):
    store = ActionRunStore(tmp_path / "action-runs.sqlite3")
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-12345678",
        plan_hash="plan-hash",
        plan=sample_plan(),
        total_steps=2,
    )

    queued = run.public_payload()
    assert queued["schema_version"] == 4
    assert queued["revision"] == 1
    assert queued["last_event_id"] > 0
    assert queued["available_controls"] == ["cancel_remaining"]
    assert queued["current_step_interruption"]["policy"] == "before_dispatch"
    assert queued["current_step_interruption"]["abort_current_step_supported"] is False

    progress = store.append_event(
        run.run_id,
        event_type="progress",
        payload={
            "stage": "monitor",
            "state": "running",
            "label": "Monitoring takeoff",
            "step_index": 1,
            "step_kind": "flight_command",
        },
        state="running",
        current_step=1,
    )

    running = store.require(run.run_id).public_payload()
    assert running["revision"] == 2
    assert running["last_event_id"] == progress.id
    assert running["available_controls"] == [
        "cancel_remaining",
        "pause_after_current_step",
    ]
    assert running["current_step_interruption"]["policy"] == "drain_dispatched_step"
    assert (
        running["current_step_interruption"]["cancel_remaining"]["waits_for_terminal"]
        is True
    )
    event_payload = progress.public_payload()["payload"]
    assert event_payload["available_controls"] == running["available_controls"]
    assert event_payload["current_step_interruption"]["policy"] == "drain_dispatched_step"


def test_action_run_cancel_is_idempotent_and_actor_scoped(tmp_path):
    store = ActionRunStore(tmp_path / "action-runs.sqlite3")
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-12345678",
        plan_hash="plan-hash",
        plan=sample_plan(),
        total_steps=2,
    )

    cancelled = store.request_control(
        run.run_id,
        actor="operator",
        action="cancel_remaining",
        control_id="ctl-stable",
    )
    duplicate = store.request_control(
        run.run_id,
        actor="operator",
        action="cancel_remaining",
        control_id="ctl-stable",
    )

    assert cancelled.state == "cancel_requested"
    assert duplicate.state == "cancel_requested"
    assert len([event for event in store.list_events(run.run_id) if event.event_type == "run_control_requested"]) == 1

    try:
        store.request_control(run.run_id, actor="other", action="resume")
    except PermissionError:
        pass
    else:  # pragma: no cover - explicit failure message
        raise AssertionError("a different actor controlled the action run")


def test_action_run_cancel_is_monotonic_and_terminal_state_clears_control(tmp_path):
    store = ActionRunStore(tmp_path / "action-runs.sqlite3")
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-12345678",
        plan_hash="plan-hash",
        plan=sample_plan(),
        total_steps=2,
    )

    store.request_control(run.run_id, actor="operator", action="cancel_remaining")
    unchanged = store.request_control(run.run_id, actor="operator", action="resume")
    assert unchanged.state == "cancel_requested"
    assert unchanged.control_state == "cancel_requested"
    assert unchanged.public_payload()["available_controls"] == []

    store.append_event(
        run.run_id,
        event_type="progress",
        payload={
            "stage": "monitor",
            "state": "running",
            "label": "Current command still running",
            "step_index": 1,
            "step_kind": "flight_command",
        },
        state="running",
        current_step=1,
    )
    latched = store.require(run.run_id)
    assert latched.state == "cancel_requested"
    assert latched.control_state == "cancel_requested"
    assert (
        latched.public_payload()["current_step_interruption"]["policy"]
        == "drain_dispatched_step"
    )

    terminal = store.append_event(
        run.run_id,
        event_type="run_cancelled",
        payload={"stage": "action", "state": "cancelled", "label": "Cancelled"},
        state="cancelled",
    )

    assert terminal.event_type == "run_cancelled"
    snapshot = store.require(run.run_id)
    assert snapshot.state == "cancelled"
    assert snapshot.control_state == ""
    assert snapshot.terminal is True


def test_action_run_restart_fails_closed_without_resuming_steps(tmp_path):
    path = tmp_path / "action-runs.sqlite3"
    store = ActionRunStore(path)
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-12345678",
        plan_hash="plan-hash",
        plan=sample_plan(),
        total_steps=2,
        runner_owner_id="worker-a",
    )
    store.append_event(
        run.run_id,
        event_type="run_started",
        payload={"stage": "action", "state": "running", "label": "Started"},
        state="running",
        ownership=run.ownership,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE action_runs SET runner_lease_expires_at=0 WHERE run_id=?",
            (run.run_id,),
        )

    restarted = ActionRunStore(path)
    interrupted = restarted.require(run.run_id)

    assert interrupted.state == "interrupted"
    assert interrupted.terminal is True
    assert "no undispatched step was resumed" in interrupted.summary
    assert restarted.list_events(run.run_id)[-1].event_type == "run_interrupted"


def test_action_run_terminal_state_cannot_be_reopened_and_releases_resources(tmp_path):
    path = tmp_path / "action-runs.sqlite3"
    store = ActionRunStore(path)
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-terminal",
        plan_hash="plan-terminal",
        plan=sample_plan(),
        total_steps=2,
        resource_keys=["vehicle:1"],
        runner_owner_id="worker-a",
    )

    store.append_event(
        run.run_id,
        event_type="run_succeeded",
        payload={"stage": "action", "state": "succeeded", "label": "Completed"},
        state="succeeded",
        ownership=run.ownership,
    )

    with pytest.raises(ActionRunTerminalStateError):
        store.append_event(
            run.run_id,
            event_type="progress",
            payload={"stage": "action", "state": "running", "label": "Late update"},
            state="running",
            ownership=run.ownership,
        )

    assert store.require(run.run_id).state == "succeeded"
    assert [event.event_type for event in store.list_events(run.run_id)].count("progress") == 0
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM action_run_resource_leases WHERE run_id=?",
            (run.run_id,),
        ).fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE action_runs SET state='running' WHERE run_id=?",
                (run.run_id,),
            )

    replacement, created = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-replacement",
        plan_hash="plan-replacement",
        plan=sample_plan(),
        total_steps=2,
        resource_keys=["vehicle:1"],
        runner_owner_id="worker-b",
    )
    assert created is True
    assert replacement.resource_keys == ("vehicle:1",)


def test_action_run_ownership_token_generation_can_assert_and_renew(tmp_path):
    store = ActionRunStore(tmp_path / "action-runs.sqlite3")
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-owned",
        plan_hash="plan-owned",
        plan=sample_plan(),
        total_steps=2,
        resource_keys=["vehicle:1", "sitl-instance:drone-1"],
        runner_owner_id="worker-a",
        runner_lease_seconds=5,
    )

    ownership = run.ownership
    assert ownership is not None
    assert ownership.run_id == run.run_id
    assert ownership.runner_generation == 1
    assert ownership.runner_token
    assert store.assert_ownership(ownership).run_id == run.run_id

    renewed = store.renew_ownership(ownership, runner_lease_seconds=120)
    assert renewed.runner_lease_expires_at is not None
    assert run.runner_lease_expires_at is not None
    assert renewed.runner_lease_expires_at > run.runner_lease_expires_at

    with pytest.raises(ActionRunOwnershipError):
        store.assert_ownership(
            type(ownership)(
                run_id=ownership.run_id,
                runner_owner_id="worker-b",
                runner_generation=ownership.runner_generation,
                runner_token=ownership.runner_token,
            )
        )


def test_action_run_resource_leases_allow_disjoint_and_reject_overlap(tmp_path):
    path = tmp_path / "action-runs.sqlite3"
    first_store = ActionRunStore(path)
    first, _ = first_store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-first",
        plan_hash="plan-first",
        plan=sample_plan(),
        total_steps=2,
        resource_keys=["vehicle:1"],
        runner_owner_id="worker-a",
    )

    second_store = ActionRunStore(path)
    assert second_store.require(first.run_id).state == "queued"
    with pytest.raises(ActionRunResourceConflict) as conflict:
        second_store.create_or_get(
            actor="operator",
            session_id="session-1",
            draft_id="act-overlap",
            plan_hash="plan-overlap",
            plan=sample_plan(),
            total_steps=2,
            resource_keys=["vehicle:1", "vehicle:2"],
            runner_owner_id="worker-b",
        )
    assert conflict.value.conflicts == {"vehicle:1": first.run_id}

    disjoint, created = second_store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-disjoint",
        plan_hash="plan-disjoint",
        plan=sample_plan(),
        total_steps=2,
        resource_keys=["vehicle:2"],
        runner_owner_id="worker-b",
    )
    assert created is True
    assert disjoint.resource_keys == ("vehicle:2",)


def test_action_run_resource_conflict_is_atomic_across_concurrent_stores(tmp_path):
    path = tmp_path / "action-runs.sqlite3"
    stores = [ActionRunStore(path), ActionRunStore(path)]
    barrier = Barrier(2)

    def create(index):
        barrier.wait()
        try:
            run, created = stores[index].create_or_get(
                actor="operator",
                session_id="session-1",
                draft_id=f"act-concurrent-{index}",
                plan_hash=f"plan-concurrent-{index}",
                plan=sample_plan(),
                total_steps=2,
                resource_keys=["vehicle:1"],
                runner_owner_id=f"worker-{index}",
            )
            return ("created", created, run.run_id)
        except ActionRunResourceConflict as exc:
            return ("conflict", exc.conflicts)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, (0, 1)))

    assert sorted(result[0] for result in results) == ["conflict", "created"]
    created_run_id = next(result[2] for result in results if result[0] == "created")
    conflict = next(result for result in results if result[0] == "conflict")
    assert conflict[1] == {"vehicle:1": created_run_id}


def test_action_run_expired_owner_is_reaped_and_old_worker_cannot_append(tmp_path):
    path = tmp_path / "action-runs.sqlite3"
    old_store = ActionRunStore(path)
    run, _ = old_store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-expired-owner",
        plan_hash="plan-expired-owner",
        plan=sample_plan(),
        total_steps=2,
        resource_keys=["vehicle:1"],
        runner_owner_id="worker-old",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE action_runs SET runner_lease_expires_at=0 WHERE run_id=?",
            (run.run_id,),
        )

    new_store = ActionRunStore(path)
    interrupted = new_store.require(run.run_id)
    assert interrupted.state == "interrupted"
    assert "ownership expired" in interrupted.summary
    assert new_store.reap_stale_runs() == ()
    with pytest.raises((ActionRunOwnershipError, ActionRunTerminalStateError)):
        old_store.append_event(
            run.run_id,
            event_type="late_progress",
            payload={"stage": "action", "state": "running"},
            state="running",
            ownership=run.ownership,
        )

    replacement, created = new_store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-after-reap",
        plan_hash="plan-after-reap",
        plan=sample_plan(),
        total_steps=2,
        resource_keys=["vehicle:1"],
        runner_owner_id="worker-new",
    )
    assert created is True
    assert replacement.state == "queued"


def test_action_run_existing_sqlite_schema_is_migrated_without_resuming(tmp_path):
    path = tmp_path / "legacy-action-runs.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE action_runs (
                run_id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                session_id TEXT NOT NULL,
                draft_id TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                state TEXT NOT NULL,
                current_step INTEGER NOT NULL DEFAULT 0,
                total_steps INTEGER NOT NULL DEFAULT 1,
                summary TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}',
                control_state TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(actor, draft_id, plan_hash)
            );
            CREATE TABLE action_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES action_runs(run_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE action_run_controls (
                control_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES action_runs(run_id) ON DELETE CASCADE,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO action_runs(
                run_id,actor,session_id,draft_id,plan_hash,plan_json,state,
                total_steps,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?, ?,?,?)
            """,
            (
                "run-legacy-active",
                "operator",
                "session-1",
                "act-legacy-active",
                "plan-legacy-active",
                "{}",
                "running",
                1,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO action_runs(
                run_id,actor,session_id,draft_id,plan_hash,plan_json,state,
                total_steps,created_at,updated_at,completed_at
            ) VALUES(?,?,?,?,?,?,?, ?,?,?,?)
            """,
            (
                "run-legacy-terminal",
                "operator",
                "session-1",
                "act-legacy-terminal",
                "plan-legacy-terminal",
                "{}",
                "succeeded",
                1,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    store = ActionRunStore(path, max_age_days=3650)
    assert store.require("run-legacy-active").state == "interrupted"
    assert store.require("run-legacy-terminal").state == "succeeded"
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(action_runs)")
        }
        assert {
            "resource_keys_json",
            "revision",
            "last_event_id",
            "runner_owner_id",
            "runner_generation",
            "runner_token",
            "runner_lease_expires_at",
        } <= columns
        assert connection.execute(
            "SELECT user_version FROM pragma_user_version"
        ).fetchone()[0] == 4


def test_action_run_relative_env_path_is_resolved_from_repo_root(monkeypatch, tmp_path):
    repo_root = Path(action_runs_module.__file__).resolve().parents[2]
    target = tmp_path / "relative-action-runs.sqlite3"
    monkeypatch.setenv("MDS_AGENT_ACTION_RUN_DB", os.path.relpath(target, repo_root))

    store = ActionRunStore.from_env()

    assert Path(store.db_path).resolve() == target.resolve()


def test_action_run_retention_prunes_oldest_terminal_runs_per_actor(tmp_path):
    store = ActionRunStore(
        tmp_path / "action-runs.sqlite3",
        max_age_days=30,
        max_records_per_actor=2,
    )
    run_ids = []
    for index in range(3):
        run, _ = store.create_or_get(
            actor="operator",
            session_id="session-1",
            draft_id=f"act-{index}",
            plan_hash=f"plan-{index}",
            plan=sample_plan(),
            total_steps=2,
        )
        store.append_event(
            run.run_id,
            event_type="run_succeeded",
            payload={"stage": "action", "state": "succeeded", "label": "Completed"},
            state="succeeded",
        )
        run_ids.append(run.run_id)

    retained = store.list_runs(actor="operator", limit=10)

    assert [run.run_id for run in retained] == list(reversed(run_ids[1:]))
    with pytest.raises(KeyError, match="unknown action run id"):
        store.require(run_ids[0])


def test_action_run_retention_prunes_expired_terminal_runs_on_restart(tmp_path):
    path = tmp_path / "action-runs.sqlite3"
    store = ActionRunStore(path, max_age_days=1)
    run, _ = store.create_or_get(
        actor="operator",
        session_id="session-1",
        draft_id="act-expired",
        plan_hash="plan-expired",
        plan=sample_plan(),
        total_steps=2,
    )
    store.append_event(
        run.run_id,
        event_type="run_succeeded",
        payload={"stage": "action", "state": "succeeded", "label": "Completed"},
        state="succeeded",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE action_runs SET updated_at=?, completed_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", run.run_id),
        )

    restarted = ActionRunStore(path, max_age_days=1)

    with pytest.raises(KeyError, match="unknown action run id"):
        restarted.require(run.run_id)


def test_action_run_retention_env_is_bounded_and_configurable(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ACTION_RUN_DB", str(tmp_path / "action-runs.sqlite3"))
    monkeypatch.setenv("MDS_AGENT_ACTION_RUN_MAX_AGE_DAYS", "45")
    monkeypatch.setenv("MDS_AGENT_ACTION_RUN_MAX_RECORDS", "350")

    store = ActionRunStore.from_env()

    assert store.max_age_days == 45
    assert store.max_records_per_actor == 350
