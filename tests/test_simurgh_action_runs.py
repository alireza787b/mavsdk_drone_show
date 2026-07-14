from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import agent_runtime.action_runs as action_runs_module
import pytest
from agent_runtime.action_runs import ActionRunStore


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
    )
    store.append_event(
        run.run_id,
        event_type="run_started",
        payload={"stage": "action", "state": "running", "label": "Started"},
        state="running",
    )

    restarted = ActionRunStore(path)
    interrupted = restarted.require(run.run_id)

    assert interrupted.state == "interrupted"
    assert interrupted.terminal is True
    assert "no undispatched step was resumed" in interrupted.summary
    assert restarted.list_events(run.run_id)[-1].event_type == "run_interrupted"


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
