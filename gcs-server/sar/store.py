# gcs-server/sar/store.py
"""
QuickScout persistent store.

This replaces the earlier in-memory-only mission and POI state for the GCS side
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

from sar.schemas import POI, QuickScoutOperationRecord
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
    """SQLite-backed durable store for QuickScout operations and POIs."""

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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
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

                CREATE TABLE IF NOT EXISTS quickscout_pois (
                    poi_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES quickscout_operations(mission_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_quickscout_pois_mission
                ON quickscout_pois (mission_id, timestamp);
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

    def save_poi(self, mission_id: str, poi: POI) -> POI:
        timestamp = float(poi.timestamp or time.time())
        payload = poi.model_dump(mode="json")
        poi_id = payload["id"]
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quickscout_pois (
                    poi_id, mission_id, timestamp, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(poi_id) DO UPDATE SET
                    mission_id = excluded.mission_id,
                    timestamp = excluded.timestamp,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    poi_id,
                    mission_id,
                    timestamp,
                    time.time(),
                    json.dumps(payload, sort_keys=True),
                ),
            )
        return poi

    def list_pois(self, mission_id: str) -> list[POI]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM quickscout_pois
                WHERE mission_id = ?
                ORDER BY timestamp ASC, poi_id ASC
                """,
                (mission_id,),
            ).fetchall()
        return [POI.model_validate(json.loads(row["payload_json"])) for row in rows]

    def get_poi(self, poi_id: str) -> Optional[POI]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM quickscout_pois WHERE poi_id = ?",
                (poi_id,),
            ).fetchone()
        if row is None:
            return None
        return POI.model_validate(json.loads(row["payload_json"]))

    def delete_poi(self, poi_id: str) -> bool:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM quickscout_pois WHERE poi_id = ?", (poi_id,))
        return cursor.rowcount > 0

    def reset_all(self) -> None:
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM quickscout_pois")
            connection.execute("DELETE FROM quickscout_operations")

    def list_operations(self) -> Iterable[QuickScoutOperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM quickscout_operations ORDER BY created_at ASC, mission_id ASC"
            ).fetchall()
        for row in rows:
            yield QuickScoutOperationRecord.model_validate(json.loads(row["payload_json"]))
