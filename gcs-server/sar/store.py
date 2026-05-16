# gcs-server/sar/store.py
"""
QuickScout persistent store.

This replaces the earlier in-memory-only mission and finding state for the GCS side
of QuickScout with a small SQLite-backed store. The schema intentionally keeps
the JSON payloads flexible so the subsystem can keep evolving without a large
database migration burden while the feature is still being redesigned.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from sar.schemas import QuickScoutFinding, QuickScoutOperationRecord
from mds_logging import get_logger

logger = get_logger("quickscout_store")

_store_instance: "QuickScoutStore | None" = None
_store_lock = threading.Lock()


def get_quickscout_store() -> "QuickScoutStore":
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = QuickScoutStore()
    return _store_instance


class QuickScoutStore:
    """SQLite-backed durable store for QuickScout operations and findings."""

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or self._resolve_default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._initialize_schema()

    @staticmethod
    def _resolve_default_db_path() -> str:
        env_path = os.environ.get("MDS_QUICKSCOUT_DB_PATH")
        if env_path:
            return env_path

        repo_root = Path(__file__).resolve().parents[2]
        return str(repo_root / "runtime_data" / "quickscout" / "quickscout.sqlite3")

    def _connect(self, *, initialize: bool = True) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db_exists = self.db_path.exists()
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        if initialize and not db_exists:
            self._initialize_schema_on_connection(connection)
        return connection

    def _initialize_schema(self) -> None:
        with self._connect(initialize=False) as connection:
            self._initialize_schema_on_connection(connection)

    @staticmethod
    def _initialize_schema_on_connection(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS quickscout_operations (
                mission_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_quickscout_operations_state
            ON quickscout_operations (state);

            CREATE TABLE IF NOT EXISTS quickscout_findings (
                finding_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                updated_at REAL NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(mission_id) REFERENCES quickscout_operations(mission_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_quickscout_findings_mission
            ON quickscout_findings (mission_id, timestamp);
            """
        )
        legacy_table_exists = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'quickscout_pois'
            """
        ).fetchone()
        if legacy_table_exists:
            connection.execute(
                """
                INSERT OR IGNORE INTO quickscout_findings (
                    finding_id, mission_id, timestamp, updated_at, payload_json
                )
                SELECT
                    poi_id, mission_id, timestamp, updated_at, payload_json
                FROM quickscout_pois
                """
            )

    def save_operation(self, operation: QuickScoutOperationRecord) -> QuickScoutOperationRecord:
        payload = operation.model_dump(mode="json")
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quickscout_operations (
                    mission_id, state, created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mission_id) DO UPDATE SET
                    state = excluded.state,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    operation.mission_id,
                    operation.state.value,
                    float(operation.created_at),
                    float(operation.updated_at),
                    json.dumps(payload, sort_keys=True),
                ),
            )
        return operation

    def get_operation(self, mission_id: str) -> Optional[QuickScoutOperationRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM quickscout_operations WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()

        if row is None:
            return None

        return QuickScoutOperationRecord.model_validate(json.loads(row["payload_json"]))

    def delete_operation(self, mission_id: str) -> bool:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM quickscout_operations WHERE mission_id = ?",
                (mission_id,),
            )
        return cursor.rowcount > 0

    def save_finding(self, mission_id: str, finding: QuickScoutFinding) -> QuickScoutFinding:
        timestamp = float(finding.timestamp or time.time())
        payload = finding.model_dump(mode="json")
        finding_id = payload["id"]
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quickscout_findings (
                    finding_id, mission_id, timestamp, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(finding_id) DO UPDATE SET
                    mission_id = excluded.mission_id,
                    timestamp = excluded.timestamp,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    finding_id,
                    mission_id,
                    timestamp,
                    time.time(),
                    json.dumps(payload, sort_keys=True),
                ),
            )
        return finding

    def list_findings(self, mission_id: str) -> list[QuickScoutFinding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM quickscout_findings
                WHERE mission_id = ?
                ORDER BY timestamp ASC, finding_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [QuickScoutFinding.model_validate(json.loads(row["payload_json"])) for row in rows]

    def get_finding(self, finding_id: str) -> Optional[QuickScoutFinding]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM quickscout_findings WHERE finding_id = ?",
                (finding_id,),
            ).fetchone()
        if row is None:
            return None
        return QuickScoutFinding.model_validate(json.loads(row["payload_json"]))

    def delete_finding(self, finding_id: str) -> bool:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM quickscout_findings WHERE finding_id = ?",
                (finding_id,),
            )
        return cursor.rowcount > 0

    def reset_all(self) -> None:
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM quickscout_findings")
            legacy_table_exists = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'quickscout_pois'
                """
            ).fetchone()
            if legacy_table_exists:
                connection.execute("DELETE FROM quickscout_pois")
            connection.execute("DELETE FROM quickscout_operations")

    def list_operations(self) -> Iterable[QuickScoutOperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM quickscout_operations ORDER BY created_at ASC, mission_id ASC"
            ).fetchall()
        for row in rows:
            yield QuickScoutOperationRecord.model_validate(json.loads(row["payload_json"]))
