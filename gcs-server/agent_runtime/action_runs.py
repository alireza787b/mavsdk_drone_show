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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ACTION_RUN_SCHEMA_VERSION = 4
ACTION_RUN_TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "blocked", "skipped", "cancelled", "interrupted"}
)
ACTION_RUN_ACTIVE_STATES = frozenset(
    {"queued", "running", "pause_requested", "paused", "cancel_requested"}
)
ACTION_RUN_CONTROL_ACTIONS = frozenset(
    {"cancel_remaining", "pause_after_current_step", "resume"}
)
DEFAULT_ACTION_RUN_MAX_AGE_DAYS = 30
DEFAULT_ACTION_RUN_MAX_RECORDS = 200
MIN_RUNNER_LEASE_SECONDS = 5
DEFAULT_RUNNER_LEASE_SECONDS = 60
MAX_RUNNER_LEASE_SECONDS = 3600
_DISPATCHED_STEP_KINDS = frozenset(
    {"action", "flight_command", "registry_action", "system_action"}
)
_LOCAL_WAIT_STEP_KINDS = frozenset({"delay", "wait"})


class ActionRunResourceConflict(RuntimeError):
    """Raised when an active run already leases one or more requested resources."""

    def __init__(self, conflicts: Mapping[str, str]):
        self.conflicts = dict(sorted(conflicts.items()))
        resources = ", ".join(self.conflicts)
        super().__init__(f"action resources already leased: {resources}")


class ActionRunOwnershipError(RuntimeError):
    """Raised when a runner no longer owns an active action run."""


