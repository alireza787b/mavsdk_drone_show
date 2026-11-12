"""Small single-GCS SQLite/WAL journal; never a vehicle writer or flight tracker."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ParamJobConflict(ValueError):
    pass


class ParamJobJournal:
    def __init__(self, state_dir: str, runtime_binding: str, *, max_bytes: int = 64 * 1024 * 1024) -> None:
        path = Path(state_dir).expanduser()
        if not path.is_absolute():
            raise ValueError("Parameter receipt state directory must be absolute")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = path / "px4-parameters.sqlite3"
        self.runtime_binding = runtime_binding
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        self.path.chmod(0o600)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS param_reviews (
                review_id TEXT PRIMARY KEY, runtime_binding TEXT NOT NULL,
                review_hash TEXT NOT NULL, expires_at INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS param_jobs (
                job_id TEXT PRIMARY KEY, runtime_binding TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                review_id TEXT NOT NULL REFERENCES param_reviews(review_id),
                payload TEXT NOT NULL,
                UNIQUE(runtime_binding, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS param_job_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES param_jobs(job_id),
                created_at INTEGER NOT NULL, event_type TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS param_job_reservations (
                job_id TEXT PRIMARY KEY REFERENCES param_jobs(job_id),
                reserved_bytes INTEGER NOT NULL
            );
        """)
        self._db.commit()
        self._fence_interrupted_jobs()

    def _require_capacity(self, needed: int) -> None:
        disk_bytes = sum(
            path.stat().st_size for path in (self.path, Path(str(self.path) + "-wal")) if path.exists()
        )
        reserved = self._db.execute("SELECT COALESCE(SUM(reserved_bytes), 0) FROM param_job_reservations").fetchone()[0]
        if disk_bytes + reserved + needed > self.max_bytes:
            raise ParamJobConflict(
                "Parameter receipt storage capacity reached; operator maintenance is required. "
                "Existing receipts remain readable; no new write was accepted."
            )

    def _checkpoint(self) -> None:
        # A single GCS owns this journal. Short reads do not hold snapshots;
        # truncating committed WAL prevents repeated receipt updates accumulating.
        self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _fence_interrupted_jobs(self) -> None:
        """Restart is not permission to replay a possibly delivered write."""
        with self._lock, self._db:
            rows = self._db.execute(
                "SELECT job_id, payload FROM param_jobs WHERE runtime_binding = ?",
                (self.runtime_binding,),
            ).fetchall()
            for job_id, raw in rows:
                payload = json.loads(raw)
                if payload.get("terminal"):
                    continue
                for target in payload["results"]:
                    if target["outcome"] == "pending":
                        target.update(outcome="not_attempted", error="GCS restarted before dispatch")
                    elif target["outcome"] == "running":
                        target.update(outcome="unknown", error="GCS restarted during dispatch; do not replay")
                payload.update(
                    status="unknown" if any(t["outcome"] == "unknown" for t in payload["results"]) else "failed",
                    terminal=True,
                    unknown_targets=sum(t["outcome"] == "unknown" for t in payload["results"]),
                    failed_targets=sum(not t["verified"] for t in payload["results"]),
                    completed_targets=len(payload["results"]),
                    completed_at=int(time.time() * 1000),
                    updated_at=int(time.time() * 1000),
                )
                self._write_job(payload, "restart_fenced")

    def save_review(self, review: dict[str, Any], dispatch: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM param_reviews WHERE expires_at < ? AND review_id NOT IN (SELECT review_id FROM param_jobs)",
                (int(time.time() * 1000),),
            )
            count = self._db.execute("SELECT COUNT(*) FROM param_reviews").fetchone()[0]
            if count >= 4096:
                raise ParamJobConflict("Parameter review history is full; operator maintenance is required")
            payload = canonical_json({"review": review, "dispatch": dispatch})
            self._require_capacity(len(payload.encode("utf-8")) * 2 + 16_384)
            self._db.execute(
                "INSERT INTO param_reviews VALUES (?, ?, ?, ?, ?)",
                (review["review_id"], self.runtime_binding, review["review_hash"], review["expires_at"],
                 payload),
            )
        with self._lock:
            self._checkpoint()

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM param_reviews WHERE review_id = ? AND runtime_binding = ?",
                (review_id, self.runtime_binding),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM param_jobs WHERE job_id = ? AND runtime_binding = ?",
                (job_id, self.runtime_binding),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def find_request(self, key: str, fingerprint: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT fingerprint, payload FROM param_jobs WHERE idempotency_key = ? AND runtime_binding = ?",
                (key, self.runtime_binding),
            ).fetchone()
            if row and fingerprint is not None and row[0] != fingerprint:
                raise ParamJobConflict("Idempotency key is already bound to a different parameter request")
            return json.loads(row[1]) if row else None

    def accept(self, job: dict[str, Any], fingerprint: str) -> tuple[dict[str, Any], bool]:
        with self._lock, self._db:
            existing = self.find_request(job["idempotency_key"], fingerprint)
            if existing:
                return existing, False
            review = self.get_review(job["review_id"])
            entry_count = sum(len(target["entries"]) for target in review["dispatch"].values())
            # Reserve for bounded native per-entry receipts and update/WAL
            # overhead before accepting any writer. Error strings are bounded
            # by the runner before persistence.
            reservation = (
                len(canonical_json(job).encode("utf-8")) * 4
                + len(canonical_json(review["dispatch"]).encode("utf-8")) * 4
                + entry_count * 8192 + len(job["results"]) * 4096
            )
            self._require_capacity(reservation)
            self._db.execute(
                "INSERT INTO param_jobs VALUES (?, ?, ?, ?, ?, ?)",
                (job["job_id"], self.runtime_binding, job["idempotency_key"], fingerprint,
                 job["review_id"], canonical_json(job)),
            )
            self._db.execute("INSERT INTO param_job_reservations VALUES (?, ?)", (job["job_id"], reservation))
            self._event(job, "accepted")
            return job, True

    def _event(self, job: dict[str, Any], kind: str) -> None:
        self._db.execute(
            "INSERT INTO param_job_events(job_id, created_at, event_type, payload) VALUES (?, ?, ?, ?)",
            (job["job_id"], int(time.time() * 1000), kind,
             canonical_json({"status": job["status"], "outcomes": {t["hw_id"]: t["outcome"] for t in job["results"]}})),
        )

    def _write_job(self, job: dict[str, Any], kind: str) -> None:
        self._db.execute(
            "UPDATE param_jobs SET payload = ? WHERE job_id = ? AND runtime_binding = ?",
            (canonical_json(job), job["job_id"], self.runtime_binding),
        )
        self._event(job, kind)
        if job.get("terminal"):
            self._db.execute("DELETE FROM param_job_reservations WHERE job_id = ?", (job["job_id"],))

    def save_job(self, job: dict[str, Any], kind: str) -> None:
        with self._lock, self._db:
            self._write_job(job, kind)
        with self._lock:
            self._checkpoint()

    def close(self) -> None:
        with self._lock:
            self._db.close()
