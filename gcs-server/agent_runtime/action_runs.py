"""Durable operator-visible action runs for Simurgh.

The command tracker remains authoritative for accepted GCS flight commands.
This store records the higher-level, potentially multi-step operator workflow so
chat streams can disconnect and reconnect without owning execution state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


ACTION_RUN_SCHEMA_VERSION = 1
ACTION_RUN_TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "blocked", "cancelled", "interrupted"}
)
ACTION_RUN_ACTIVE_STATES = frozenset(
    {"queued", "running", "pause_requested", "paused", "cancel_requested"}
)
ACTION_RUN_CONTROL_ACTIONS = frozenset(
    {"cancel_remaining", "pause_after_current_step", "resume"}
)
DEFAULT_ACTION_RUN_MAX_AGE_DAYS = 30
DEFAULT_ACTION_RUN_MAX_RECORDS = 200


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _decode_json(value: str | None, default: Any) -> Any:
    try:
        decoded = json.loads(value or "")
    except (TypeError, ValueError):
        return default
    return decoded


def _bounded_positive_int_env(name: str, default: int, *, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, min(int(raw), maximum))
    except ValueError:
        return default


@dataclass(frozen=True)
class ActionRunEvent:
    id: int
    run_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at: str

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ActionRunSnapshot:
    run_id: str
    actor: str
    session_id: str
    draft_id: str
    plan_hash: str
    plan: Mapping[str, Any]
    state: str
    current_step: int
    total_steps: int
    summary: str
    result: Mapping[str, Any]
    control_state: str
    created_at: str
    updated_at: str
    completed_at: str | None

    @property
    def terminal(self) -> bool:
        return self.state in ACTION_RUN_TERMINAL_STATES

    def public_payload(self, *, include_plan: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": ACTION_RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "actor": self.actor,
            "session_id": self.session_id,
            "draft_id": self.draft_id,
            "plan_hash": self.plan_hash,
            "state": self.state,
            "terminal": self.terminal,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "summary": self.summary,
            "result": dict(self.result),
            "control_state": self.control_state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }
        if include_plan:
            payload["plan"] = dict(self.plan)
        return payload


class ActionRunStore:
    """SQLite-backed action-run journal with atomic confirmation idempotency."""

    def __init__(
        self,
        db_path: str | os.PathLike[str],
        *,
        max_age_days: int = DEFAULT_ACTION_RUN_MAX_AGE_DAYS,
        max_records_per_actor: int = DEFAULT_ACTION_RUN_MAX_RECORDS,
    ):
        self.db_path = str(db_path)
        self.max_age_days = max(1, min(int(max_age_days), 3650))
        self.max_records_per_actor = max(1, min(int(max_records_per_actor), 10000))
        self._lock = threading.RLock()
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()
        self._interrupt_orphaned_runs()
        self._prune_retention()

    @classmethod
    def from_env(cls) -> "ActionRunStore":
        repo_root = Path(__file__).resolve().parents[2]
        configured = os.getenv("MDS_AGENT_ACTION_RUN_DB", "").strip()
        path = Path(configured).expanduser() if configured else Path("runtime_data/simurgh/action_runs.sqlite3")
        if not path.is_absolute():
            path = repo_root / path
        return cls(
            path,
            max_age_days=_bounded_positive_int_env(
                "MDS_AGENT_ACTION_RUN_MAX_AGE_DAYS",
                DEFAULT_ACTION_RUN_MAX_AGE_DAYS,
                maximum=3650,
            ),
            max_records_per_actor=_bounded_positive_int_env(
                "MDS_AGENT_ACTION_RUN_MAX_RECORDS",
                DEFAULT_ACTION_RUN_MAX_RECORDS,
                maximum=10000,
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS action_runs (
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
                CREATE INDEX IF NOT EXISTS idx_action_runs_actor_updated
                    ON action_runs(actor, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_action_runs_session_updated
                    ON action_runs(session_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS action_run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES action_runs(run_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_action_run_events_run_id
                    ON action_run_events(run_id, id);

                CREATE TABLE IF NOT EXISTS action_run_controls (
                    control_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES action_runs(run_id) ON DELETE CASCADE,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )

    def _interrupt_orphaned_runs(self) -> None:
        now = _utc_now()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id FROM action_runs WHERE state IN ('queued','running','pause_requested','paused','cancel_requested')"
            ).fetchall()
            for row in rows:
                run_id = str(row["run_id"])
                summary = "GCS restarted before the action run reached a terminal state; no undispatched step was resumed."
                connection.execute(
                    """
                    UPDATE action_runs
                    SET state='interrupted', summary=?, control_state='', updated_at=?, completed_at=?
                    WHERE run_id=?
                    """,
                    (summary, now, now, run_id),
                )
                connection.execute(
                    "INSERT INTO action_run_events(run_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                    (
                        run_id,
                        "run_interrupted",
                        _canonical_json(
                            {
                                "stage": "action",
                                "state": "interrupted",
                                "label": "Action run interrupted by GCS restart",
                                "summary": summary,
                                "run_id": run_id,
                            }
                        ),
                        now,
                    ),
                )

    def _prune_retention(
        self,
        connection: sqlite3.Connection | None = None,
        *,
        actor: str | None = None,
    ) -> None:
        """Bound terminal history while preserving every active action run."""

        owned_connection = connection is None
        db = connection or self._connect()
        terminal_states = tuple(sorted(ACTION_RUN_TERMINAL_STATES))
        placeholders = ",".join("?" for _ in terminal_states)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.max_age_days)).isoformat()
        try:
            db.execute(
                f"DELETE FROM action_runs WHERE state IN ({placeholders}) AND updated_at < ?",
                (*terminal_states, cutoff),
            )
            actors = (
                [actor]
                if actor
                else [
                    str(row["actor"])
                    for row in db.execute(
                        f"SELECT DISTINCT actor FROM action_runs WHERE state IN ({placeholders})",
                        terminal_states,
                    ).fetchall()
                ]
            )
            for actor_id in actors:
                stale_rows = db.execute(
                    f"""
                    SELECT run_id FROM action_runs
                    WHERE actor=? AND state IN ({placeholders})
                    ORDER BY updated_at DESC, run_id DESC
                    LIMIT -1 OFFSET ?
                    """,
                    (actor_id, *terminal_states, self.max_records_per_actor),
                ).fetchall()
                stale_ids = [str(row["run_id"]) for row in stale_rows]
                if stale_ids:
                    stale_placeholders = ",".join("?" for _ in stale_ids)
                    db.execute(
                        f"DELETE FROM action_runs WHERE run_id IN ({stale_placeholders})",
                        stale_ids,
                    )
            if owned_connection:
                db.commit()
        finally:
            if owned_connection:
                db.close()

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> ActionRunSnapshot:
        plan = _decode_json(row["plan_json"], {})
        result = _decode_json(row["result_json"], {})
        return ActionRunSnapshot(
            run_id=str(row["run_id"]),
            actor=str(row["actor"]),
            session_id=str(row["session_id"]),
            draft_id=str(row["draft_id"]),
            plan_hash=str(row["plan_hash"]),
            plan=plan if isinstance(plan, Mapping) else {},
            state=str(row["state"]),
            current_step=int(row["current_step"] or 0),
            total_steps=max(1, int(row["total_steps"] or 1)),
            summary=str(row["summary"] or ""),
            result=result if isinstance(result, Mapping) else {},
            control_state=str(row["control_state"] or ""),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
        )

    def create_or_get(
        self,
        *,
        actor: str,
        session_id: str,
        draft_id: str,
        plan_hash: str,
        plan: Mapping[str, Any],
        total_steps: int,
    ) -> tuple[ActionRunSnapshot, bool]:
        now = _utc_now()
        run_id = f"run-{uuid.uuid4().hex[:16]}"
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM action_runs WHERE actor=? AND draft_id=? AND plan_hash=?",
                (actor, draft_id, plan_hash),
            ).fetchone()
            if row is not None:
                return self._snapshot(row), False
            connection.execute(
                """
                INSERT INTO action_runs(
                    run_id,actor,session_id,draft_id,plan_hash,plan_json,state,
                    current_step,total_steps,summary,result_json,control_state,
                    created_at,updated_at,completed_at
                ) VALUES(?,?,?,?,?,?,'queued',0,?,'','{}','',?,?,NULL)
                """,
                (
                    run_id,
                    actor,
                    session_id,
                    draft_id,
                    plan_hash,
                    _canonical_json(dict(plan)),
                    max(1, int(total_steps)),
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO action_run_events(run_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                (
                    run_id,
                    "run_queued",
                    _canonical_json(
                        {
                            "stage": "action",
                            "state": "queued",
                            "label": "Action run queued",
                            "run_id": run_id,
                            "step_count": max(1, int(total_steps)),
                        }
                    ),
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
            assert row is not None
            return self._snapshot(row), True

    def require(self, run_id: str) -> ActionRunSnapshot:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown action run id: {run_id}")
        return self._snapshot(row)

    def list_runs(
        self,
        *,
        actor: str | None = None,
        session_id: str | None = None,
        active_only: bool = False,
        limit: int = 20,
    ) -> list[ActionRunSnapshot]:
        clauses: list[str] = []
        values: list[Any] = []
        if actor:
            clauses.append("actor=?")
            values.append(actor)
        if session_id:
            clauses.append("session_id=?")
            values.append(session_id)
        if active_only:
            clauses.append("state IN ('queued','running','pause_requested','paused','cancel_requested')")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 100)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM action_runs{where} ORDER BY updated_at DESC LIMIT ?",
                tuple(values),
            ).fetchall()
        return [self._snapshot(row) for row in rows]

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        state: str | None = None,
        current_step: int | None = None,
        summary: str | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> ActionRunEvent:
        now = _utc_now()
        safe_payload = dict(payload)
        safe_payload.setdefault("run_id", run_id)
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown action run id: {run_id}")
            next_state = str(state or row["state"])
            next_step = int(current_step if current_step is not None else row["current_step"] or 0)
            next_summary = str(summary if summary is not None else row["summary"] or "")[:1000]
            next_result = dict(result) if result is not None else _decode_json(row["result_json"], {})
            completed_at = now if next_state in ACTION_RUN_TERMINAL_STATES else row["completed_at"]
            next_control_state = "" if next_state in ACTION_RUN_TERMINAL_STATES else str(row["control_state"] or "")
            connection.execute(
                """
                UPDATE action_runs
                SET state=?,current_step=?,summary=?,result_json=?,control_state=?,updated_at=?,completed_at=?
                WHERE run_id=?
                """,
                (
                    next_state,
                    max(0, next_step),
                    next_summary,
                    _canonical_json(next_result if isinstance(next_result, Mapping) else {}),
                    next_control_state,
                    now,
                    completed_at,
                    run_id,
                ),
            )
            cursor = connection.execute(
                "INSERT INTO action_run_events(run_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                (run_id, str(event_type)[:80], _canonical_json(safe_payload), now),
            )
            event_id = int(cursor.lastrowid)
            if next_state in ACTION_RUN_TERMINAL_STATES:
                self._prune_retention(connection, actor=str(row["actor"]))
        return ActionRunEvent(event_id, run_id, str(event_type)[:80], safe_payload, now)

    def list_events(self, run_id: str, *, after_id: int = 0, limit: int = 200) -> list[ActionRunEvent]:
        self.require(run_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id,run_id,event_type,payload_json,created_at
                FROM action_run_events
                WHERE run_id=? AND id>?
                ORDER BY id ASC
                LIMIT ?
                """,
                (run_id, max(0, int(after_id)), max(1, min(int(limit), 1000))),
            ).fetchall()
        events: list[ActionRunEvent] = []
        for row in rows:
            payload = _decode_json(row["payload_json"], {})
            events.append(
                ActionRunEvent(
                    id=int(row["id"]),
                    run_id=str(row["run_id"]),
                    event_type=str(row["event_type"]),
                    payload=payload if isinstance(payload, Mapping) else {},
                    created_at=str(row["created_at"]),
                )
            )
        return events

    def request_control(
        self,
        run_id: str,
        *,
        actor: str,
        action: str,
        reason: str = "",
        control_id: str | None = None,
    ) -> ActionRunSnapshot:
        normalized_action = str(action or "").strip().casefold()
        if normalized_action not in ACTION_RUN_CONTROL_ACTIONS:
            raise ValueError(f"unsupported action-run control: {action}")
        stable_control_id = str(control_id or f"ctl-{uuid.uuid4().hex[:16]}").strip()
        now = _utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown action run id: {run_id}")
            if str(row["actor"]) != str(actor):
                raise PermissionError("action run belongs to a different operator")
            existing = connection.execute(
                "SELECT control_id FROM action_run_controls WHERE control_id=?",
                (stable_control_id,),
            ).fetchone()
            if existing is not None:
                return self._snapshot(row)
            if str(row["state"]) in ACTION_RUN_TERMINAL_STATES:
                return self._snapshot(row)
            if (
                str(row["state"]) == "cancel_requested"
                or str(row["control_state"] or "") == "cancel_requested"
            ) and normalized_action != "cancel_remaining":
                return self._snapshot(row)
            control_state = {
                "cancel_remaining": "cancel_requested",
                "pause_after_current_step": "pause_requested",
                "resume": "",
            }[normalized_action]
            next_state = str(row["state"])
            if normalized_action == "cancel_remaining":
                next_state = "cancel_requested"
            elif normalized_action == "pause_after_current_step":
                next_state = "pause_requested"
            elif normalized_action == "resume" and next_state in {"paused", "pause_requested"}:
                next_state = "running"
            connection.execute(
                "INSERT INTO action_run_controls(control_id,run_id,actor,action,reason,created_at) VALUES(?,?,?,?,?,?)",
                (stable_control_id, run_id, actor, normalized_action, str(reason or "")[:500], now),
            )
            connection.execute(
                "UPDATE action_runs SET state=?,control_state=?,updated_at=? WHERE run_id=?",
                (next_state, control_state, now, run_id),
            )
            connection.execute(
                "INSERT INTO action_run_events(run_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                (
                    run_id,
                    "run_control_requested",
                    _canonical_json(
                        {
                            "stage": "action",
                            "state": next_state,
                            "label": normalized_action.replace("_", " ").capitalize(),
                            "run_id": run_id,
                            "control_id": stable_control_id,
                            "control": normalized_action,
                        }
                    ),
                    now,
                ),
            )
            updated = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
            assert updated is not None
            return self._snapshot(updated)

    def clear_control(self, run_id: str, *, state: str = "running") -> ActionRunSnapshot:
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE action_runs SET state=?,control_state='',updated_at=? WHERE run_id=?",
                (state, now, run_id),
            )
            row = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown action run id: {run_id}")
        return self._snapshot(row)