class ActionRunTerminalStateError(RuntimeError):
    """Raised when code attempts to mutate an already-terminal action run."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unix_now() -> float:
    return time.time()


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


def _bounded_lease_seconds(value: int | float) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("runner_lease_seconds must be a positive integer") from exc
    if parsed < MIN_RUNNER_LEASE_SECONDS:
        raise ValueError(
            f"runner_lease_seconds must be at least {MIN_RUNNER_LEASE_SECONDS}"
        )
    return min(parsed, MAX_RUNNER_LEASE_SECONDS)


def _normalize_resource_keys(resource_keys: Iterable[str] | str | None) -> tuple[str, ...]:
    if resource_keys is None:
        return ()
    values = (resource_keys,) if isinstance(resource_keys, str) else resource_keys
    normalized: set[str] = set()
    for value in values:
        key = str(value or "").strip().casefold()
        namespace, separator, identifier = key.partition(":")
        if not separator or not namespace or not identifier:
            raise ValueError(
                "resource keys must be typed as '<namespace>:<identifier>'"
            )
        if len(key) > 255 or any(character.isspace() for character in key):
            raise ValueError("resource keys must be at most 255 non-whitespace characters")
        normalized.add(key)
    return tuple(sorted(normalized))


def _plan_step(plan: Mapping[str, Any], current_step: int) -> Mapping[str, Any]:
    display_plan = plan.get("display_plan")
    if isinstance(display_plan, Mapping):
        steps = display_plan.get("steps")
    else:
        steps = plan.get("steps")
    if not isinstance(steps, list):
        return {}
    for position, item in enumerate(steps, start=1):
        if not isinstance(item, Mapping):
            continue
        try:
            index = int(item.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        if index == current_step or (index == 0 and position == current_step):
            return item
    return {}


def _available_controls(state: str) -> list[str]:
    normalized = str(state or "").strip().casefold()
    if normalized == "running":
        return ["cancel_remaining", "pause_after_current_step"]
    if normalized == "queued":
        return ["cancel_remaining"]
    if normalized in {"pause_requested", "paused"}:
        return ["cancel_remaining", "resume"]
    return []


def _current_step_interruption(
    *,
    state: str,
    current_step: int,
    plan: Mapping[str, Any],
    step_kind: str = "",
) -> dict[str, Any]:
    normalized_state = str(state or "").strip().casefold()
    current = _plan_step(plan, current_step)
    kind = str(step_kind or current.get("kind") or "").strip().casefold()
    active = normalized_state in ACTION_RUN_ACTIVE_STATES and current_step > 0
    if normalized_state in ACTION_RUN_TERMINAL_STATES:
        policy = "terminal"
    elif not active:
        policy = "before_dispatch"
    elif kind in _LOCAL_WAIT_STEP_KINDS:
        policy = "stop_local_wait"
    elif kind in _DISPATCHED_STEP_KINDS:
        policy = "drain_dispatched_step"
    else:
        policy = "safe_step_boundary"
    return {
        "policy": policy,
        "step_kind": kind,
        "active_step": active,
        "cancel_remaining": {
            "stops_current_step": policy == "stop_local_wait",
            "blocks_future_dispatches": True,
            "waits_for_terminal": policy == "drain_dispatched_step",
        },
        "pause_after_current_step": {
            "stops_current_step": False,
            "pauses_before_next_dispatch": True,
        },
        "abort_current_step_supported": False,
    }


def _control_contract(
    *,
    state: str,
    current_step: int,
    plan: Mapping[str, Any],
    step_kind: str = "",
) -> dict[str, Any]:
    return {
        "available_controls": _available_controls(state),
        "current_step_interruption": _current_step_interruption(
            state=state,
            current_step=current_step,
            plan=plan,
            step_kind=step_kind,
        ),
    }


@dataclass(frozen=True)
class ActionRunEvent:
    id: int
    run_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at: str

    def public_payload(self) -> dict[str, Any]:
        payload = dict(self.payload)
        run_state = str(payload.get("run_state") or payload.get("state") or "")
        try:
            current_step = int(payload.get("step_index") or 0)
        except (TypeError, ValueError):
            current_step = 0
        contract = _control_contract(
            state=run_state,
            current_step=current_step,
            plan={},
            step_kind=str(payload.get("step_kind") or ""),
        )
        payload.setdefault("available_controls", contract["available_controls"])
        payload.setdefault(
            "current_step_interruption",
            contract["current_step_interruption"],
        )
        return {
            "id": self.id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "payload": payload,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ActionRunOwnership:
    """Opaque capability identifying one persisted runner generation."""

    run_id: str
    runner_owner_id: str
    runner_generation: int
    runner_token: str


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
    resource_keys: tuple[str, ...]
    revision: int
    last_event_id: int
    runner_owner_id: str
    runner_generation: int
    runner_token: str
    runner_lease_expires_at: float | None
    created_at: str
    updated_at: str
    completed_at: str | None

    @property
    def terminal(self) -> bool:
        return self.state in ACTION_RUN_TERMINAL_STATES

    @property
    def ownership(self) -> ActionRunOwnership | None:
        if (
            not self.runner_owner_id
            or self.runner_generation < 1
            or not self.runner_token
        ):
            return None
        return ActionRunOwnership(
            run_id=self.run_id,
            runner_owner_id=self.runner_owner_id,
            runner_generation=self.runner_generation,
            runner_token=self.runner_token,
        )

    def public_payload(self, *, include_plan: bool = True) -> dict[str, Any]:
        control_contract = _control_contract(
            state=self.state,
            current_step=self.current_step,
            plan=self.plan,
        )
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
            "resource_keys": list(self.resource_keys),
            "revision": self.revision,
            "last_event_id": self.last_event_id,
            **control_contract,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }
        if include_plan:
            payload["plan"] = dict(self.plan)
        return payload


class ActionRunStore:
    """SQLite-backed action-run journal with durable runner leases."""

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
        self._default_runner_owner_id = f"store-{uuid.uuid4().hex}"
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()
        self._reap_stale_runner_leases()
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

    @staticmethod
    def _begin_immediate(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

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
                    resource_keys_json TEXT NOT NULL DEFAULT '[]',
                    revision INTEGER NOT NULL DEFAULT 0,
                    last_event_id INTEGER NOT NULL DEFAULT 0,
                    runner_owner_id TEXT NOT NULL DEFAULT '',
                    runner_generation INTEGER NOT NULL DEFAULT 0,
                    runner_token TEXT NOT NULL DEFAULT '',
                    runner_lease_expires_at REAL,
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

                CREATE TABLE IF NOT EXISTS action_run_resource_leases (
                    resource_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES action_runs(run_id) ON DELETE CASCADE,
                    runner_owner_id TEXT NOT NULL,
                    runner_generation INTEGER NOT NULL,
                    runner_token TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    lease_expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_action_run_resource_leases_run_id
                    ON action_run_resource_leases(run_id);
                CREATE INDEX IF NOT EXISTS idx_action_run_resource_leases_expiry
                    ON action_run_resource_leases(lease_expires_at);

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

            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(action_runs)").fetchall()
            }
            migrations = {
                "resource_keys_json": "ALTER TABLE action_runs ADD COLUMN resource_keys_json TEXT NOT NULL DEFAULT '[]'",
                "revision": "ALTER TABLE action_runs ADD COLUMN revision INTEGER NOT NULL DEFAULT 0",
                "last_event_id": "ALTER TABLE action_runs ADD COLUMN last_event_id INTEGER NOT NULL DEFAULT 0",
                "runner_owner_id": "ALTER TABLE action_runs ADD COLUMN runner_owner_id TEXT NOT NULL DEFAULT ''",
                "runner_generation": "ALTER TABLE action_runs ADD COLUMN runner_generation INTEGER NOT NULL DEFAULT 0",
                "runner_token": "ALTER TABLE action_runs ADD COLUMN runner_token TEXT NOT NULL DEFAULT ''",
                "runner_lease_expires_at": "ALTER TABLE action_runs ADD COLUMN runner_lease_expires_at REAL",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_action_runs_runner_lease
                    ON action_runs(runner_lease_expires_at)
                """
            )
            connection.execute(
                """
                UPDATE action_runs
                SET revision=(
                        SELECT COUNT(*)
                        FROM action_run_events
                        WHERE action_run_events.run_id=action_runs.run_id
                    ),
                    last_event_id=COALESCE((
                        SELECT MAX(id)
                        FROM action_run_events
                        WHERE action_run_events.run_id=action_runs.run_id
                    ), 0)
                """
            )

            terminal_states = ", ".join(
                f"'{state}'" for state in sorted(ACTION_RUN_TERMINAL_STATES)
            )
            connection.executescript(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_action_runs_terminal_monotonic
                BEFORE UPDATE OF state ON action_runs
                WHEN OLD.state IN ({terminal_states}) AND NEW.state <> OLD.state
                BEGIN
                    SELECT RAISE(ABORT, 'terminal action run state is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_action_runs_release_resources
                AFTER UPDATE OF state ON action_runs
                WHEN NEW.state IN ({terminal_states}) AND OLD.state NOT IN ({terminal_states})
                BEGIN
                    DELETE FROM action_run_resource_leases WHERE run_id = NEW.run_id;
                    UPDATE action_runs
                    SET runner_lease_expires_at = NULL
                    WHERE run_id = NEW.run_id;
                END;

                CREATE TRIGGER IF NOT EXISTS trg_action_run_event_revision
                AFTER INSERT ON action_run_events
                BEGIN
                    UPDATE action_runs
                    SET revision = revision + 1,
                        last_event_id = NEW.id
                    WHERE run_id = NEW.run_id;
                END;
                """
            )
            connection.execute(f"PRAGMA user_version = {ACTION_RUN_SCHEMA_VERSION}")

    def _reap_stale_runner_leases(
        self,
        connection: sqlite3.Connection | None = None,
        *,
        now_epoch: float | None = None,
    ) -> tuple[str, ...]:
        """Interrupt expired/legacy owners; never resume a partially-run plan."""

        owned_connection = connection is None
        db = connection or self._connect()
        now_epoch = _unix_now() if now_epoch is None else float(now_epoch)
        now = _utc_now()
        reaped: list[str] = []
        try:
            if owned_connection:
                self._begin_immediate(db)
            rows = db.execute(
                """
                SELECT *
                FROM action_runs
                WHERE state IN ('queued','running','pause_requested','paused','cancel_requested')
                  AND (
                    runner_generation < 1
                    OR runner_token = ''
                    OR runner_lease_expires_at IS NULL
                    OR runner_lease_expires_at <= ?
                  )
                """,
                (now_epoch,),
            ).fetchall()
            for row in rows:
                run_id = str(row["run_id"])
                summary = (
                    "Runner ownership expired before the action run reached a terminal "
                    "state; no undispatched step was resumed."
                )
                plan = _decode_json(row["plan_json"], {})
                current_step = int(row["current_step"] or 0)
                contract = _control_contract(
                    state="interrupted",
                    current_step=current_step,
                    plan=plan if isinstance(plan, Mapping) else {},
                )
                cursor = db.execute(
                    """
                    UPDATE action_runs
                    SET state='interrupted', summary=?, control_state='',
                        updated_at=?, completed_at=?
                    WHERE run_id=?
                      AND state IN ('queued','running','pause_requested','paused','cancel_requested')
                      AND (
                        runner_generation < 1
                        OR runner_token = ''
                        OR runner_lease_expires_at IS NULL
                        OR runner_lease_expires_at <= ?
                      )
                    """,
                    (summary, now, now, run_id, now_epoch),
                )
                if cursor.rowcount != 1:
                    continue
                db.execute(
                    "DELETE FROM action_run_resource_leases WHERE run_id=?",
                    (run_id,),
                )
                db.execute(
                    "INSERT INTO action_run_events(run_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                    (
                        run_id,
                        "run_interrupted",
                        _canonical_json(
                            {
                                "stage": "action",
                                "state": "interrupted",
                                "label": "Action run interrupted after runner lease expiry",
                                "summary": summary,
                                "run_id": run_id,
                                "run_state": "interrupted",
                                **contract,
                            }
                        ),
                        now,
                    ),
                )
                reaped.append(run_id)
            if owned_connection:
                db.commit()
            return tuple(reaped)
        finally:
            if owned_connection:
                db.close()

    def reap_stale_runs(self) -> tuple[str, ...]:
        """Reap expired runner leases and return newly interrupted run IDs."""

        with self._lock:
            return self._reap_stale_runner_leases()

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
        resource_keys = _decode_json(row["resource_keys_json"], [])
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
            resource_keys=(
                tuple(str(item) for item in resource_keys)
                if isinstance(resource_keys, list)
                else ()
            ),
            revision=max(0, int(row["revision"] or 0)),
            last_event_id=max(0, int(row["last_event_id"] or 0)),
            runner_owner_id=str(row["runner_owner_id"] or ""),
            runner_generation=max(0, int(row["runner_generation"] or 0)),
            runner_token=str(row["runner_token"] or ""),
            runner_lease_expires_at=(
                float(row["runner_lease_expires_at"])
                if row["runner_lease_expires_at"] is not None
                else None
            ),
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
        resource_keys: Iterable[str] | str | None = None,
        runner_owner_id: str | None = None,
        runner_lease_seconds: int = DEFAULT_RUNNER_LEASE_SECONDS,
    ) -> tuple[ActionRunSnapshot, bool]:
        normalized_resource_keys = _normalize_resource_keys(resource_keys)
        owner_id = str(runner_owner_id or self._default_runner_owner_id).strip()
        if not owner_id:
            raise ValueError("runner_owner_id must not be empty")
        lease_seconds = _bounded_lease_seconds(runner_lease_seconds)
        now = _utc_now()
        now_epoch = _unix_now()
        lease_expires_at = now_epoch + lease_seconds
        run_id = f"run-{uuid.uuid4().hex[:16]}"
        runner_token = uuid.uuid4().hex
        with self._lock, self._connect() as connection:
            self._begin_immediate(connection)
            self._reap_stale_runner_leases(connection, now_epoch=now_epoch)
            row = connection.execute(
                "SELECT * FROM action_runs WHERE actor=? AND draft_id=? AND plan_hash=?",
                (actor, draft_id, plan_hash),
            ).fetchone()
            if row is not None:
                existing = self._snapshot(row)
                if (
                    normalized_resource_keys
                    and existing.resource_keys != normalized_resource_keys
                ):
                    raise ValueError(
                        "idempotent action-run confirmation supplied different resource keys"
                    )
                return existing, False
            if normalized_resource_keys:
                placeholders = ",".join("?" for _ in normalized_resource_keys)
                conflicts = connection.execute(
                    f"""
                    SELECT resource_key,run_id
                    FROM action_run_resource_leases
                    WHERE resource_key IN ({placeholders})
                    ORDER BY resource_key
                    """,
                    normalized_resource_keys,
                ).fetchall()
                if conflicts:
                    raise ActionRunResourceConflict(
                        {
                            str(row["resource_key"]): str(row["run_id"])
                            for row in conflicts
                        }
                    )
            connection.execute(
                """
                INSERT INTO action_runs(
                    run_id,actor,session_id,draft_id,plan_hash,plan_json,state,
                    current_step,total_steps,summary,result_json,control_state,
                    resource_keys_json,runner_owner_id,runner_generation,runner_token,
                    runner_lease_expires_at,created_at,updated_at,completed_at
                ) VALUES(?,?,?,?,?,?,'queued',0,?,'','{}','',?,?,?,?,?,?,?,NULL)
                """,
                (
                    run_id,
                    actor,
                    session_id,
                    draft_id,
                    plan_hash,
                    _canonical_json(dict(plan)),
                    max(1, int(total_steps)),
                    _canonical_json(list(normalized_resource_keys)),
                    owner_id,
                    1,
                    runner_token,
                    lease_expires_at,
                    now,
                    now,
                ),
            )
            for resource_key in normalized_resource_keys:
                connection.execute(
                    """
                    INSERT INTO action_run_resource_leases(
                        resource_key,run_id,runner_owner_id,runner_generation,
                        runner_token,acquired_at,lease_expires_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        resource_key,
                        run_id,
                        owner_id,
                        1,
                        runner_token,
                        now,
                        lease_expires_at,
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
                            "run_state": "queued",
                            **_control_contract(
                                state="queued",
                                current_step=0,
                                plan=plan,
                            ),
                        }
                    ),
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
            assert row is not None
            return self._snapshot(row), True

    @staticmethod
    def _ownership_from_row(row: sqlite3.Row) -> ActionRunOwnership | None:
        owner_id = str(row["runner_owner_id"] or "")
        token = str(row["runner_token"] or "")
        generation = int(row["runner_generation"] or 0)
        if not owner_id or not token or generation < 1:
            return None
        return ActionRunOwnership(
            run_id=str(row["run_id"]),
            runner_owner_id=owner_id,
            runner_generation=generation,
            runner_token=token,
        )

    def _effective_ownership(
        self,
        row: sqlite3.Row,
        ownership: ActionRunOwnership | None,
    ) -> ActionRunOwnership:
        if ownership is not None:
            return ownership
        stored = self._ownership_from_row(row)
        if stored is None:
            raise ActionRunOwnershipError("action run has no active runner ownership")
        if stored.runner_owner_id != self._default_runner_owner_id:
            raise ActionRunOwnershipError(
                "runner ownership is required for this action run"
            )
        return stored

    @staticmethod
    def _assert_ownership_row(
        row: sqlite3.Row,
        ownership: ActionRunOwnership,
        *,
        now_epoch: float,
    ) -> None:
        if str(row["run_id"]) != ownership.run_id:
            raise ActionRunOwnershipError("ownership token belongs to another action run")
        if str(row["runner_owner_id"] or "") != ownership.runner_owner_id:
            raise ActionRunOwnershipError("runner owner does not match action run")
        if int(row["runner_generation"] or 0) != int(ownership.runner_generation):
            raise ActionRunOwnershipError("runner generation does not match action run")
        if str(row["runner_token"] or "") != ownership.runner_token:
            raise ActionRunOwnershipError("runner ownership token does not match action run")
        expiry = row["runner_lease_expires_at"]
        if expiry is None or float(expiry) <= now_epoch:
            raise ActionRunOwnershipError("runner ownership lease has expired")
        if str(row["state"]) in ACTION_RUN_TERMINAL_STATES:
            raise ActionRunTerminalStateError(
                f"action run is already terminal: {row['state']}"
            )

    def assert_ownership(self, ownership: ActionRunOwnership) -> ActionRunSnapshot:
        """Validate a runner token before a dispatch or event mutation."""

        with self._lock, self._connect() as connection:
            self._begin_immediate(connection)
            now_epoch = _unix_now()
            self._reap_stale_runner_leases(connection, now_epoch=now_epoch)
            row = connection.execute(
                "SELECT * FROM action_runs WHERE run_id=?", (ownership.run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown action run id: {ownership.run_id}")
            self._assert_ownership_row(row, ownership, now_epoch=now_epoch)
            return self._snapshot(row)

    def renew_ownership(
        self,
        ownership: ActionRunOwnership,
        *,
        runner_lease_seconds: int = DEFAULT_RUNNER_LEASE_SECONDS,
    ) -> ActionRunSnapshot:
        """Extend a valid runner lease and its associated resource leases."""

        lease_seconds = _bounded_lease_seconds(runner_lease_seconds)
        now = _utc_now()
        now_epoch = _unix_now()
        lease_expires_at = now_epoch + lease_seconds
        with self._lock, self._connect() as connection:
            self._begin_immediate(connection)
            self._reap_stale_runner_leases(connection, now_epoch=now_epoch)
            row = connection.execute(
                "SELECT * FROM action_runs WHERE run_id=?", (ownership.run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown action run id: {ownership.run_id}")
            self._assert_ownership_row(row, ownership, now_epoch=now_epoch)
            connection.execute(
                """
                UPDATE action_runs
                SET runner_lease_expires_at=?,updated_at=?
                WHERE run_id=? AND runner_generation=?
                """,
                (lease_expires_at, now, ownership.run_id, ownership.runner_generation),
            )
            connection.execute(
                """
                UPDATE action_run_resource_leases
                SET lease_expires_at=?
                WHERE run_id=? AND runner_generation=? AND runner_token=?
                """,
                (
                    lease_expires_at,
                    ownership.run_id,
                    ownership.runner_generation,
                    ownership.runner_token,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM action_runs WHERE run_id=?", (ownership.run_id,)
            ).fetchone()
            assert updated is not None
            return self._snapshot(updated)

    def require(self, run_id: str) -> ActionRunSnapshot:
        with self._lock, self._connect() as connection:
            self._begin_immediate(connection)
            self._reap_stale_runner_leases(connection)
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
            self._begin_immediate(connection)
            self._reap_stale_runner_leases(connection)
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
        ownership: ActionRunOwnership | None = None,
    ) -> ActionRunEvent:
        now = _utc_now()
        with self._lock, self._connect() as connection:
            self._begin_immediate(connection)
            now_epoch = _unix_now()
            self._reap_stale_runner_leases(connection, now_epoch=now_epoch)
            row = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown action run id: {run_id}")
            if str(row["state"]) in ACTION_RUN_TERMINAL_STATES:
                raise ActionRunTerminalStateError(
                    f"action run is already terminal: {row['state']}"
                )
            effective_ownership = self._effective_ownership(row, ownership)
            self._assert_ownership_row(
                row,
                effective_ownership,
                now_epoch=now_epoch,
            )
            if ownership is None:
                # Preserve the legacy store-local API while making its implicit
                # owner behave like a normal heartbeat lease.
                implicit_expiry = now_epoch + DEFAULT_RUNNER_LEASE_SECONDS
                connection.execute(
                    """
                    UPDATE action_runs
                    SET runner_lease_expires_at=?,updated_at=?
                    WHERE run_id=? AND runner_generation=? AND runner_token=?
                    """,
                    (
                        implicit_expiry,
                        now,
                        run_id,
                        effective_ownership.runner_generation,
                        effective_ownership.runner_token,
                    ),
                )
                connection.execute(
                    """
                    UPDATE action_run_resource_leases
                    SET lease_expires_at=?
                    WHERE run_id=? AND runner_generation=? AND runner_token=?
                    """,
                    (
                        implicit_expiry,
                        run_id,
                        effective_ownership.runner_generation,
                        effective_ownership.runner_token,
                    ),
                )
            next_state = str(state or row["state"])
            current_control_state = str(row["control_state"] or "")
            if (
                current_control_state == "cancel_requested"
                and next_state in ACTION_RUN_ACTIVE_STATES
            ):
                next_state = "cancel_requested"
            elif (
                current_control_state == "pause_requested"
                and next_state == "running"
            ):
                next_state = "pause_requested"
            next_step = int(current_step if current_step is not None else row["current_step"] or 0)
            next_summary = str(summary if summary is not None else row["summary"] or "")[:1000]
            next_result = dict(result) if result is not None else _decode_json(row["result_json"], {})
            completed_at = now if next_state in ACTION_RUN_TERMINAL_STATES else row["completed_at"]
            next_control_state = "" if next_state in ACTION_RUN_TERMINAL_STATES else str(row["control_state"] or "")
            plan = _decode_json(row["plan_json"], {})
            safe_payload = dict(payload)
            safe_payload.setdefault("run_id", run_id)
            safe_payload["run_state"] = next_state
            contract = _control_contract(
                state=next_state,
                current_step=next_step,
                plan=plan if isinstance(plan, Mapping) else {},
                step_kind=str(safe_payload.get("step_kind") or ""),
            )
            safe_payload.setdefault("available_controls", contract["available_controls"])
            safe_payload.setdefault(
                "current_step_interruption",
                contract["current_step_interruption"],
            )
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
            self._begin_immediate(connection)
            self._reap_stale_runner_leases(connection)
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
            plan = _decode_json(row["plan_json"], {})
            current_step = int(row["current_step"] or 0)
            contract = _control_contract(
                state=next_state,
                current_step=current_step,
                plan=plan if isinstance(plan, Mapping) else {},
            )
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
                            "run_state": next_state,
                            **contract,
                        }
                    ),
                    now,
                ),
            )
            updated = connection.execute("SELECT * FROM action_runs WHERE run_id=?", (run_id,)).fetchone()
            assert updated is not None
            return self._snapshot(updated)

    def clear_control(
        self,
        run_id: str,
        *,
        state: str = "running",
        ownership: ActionRunOwnership | None = None,
    ) -> ActionRunSnapshot:
        now = _utc_now()
        with self._lock, self._connect() as connection:
            self._begin_immediate(connection)
            now_epoch = _unix_now()
            self._reap_stale_runner_leases(connection, now_epoch=now_epoch)
            row = connection.execute(
                "SELECT * FROM action_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown action run id: {run_id}")
            if str(row["state"]) in ACTION_RUN_TERMINAL_STATES:
                raise ActionRunTerminalStateError(
                    f"action run is already terminal: {row['state']}"
                )
            effective_ownership = self._effective_ownership(row, ownership)
            self._assert_ownership_row(row, effective_ownership, now_epoch=now_epoch)
            connection.execute(
                "UPDATE action_runs SET state=?,control_state='',updated_at=? WHERE run_id=?",
                (state, now, run_id),
            )
            updated = connection.execute(
                "SELECT * FROM action_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            assert updated is not None
        return self._snapshot(updated)
