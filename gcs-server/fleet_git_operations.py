"""Receipts for reviewed Git updates. Only a live worker can hold the fleet write lease."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

REVIEW_TTL_MS = 300_000
RETENTION_MS = 7 * 24 * 3600 * 1000
ACTIVE_PHASES = {"applying", "verifying"}


class AircraftUpdate(BaseModel):
    hw_id: str
    pos_id: int
    state: Literal["ready", "blocked", "applying", "verifying", "verified", "unconfirmed"]
    error_code: str | None


class UpdateCounts(BaseModel):
    total: int
    ready: int
    blocked: int
    verified: int
    unconfirmed: int


class GitUpdateStatus(BaseModel):
    operation_id: str
    preview_id: str
    phase: Literal["review", "applying", "verifying", "completed", "partial", "failed", "interrupted", "expired"]
    target_branch: str
    target_commit: str
    started_at: int
    updated_at: int
    completed_at: int | None
    target_counts: UpdateCounts
    per_aircraft_state: dict[str, AircraftUpdate]
    message: str
    error_code: str | None


def now_ms():
    return int(time.time() * 1000)


def update_phase(record, phase, message, *, error_code=None, verified=()):
    """Only advance confirmed aircraft. Later interruption retains their evidence."""
    status = record["status"]
    timestamp = now_ms()
    terminal = phase not in ACTIVE_PHASES and phase != "review"
    status.update(phase=phase, updated_at=timestamp, completed_at=timestamp if terminal else None,
                  message=message, error_code=error_code)
    verified = set(verified)
    for hw_id, aircraft in status["per_aircraft_state"].items():
        if aircraft["state"] in {"blocked", "verified"}:
            continue
        if hw_id in verified:
            aircraft.update(state="verified", error_code=None)
        elif phase in ACTIVE_PHASES:
            aircraft.update(state=phase)
        elif terminal and phase != "expired":
            aircraft.update(state="unconfirmed", error_code=error_code or "verification_timeout")
    states = [row["state"] for row in status["per_aircraft_state"].values()]
    status["target_counts"] = {
        "total": len(states), "ready": len(states) - states.count("blocked"), "blocked": states.count("blocked"),
        "verified": states.count("verified"), "unconfirmed": states.count("unconfirmed"),
    }


class GitOperationStore:
    def __init__(self, params):
        state_dir = Path(params.GCS_COMMAND_STATE_DIR)
        if not state_dir.is_absolute():
            raise ValueError("Git operation state directory must be absolute")
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        binding = [str(Path(__file__).resolve().parents[1]), str(getattr(params, "runtime_mode", "")),
                   str(getattr(params, "gcs_api_port", ""))]
        scope = hashlib.sha256(json.dumps(binding).encode()).hexdigest()[:16]
        self.path = state_dir / f"fleet-git-{scope}.sqlite3"
        self.lease_path = self.path.with_suffix(".lock")
        os.close(os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600))
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, updated_at INTEGER NOT NULL, record TEXT NOT NULL
            )""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5, isolation_level=None)

    def try_lease(self):
        # An OS lease survives a browser disconnect and is released on GCS process exit.
        fd = os.open(self.lease_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd

    def create(self, preview):
        public = {
            "operation_id": preview["job_id"], "preview_id": preview["job_id"],
            "target_branch": preview["target_branch"], "target_commit": preview["target_commit"],
            "started_at": preview["created_at"],
            "per_aircraft_state": {hw: {"hw_id": hw, "pos_id": r["pos_id"],
                                        "state": "ready" if r["ok"] else "blocked",
                                        "error_code": r.get("error_code")} for hw, r in preview["results"].items()},
        }
        record = {"status": public, "targets": preview["targets"],
                  "proof": hashlib.sha256(preview["confirmation_token"].encode()).hexdigest()}
        update_phase(record, "review", "Review aircraft")
        with closing(self._connect()) as db:
            db.execute("DELETE FROM operations WHERE updated_at < ?", (now_ms() - RETENTION_MS,))
            db.execute("INSERT INTO operations VALUES (?, ?, ?)",
                       (preview["job_id"], public["updated_at"], json.dumps(record)))
        return public

    def read(self, operation_id):
        with closing(self._connect()) as db:
            row = db.execute("SELECT record FROM operations WHERE id = ?", (operation_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Sync operation was not found")
        return json.loads(row[0])

    def save(self, record):
        status = record["status"]
        with closing(self._connect()) as db:
            db.execute("UPDATE operations SET updated_at=?,record=? WHERE id=?",
                       (status["updated_at"], json.dumps(record), status["operation_id"]))

    def reconcile(self, record):
        """Called only inside the writer lease, hence a recorded active operation has lost its worker."""
        status = record["status"]
        if status["phase"] in ACTIVE_PHASES:
            update_phase(record, "interrupted", "Update interrupted. Check aircraft software.", error_code="gcs_interrupted")
            self.save(record)
        elif status["phase"] == "review" and now_ms() - status["started_at"] >= REVIEW_TTL_MS:
            update_phase(record, "expired", "Preview expired. Review aircraft again.", error_code="preview_expired")
            self.save(record)
        return record

    def lookup(self, operation_id):
        record = self.read(operation_id)
        status = record["status"]
        if status["phase"] in ACTIVE_PHASES or (status["phase"] == "review" and now_ms() - status["started_at"] >= REVIEW_TTL_MS):
            lease = self.try_lease()
            if lease is not None:
                try:
                    return self.reconcile(self.read(operation_id))
                finally:
                    os.close(lease)
        return record
