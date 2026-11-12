"""Bounded ULog create-request metadata; never stores archive bytes or tokens."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class UlogRequestConflict(ValueError):
    pass


class UlogRequestStorageError(RuntimeError):
    pass


def request_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def native_download_job_id(hw_id: str, request_id: str, access_token: str | None) -> str:
    """An actor capability binds deterministic lookup to this one request."""
    return request_fingerprint({
        "scope": "ulog-download-request-v1", "hw_id": str(hw_id),
        "request_id": request_id,
        "access_hash": hashlib.sha256((access_token or "").encode("utf-8")).hexdigest(),
    })[:32]


def native_rejection_evidence(hw_id: str, log_id: int, request_id: str, access_token: str, message: str) -> dict:
    """Bind pre-acceptance evidence to the existing transient job capability."""
    detail = {
        "code": "ulog_create_rejected", "creation_status": "rejected", "stage": "native_pre_acceptance",
        "hw_id": str(hw_id), "log_id": int(log_id), "request_id": request_id,
        "node_job_id": native_download_job_id(hw_id, request_id, access_token), "message": str(message)[:1024],
    }
    detail["rejection_proof"] = hmac.new(access_token.encode(), request_fingerprint(detail).encode(), hashlib.sha256).hexdigest()
    return detail


def verify_native_rejection(detail: Any, hw_id: str, log_id: int, request_id: str, access_token: str) -> bool:
    if not isinstance(detail, dict) or not isinstance(detail.get("message"), str):
        return False
    proof = detail.get("rejection_proof")
    if not isinstance(proof, str) or len(proof) != 64 or any(char not in "0123456789abcdef" for char in proof):
        return False
    expected = native_rejection_evidence(hw_id, log_id, request_id, access_token, detail["message"])
    return all(detail.get(key) == value for key, value in expected.items() if key != "rejection_proof") and hmac.compare_digest(
        proof, expected["rejection_proof"],
    )


class UlogRequestReceiptStore:
    """One small SQLite table. Existing identities never get recycled at capacity."""

    def __init__(self, path: Path, *, max_bytes: int = 16 * 1024 * 1024, max_records: int = 1024) -> None:
        if not path.is_absolute():
            raise UlogRequestStorageError("ULog request receipt path must be absolute")
        self.path = path
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self.max_records = max(1, int(max_records))
        self._lock = threading.RLock()
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not stat.S_ISDIR(path.parent.lstat().st_mode):
                raise UlogRequestStorageError("ULog receipt directory is not a regular directory")
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                    raise UlogRequestStorageError("ULog request receipt file has an unsafe identity")
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            with self._connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("""CREATE TABLE IF NOT EXISTS ulog_requests (
                    scope TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    PRIMARY KEY(scope, request_id)
                )""")
        except (OSError, sqlite3.Error) as exc:
            raise UlogRequestStorageError("ULog request receipt storage is unavailable") from exc

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute(f"PRAGMA max_page_count={max(16, self.max_bytes // 4096)}")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 8192:
            raise UlogRequestStorageError("ULog request receipt metadata exceeds its bounded size")
        return encoded

    def get(self, scope: str, request_id: str) -> dict[str, Any] | None:
        try:
            with self._lock, self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM ulog_requests WHERE scope = ? AND request_id = ?",
                    (scope, request_id),
                ).fetchone()
                return json.loads(row[0]) if row else None
        except sqlite3.Error as exc:
            raise UlogRequestStorageError("ULog request receipt lookup is unavailable") from exc

    def claim(self, scope: str, request_id: str, fingerprint: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        encoded = self._encode(payload)
        try:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT fingerprint, payload FROM ulog_requests WHERE scope = ? AND request_id = ?",
                    (scope, request_id),
                ).fetchone()
                if row:
                    if row[0] != fingerprint:
                        raise UlogRequestConflict("Request identity is already bound to a different ULog download")
                    return json.loads(row[1]), False
                count = db.execute("SELECT COUNT(*) FROM ulog_requests").fetchone()[0]
                disk_bytes = sum(p.stat().st_size for p in (self.path, Path(str(self.path) + "-wal")) if p.exists())
                # Reserve each accepted request's entire bounded final metadata
                # envelope, including SQLite/WAL overhead, before native create.
                if count >= self.max_records or max(disk_bytes, (count + 1) * 16_384) > self.max_bytes:
                    raise UlogRequestStorageError(
                        "ULog request receipt capacity reached; operator maintenance is required. Existing receipts remain readable."
                    )
                now = int(time.time() * 1000)
                db.execute("INSERT INTO ulog_requests VALUES (?, ?, ?, ?, ?, ?)",
                           (scope, request_id, fingerprint, encoded, now, now))
                return payload, True
        except sqlite3.Error as exc:
            raise UlogRequestStorageError("ULog request receipt could not be accepted; no new download was submitted") from exc

    def update(self, scope: str, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = self._encode(payload)
        try:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT payload FROM ulog_requests WHERE scope = ? AND request_id = ?", (scope, request_id)).fetchone()
                if row:
                    current = json.loads(row[0])
                    if current.get("status") in {"accepted", "rejected"}:
                        return current  # Terminal evidence never regresses in a late-response race.
                db.execute("UPDATE ulog_requests SET payload = ?, updated_at = ? WHERE scope = ? AND request_id = ?",
                           (encoded, int(time.time() * 1000), scope, request_id))
            with self._lock, self._connect() as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return payload
        except sqlite3.Error as exc:
            raise UlogRequestStorageError("ULog request receipt update is unavailable; do not resubmit creation") from exc
