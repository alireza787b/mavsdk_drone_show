"""Durable native receipts. An interrupted write is lookup-only, never replayed."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from src.px4_param_models import Px4ParamPatchApplyResponse


class Px4ParamOperationStore:
    """Bounded, fail-closed receipt journal; identities are not evicted for reuse."""

    def __init__(self, directory: Path, hw_id: str, *, max_records: int = 4096, max_bytes: int = 64 * 1024 * 1024):
        identity = hashlib.sha256(hw_id.encode()).hexdigest()[:24]
        self.path = directory / f"native-{identity}.sqlite3"
        self.max_records = max_records
        self.max_bytes = max_bytes

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            connection.execute(f"PRAGMA max_page_count={max(1, self.max_bytes // page_size)}")
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS operations "
                    "(operation_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT NOT NULL, "
                    "reserved_bytes INTEGER NOT NULL DEFAULT 0)"
                )
                columns = {row[1] for row in connection.execute("PRAGMA table_info(operations)")}
                if "reserved_bytes" not in columns:
                    connection.execute("ALTER TABLE operations ADD COLUMN reserved_bytes INTEGER NOT NULL DEFAULT 0")
                yield connection
        finally:
            connection.close()

    def lookup(self, operation_id: str, fingerprint: str):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT fingerprint, response FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise ValueError("operation_id already belongs to a different PX4 parameter request")
        return Px4ParamPatchApplyResponse.model_validate(json.loads(row[1]))

    def begin(self, operation_id: str, fingerprint: str, response: Px4ParamPatchApplyResponse):
        payload = response.model_dump_json()
        # Reserve the worst-case bounded actual value/error text for every row,
        # before any mutation. Completed receipt writes use that same reservation.
        # A JSON-escaped control character can use six bytes, more than UTF-8.
        reserved_bytes = len(payload.encode()) + len(response.results) * (2048 * 6 + 1024 * 6 + 256)
        with self._connect() as connection:
            if connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] >= self.max_records:
                raise RuntimeError("PX4 parameter receipt journal is full; no write attempted")
            reserved = connection.execute(
                "SELECT COALESCE(SUM(MAX(reserved_bytes, length(CAST(response AS BLOB)))), 0) FROM operations"
            ).fetchone()[0]
            physical_bytes = connection.execute("PRAGMA page_count").fetchone()[0] * connection.execute("PRAGMA page_size").fetchone()[0]
            if max(reserved, physical_bytes) + reserved_bytes + 32768 > self.max_bytes:
                raise RuntimeError("PX4 parameter receipt journal storage capacity reached; no write attempted")
            connection.execute(
                "INSERT INTO operations (operation_id, fingerprint, response, reserved_bytes) VALUES (?, ?, ?, ?)",
                (operation_id, fingerprint, payload, reserved_bytes),
            )

    def save(self, operation_id: str, response: Px4ParamPatchApplyResponse):
        payload = response.model_dump_json()
        with self._connect() as connection:
            reserved = connection.execute(
                "SELECT reserved_bytes FROM operations WHERE operation_id=?", (operation_id,),
            ).fetchone()
            if reserved is None or len(payload.encode()) > reserved[0]:
                raise RuntimeError("PX4 parameter receipt exceeds its reserved storage capacity")
            connection.execute(
                "UPDATE operations SET response=? WHERE operation_id=?",
                (payload, operation_id),
            )
