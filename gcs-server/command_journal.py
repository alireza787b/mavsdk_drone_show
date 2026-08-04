"""Durable single-process command lifecycle journal.

The command tracker keeps a hot in-memory projection for low-latency status
reads.  This module is the durable source of truth used to rebuild that
projection after a GCS restart.  It deliberately does not coordinate multiple
GCS writers; the supported runtime remains one command-owning GCS process.

SQLite WAL transactions persist four safety-critical facts together:

* the immutable command identity and idempotency binding;
* the current command/deadline aggregate;
* per-target preparation, delivery, and execution evidence; and
* an append-only bounded-by-command-history audit event stream.

Callback capabilities are derived from a separate versioned host-local key.
The key is never placed in SQLite, command status, logs, or the repository.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
CALLBACK_KEY_VERSION = 1
DATABASE_FILENAME = "commands.sqlite3"
CALLBACK_KEY_FILENAME = "callback-capability-key.json"


class CommandJournalError(RuntimeError):
    """The durable command journal or callback key is unavailable/corrupt."""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _dataclass_payload(value: Any) -> Any:
    if value is None:
        return None
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Unsupported command journal value: {type(value).__name__}")


def _execution_payload(value: Any) -> Any:
    """Persist lifecycle evidence, not potentially large/sensitive raw stdout."""

    payload = _dataclass_payload(value)
    if payload is not None:
        payload.pop("script_output", None)
    return payload


def _command_payload(command: Any) -> dict[str, Any]:
    """Serialize command-level state without duplicating per-target records."""

    return {
        "command_id": command.command_id,
        "idempotency_key": command.idempotency_key,
        "request_fingerprint": command.request_fingerprint,
        "mission_type": command.mission_type,
        "mission_name": command.mission_name,
        "target_drones": list(command.target_drones),
        "params": dict(command.params),
        "status": _enum_value(command.status),
        "phase": _enum_value(command.phase),
        "outcome": _enum_value(command.outcome) if command.outcome is not None else None,
        "completion_authority": _enum_value(command.completion_authority),
        "completion_discrepancies": dict(command.completion_discrepancies),
        "created_at": command.created_at,
        "updated_at": command.updated_at,
        "preparations_expected": command.preparations_expected,
        "acks_expected": command.acks_expected,
        "executions_expected": command.executions_expected,
        "submitted_at": command.submitted_at,
        "execution_started_at": command.execution_started_at,
        "completed_at": command.completed_at,
        "timeout_at": command.timeout_at,
        "error_summary": command.error_summary,
    }


def _target_payload(command: Any, hw_id: str) -> dict[str, Any]:
    return {
        "preparation": _dataclass_payload(command.preparations.get(hw_id)),
        "ack": _dataclass_payload(command.acks.get(hw_id)),
        "execution_started_at": command.execution_starts.get(hw_id),
        "execution": _execution_payload(command.executions.get(hw_id)),
        "late_ack": _dataclass_payload(command.late_acks.get(hw_id)),
        "late_execution_started_at": command.late_execution_starts.get(hw_id),
        "late_execution": _execution_payload(command.late_executions.get(hw_id)),
        "node_execution_started_at": command.node_execution_starts.get(hw_id),
        "node_execution_report": _execution_payload(command.node_execution_reports.get(hw_id)),
    }


class CommandJournal:
    """Synchronous SQLite journal called while the tracker mutation lock is held."""

    def __init__(self, state_dir: str | os.PathLike[str]) -> None:
        path = Path(state_dir).expanduser()
        if not path.is_absolute():
            raise ValueError("command state directory must be an absolute host-local path")
        self.state_dir = path.resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.state_dir.chmod(0o700)
        except OSError as exc:
            raise CommandJournalError(
                f"Could not secure command state directory {self.state_dir}: {exc}"
            ) from exc

        self.database_path = self.state_dir / DATABASE_FILENAME
        self.callback_key_path = self.state_dir / CALLBACK_KEY_FILENAME
        self._thread_lock = threading.RLock()
        try:
            self._connection = sqlite3.connect(
                str(self.database_path),
                timeout=5.0,
                isolation_level="IMMEDIATE",
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA busy_timeout=5000")
            self._initialize_schema()
            self.database_path.chmod(0o600)
        except (OSError, sqlite3.Error) as exc:
            raise CommandJournalError(
                f"Could not initialize command journal at {self.database_path}: {exc}"
            ) from exc

        self.callback_key_version, self.callback_key = self._load_or_create_callback_key()

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS journal_metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    request_fingerprint TEXT,
                    mission_type INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    outcome TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    submitted_at INTEGER,
                    completed_at INTEGER,
                    timeout_at INTEGER,
                    state_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_commands_deadline
                    ON commands(phase, timeout_at);
                CREATE INDEX IF NOT EXISTS idx_commands_recent
                    ON commands(created_at DESC);

                CREATE TABLE IF NOT EXISTS command_targets (
                    command_id TEXT NOT NULL,
                    hw_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    PRIMARY KEY(command_id, hw_id),
                    FOREIGN KEY(command_id) REFERENCES commands(command_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS command_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_id TEXT NOT NULL,
                    hw_id TEXT,
                    event_type TEXT NOT NULL,
                    occurred_at INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY(command_id) REFERENCES commands(command_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_command_events_command
                    ON command_events(command_id, event_id);
                """
            )
            version_row = self._connection.execute(
                "SELECT value_json FROM journal_metadata WHERE key='schema_version'"
            ).fetchone()
            if version_row is None:
                self._connection.execute(
                    "INSERT INTO journal_metadata(key, value_json) VALUES('schema_version', ?)",
                    (_json_dumps(SCHEMA_VERSION),),
                )
            else:
                try:
                    observed_version = int(json.loads(version_row["value_json"]))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise CommandJournalError("Command journal schema version is corrupt") from exc
                if observed_version != SCHEMA_VERSION:
                    raise CommandJournalError(
                        "Unsupported command journal schema version "
                        f"{observed_version}; expected {SCHEMA_VERSION}"
                    )

    @staticmethod
    def _decode_callback_key(payload: Mapping[str, Any]) -> tuple[int, bytes]:
        try:
            version = int(payload["version"])
            encoded_key = str(payload["key_b64"])
            key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
            key_id = str(payload["key_id"])
        except (KeyError, TypeError, ValueError, UnicodeEncodeError) as exc:
            raise CommandJournalError("Callback capability key file is malformed") from exc
        if version != CALLBACK_KEY_VERSION or len(key) != 32:
            raise CommandJournalError("Callback capability key version or length is unsupported")
        expected_id = hashlib.sha256(key).hexdigest()[:16]
        if not secrets.compare_digest(expected_id, key_id):
            raise CommandJournalError("Callback capability key integrity check failed")
        return version, key

    def _read_callback_key(self) -> tuple[int, bytes]:
        try:
            key_stat = self.callback_key_path.lstat()
            if not stat.S_ISREG(key_stat.st_mode) or self.callback_key_path.is_symlink():
                raise CommandJournalError("Callback capability key must be a regular file")
            if stat.S_IMODE(key_stat.st_mode) & 0o077:
                raise CommandJournalError("Callback capability key permissions must be 0600")
            payload = json.loads(self.callback_key_path.read_text(encoding="utf-8"))
        except CommandJournalError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandJournalError(
                f"Could not read callback capability key {self.callback_key_path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CommandJournalError("Callback capability key file must contain an object")
        return self._decode_callback_key(payload)

    def _load_or_create_callback_key(self) -> tuple[int, bytes]:
        if self.callback_key_path.exists() or self.callback_key_path.is_symlink():
            return self._read_callback_key()

        key = secrets.token_bytes(32)
        payload = {
            "version": CALLBACK_KEY_VERSION,
            "key_id": hashlib.sha256(key).hexdigest()[:16],
            "key_b64": base64.urlsafe_b64encode(key).decode("ascii"),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.callback_key_path, flags, 0o600)
        except FileExistsError:
            return self._read_callback_key()
        except OSError as exc:
            raise CommandJournalError(
                f"Could not create callback capability key {self.callback_key_path}: {exc}"
            ) from exc

        try:
            encoded = (_json_dumps(payload) + "\n").encode("utf-8")
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            directory_fd = os.open(self.state_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise CommandJournalError(
                f"Could not persist callback capability key {self.callback_key_path}: {exc}"
            ) from exc
        return CALLBACK_KEY_VERSION, key

    def save_command(
        self,
        command: Any,
        *,
        stats: Mapping[str, int],
        event_type: str,
        hw_ids: Iterable[str] | None = None,
        event_data: Mapping[str, Any] | None = None,
    ) -> None:
        """Atomically save the aggregate, changed targets, stats, and audit event."""

        command_payload = _command_payload(command)
        normalized_hw_ids = list(dict.fromkeys(str(value) for value in (hw_ids or [])))
        if not normalized_hw_ids and event_type == "created":
            normalized_hw_ids = list(command.target_drones)
        safe_event_data = dict(event_data or {})
        with self._thread_lock:
            try:
                with self._connection:
                    self._connection.execute(
                        """
                        INSERT INTO commands(
                            command_id, idempotency_key, request_fingerprint,
                            mission_type, status, phase, outcome, created_at,
                            updated_at, submitted_at, completed_at, timeout_at,
                            state_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(command_id) DO UPDATE SET
                            idempotency_key=excluded.idempotency_key,
                            request_fingerprint=excluded.request_fingerprint,
                            mission_type=excluded.mission_type,
                            status=excluded.status,
                            phase=excluded.phase,
                            outcome=excluded.outcome,
                            created_at=excluded.created_at,
                            updated_at=excluded.updated_at,
                            submitted_at=excluded.submitted_at,
                            completed_at=excluded.completed_at,
                            timeout_at=excluded.timeout_at,
                            state_json=excluded.state_json
                        """,
                        (
                            command.command_id,
                            command.idempotency_key,
                            command.request_fingerprint,
                            command.mission_type,
                            _enum_value(command.status),
                            _enum_value(command.phase),
                            _enum_value(command.outcome) if command.outcome is not None else None,
                            command.created_at,
                            command.updated_at,
                            command.submitted_at,
                            command.completed_at,
                            command.timeout_at,
                            _json_dumps(command_payload),
                        ),
                    )
                    ordinal_by_hw_id = {
                        hw_id: ordinal for ordinal, hw_id in enumerate(command.target_drones)
                    }
                    for hw_id in normalized_hw_ids:
                        if hw_id not in ordinal_by_hw_id:
                            raise CommandJournalError(
                                f"Cannot persist unexpected target {hw_id} for {command.command_id}"
                            )
                        self._connection.execute(
                            """
                            INSERT INTO command_targets(
                                command_id, hw_id, ordinal, updated_at, state_json
                            ) VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(command_id, hw_id) DO UPDATE SET
                                ordinal=excluded.ordinal,
                                updated_at=excluded.updated_at,
                                state_json=excluded.state_json
                            """,
                            (
                                command.command_id,
                                hw_id,
                                ordinal_by_hw_id[hw_id],
                                command.updated_at,
                                _json_dumps(_target_payload(command, hw_id)),
                            ),
                        )
                    self._connection.execute(
                        """
                        INSERT INTO journal_metadata(key, value_json)
                        VALUES('tracker_stats', ?)
                        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json
                        """,
                        (_json_dumps(dict(stats)),),
                    )
                    self._connection.execute(
                        """
                        INSERT INTO command_events(
                            command_id, hw_id, event_type, occurred_at, data_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            command.command_id,
                            normalized_hw_ids[0] if len(normalized_hw_ids) == 1 else None,
                            event_type,
                            command.updated_at,
                            _json_dumps(safe_event_data),
                        ),
                    )
            except (sqlite3.Error, TypeError, ValueError) as exc:
                raise CommandJournalError(
                    f"Could not persist command {command.command_id}: {exc}"
                ) from exc

    def delete_command(self, command_id: str) -> None:
        with self._thread_lock:
            try:
                with self._connection:
                    self._connection.execute(
                        "DELETE FROM commands WHERE command_id=?",
                        (command_id,),
                    )
            except sqlite3.Error as exc:
                raise CommandJournalError(
                    f"Could not prune command {command_id} from the journal: {exc}"
                ) from exc

    def load(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Load commands in FIFO order plus durable aggregate statistics."""

        with self._thread_lock:
            try:
                command_rows = self._connection.execute(
                    "SELECT command_id, state_json FROM commands ORDER BY created_at, command_id"
                ).fetchall()
                target_rows = self._connection.execute(
                    """
                    SELECT command_id, hw_id, state_json
                    FROM command_targets
                    ORDER BY command_id, ordinal
                    """
                ).fetchall()
                stats_row = self._connection.execute(
                    "SELECT value_json FROM journal_metadata WHERE key='tracker_stats'"
                ).fetchone()
            except sqlite3.Error as exc:
                raise CommandJournalError(f"Could not load command journal: {exc}") from exc

        targets_by_command: dict[str, dict[str, Any]] = {}
        try:
            for row in target_rows:
                targets_by_command.setdefault(row["command_id"], {})[row["hw_id"]] = json.loads(
                    row["state_json"]
                )
            commands = []
            for row in command_rows:
                payload = json.loads(row["state_json"])
                if payload.get("command_id") != row["command_id"]:
                    raise CommandJournalError("Command journal identity mismatch")
                payload["targets"] = targets_by_command.get(row["command_id"], {})
                commands.append(payload)
            stats_payload = json.loads(stats_row["value_json"]) if stats_row is not None else {}
            stats = {str(key): int(value) for key, value in dict(stats_payload).items()}
        except CommandJournalError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CommandJournalError("Command journal contains invalid JSON state") from exc
        return commands, stats

    def close(self) -> None:
        with self._thread_lock:
            self._connection.close()


__all__ = [
    "CALLBACK_KEY_FILENAME",
    "CALLBACK_KEY_VERSION",
    "CommandJournal",
    "CommandJournalError",
    "DATABASE_FILENAME",
    "SCHEMA_VERSION",
]
