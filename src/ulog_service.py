"""Drone-local onboard ULog access helpers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import shutil
import stat
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO, Optional

from mavsdk.log_files import Entry as MavsdkLogEntry
from mavsdk.log_files import LogFilesError, LogFilesResult

from mds_logging.api_schemas import (
    OnboardUlogDownloadJob,
    OnboardUlogDownloadJobResponse,
    OnboardUlogDownloadRequest,
    OnboardUlogEntry,
    OnboardUlogEraseAllResponse,
    OnboardUlogCapability,
    OnboardUlogListResponse,
    OnboardUlogPolicy,
    OnboardUlogPolicyResponse,
    OnboardUlogSummaryResponse,
)
from src.ulog_transfer_policy import (
    ulog_download_aggregate_max_bytes,
    ulog_download_idle_timeout_seconds,
    ulog_download_max_bytes,
    ulog_download_min_free_bytes,
    ulog_download_timeout_seconds,
)


class UlogServiceError(Exception):
    """Typed service error metadata for HTTP and proxy adapters."""

    code = "ulog_service_error"
    http_status = 500
    retryable = False

    def __init__(self, message: str) -> None:
        self.message = str(message)
        super().__init__(self.message)


class UlogNotFoundError(UlogServiceError, FileNotFoundError):
    code = "ulog_not_found"
    http_status = 404


class UlogUnsafePathError(UlogServiceError, RuntimeError):
    code = "ulog_unsafe_path"
    http_status = 409


class UlogJobConflictError(UlogServiceError, RuntimeError):
    code = "ulog_job_conflict"
    http_status = 409


class UlogCapacityError(UlogServiceError, RuntimeError):
    code = "ulog_capacity_exceeded"
    http_status = 429
    retryable = True


class UlogStorageError(UlogServiceError, RuntimeError):
    code = "ulog_storage_unavailable"
    http_status = 507
    retryable = True


class UlogSizeLimitError(UlogServiceError, ValueError):
    code = "ulog_size_limit_exceeded"
    http_status = 413


class UlogTransportUnavailableError(UlogServiceError):
    """The node-local MAVSDK/PX4 transport could not serve a ULog operation."""

    code = "ulog_transport_unavailable"
    http_status = 503
    retryable = True

    def __init__(self, message: str, *, stage: str) -> None:
        self.stage = str(stage)
        super().__init__(message)


class UlogTransportTimeoutError(UlogTransportUnavailableError):
    """A bounded node-local ULog transport setup stage timed out."""

    code = "ulog_transport_timeout"
    http_status = 504

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        timeout_seconds: float,
    ) -> None:
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(message, stage=stage)


@dataclass(frozen=True)
class _IndexedUlogFile:
    path: Path
    root: Path
    device: int
    inode: int
    size_bytes: int
    mtime_ns: int
    ctime_ns: int


class OnboardUlogService:
    """Manage onboard PX4 ULog discovery and short-lived staged downloads."""

    def __init__(self, params: Any, *, hw_id: str, pos_id: int | None = None) -> None:
        self.params = params
        self.hw_id = str(hw_id)
        self.pos_id = pos_id if pos_id is None else int(pos_id)
        self._jobs: dict[str, OnboardUlogDownloadJob] = {}
        self._job_paths: dict[str, Path] = {}
        self._job_access_hashes: dict[str, str] = {}
        self._job_fallback_files: dict[str, _IndexedUlogFile] = {}
        self._job_reserved_bytes: dict[str, int] = {}
        self._job_stage_identities: dict[str, tuple[int, int]] = {}
        self._active_job_ids: set[str] = set()
        self._fallback_entries: dict[int, _IndexedUlogFile] = {}
        self._lock = asyncio.Lock()
        self._cleanup_orphaned_stage_files()

    def build_policy(
        self,
        *,
        ulog_capability: OnboardUlogCapability | dict[str, Any] | None = None,
    ) -> OnboardUlogPolicyResponse:
        return OnboardUlogPolicyResponse(
            hw_id=self.hw_id,
            pos_id=self.pos_id,
            policy=self._build_policy_payload(),
            ulog_capability=ulog_capability,
            timestamp=self._now_ms(),
        )

    async def list_entries(self, drone: Any, *, pos_id: int | None = None) -> OnboardUlogListResponse:
        entries = await self._fetch_entries(drone)
        return OnboardUlogListResponse(
            hw_id=self.hw_id,
            pos_id=self._resolve_pos_id(pos_id),
            count=len(entries),
            files=entries,
            policy=self._build_policy_payload(),
            ulog_capability=None,
            timestamp=self._now_ms(),
        )

    async def create_download_job(
        self,
        drone: Any,
        log_id: int,
        request: OnboardUlogDownloadRequest,
        *,
        access_token: str | None = None,
    ) -> OnboardUlogDownloadJobResponse:
        entries = await self._fetch_entries(drone)
        entry = next((candidate for candidate in entries if candidate.id == int(log_id)), None)
        if entry is None:
            raise UlogNotFoundError(f"Onboard ULog {log_id} not found")
        if int(entry.size_bytes) > ulog_download_max_bytes():
            raise UlogSizeLimitError(
                f"Onboard ULog {log_id} exceeds MDS_ULOG_DOWNLOAD_MAX_BYTES "
                f"({ulog_download_max_bytes()} bytes)"
            )

        pos_id = self._resolve_pos_id(request.pos_id)
        internal_name = f"{self.hw_id}-{uuid.uuid4().hex[:12]}.ulg"
        stage_path = self._stage_dir() / internal_name
        download_name = self._build_download_filename(entry, pos_id=pos_id)
        now_ms = self._now_ms()
        expires_at = now_ms + int(self._safe_float("ULOG_DOWNLOAD_JOB_TTL_SEC", 1800.0) * 1000)

        job = OnboardUlogDownloadJob(
            job_id=uuid.uuid4().hex,
            hw_id=self.hw_id,
            pos_id=pos_id,
            log_id=entry.id,
            date_utc=entry.date_utc,
            size_bytes=entry.size_bytes,
            status="queued",
            progress=0.0,
            staged_filename=internal_name,
            download_filename=download_name,
            created_at=now_ms,
            updated_at=now_ms,
            expires_at=expires_at,
            error=None,
        )

        async with self._lock:
            self._cleanup_expired_jobs_locked(now_ms)
            expected_size = (
                int(entry.size_bytes)
                if int(entry.size_bytes) > 0
                else ulog_download_max_bytes()
            )
            self._make_job_capacity_locked(
                expected_size=expected_size,
                stage_dir=stage_path.parent,
            )
            self._jobs[job.job_id] = job
            self._job_paths[job.job_id] = stage_path
            self._job_reserved_bytes[job.job_id] = expected_size
            if access_token:
                self._job_access_hashes[job.job_id] = self._hash_access_token(access_token)
            fallback_file = self._fallback_entries.get(int(entry.id))
            if fallback_file is not None:
                self._job_fallback_files[job.job_id] = fallback_file
            self._trim_job_count_locked()
            return OnboardUlogDownloadJobResponse(job=job.model_copy(deep=True), timestamp=now_ms)

    async def authorize_job(self, job_id: str, access_token: str | None) -> bool:
        """Validate the transient capability assigned to one raw-download job."""

        if not access_token:
            return False
        async with self._lock:
            expected = self._job_access_hashes.get(str(job_id))
        if not expected:
            return False
        return hmac.compare_digest(expected, self._hash_access_token(access_token))

    async def get_job(self, job_id: str) -> Optional[OnboardUlogDownloadJobResponse]:
        now_ms = self._now_ms()
        async with self._lock:
            self._cleanup_expired_jobs_locked(now_ms)
            job = self._jobs.get(str(job_id))
            if job is None:
                return None
            return OnboardUlogDownloadJobResponse(job=job.model_copy(deep=True), timestamp=now_ms)

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            normalized_job_id = str(job_id)
            job = self._jobs.get(normalized_job_id)
            if job is None:
                return False
            if normalized_job_id in self._active_job_ids or job.status == "downloading":
                raise UlogJobConflictError(
                    f"ULog download job {normalized_job_id} is active and cannot be deleted"
                )
            return self._delete_job_locked(normalized_job_id)

    async def cleanup_expired_jobs(self) -> int:
        """Remove expired terminal or abandoned jobs without a background daemon."""

        async with self._lock:
            return self._cleanup_expired_jobs_locked(self._now_ms())

    async def mark_job_failed(self, job_id: str, error: str) -> Optional[OnboardUlogDownloadJobResponse]:
        async with self._lock:
            current = self._jobs.get(str(job_id))
            if current is None:
                return None
            stage_path = self._job_paths.get(str(job_id))
            cleanup_error: UlogServiceError | None = None
            if stage_path is not None:
                try:
                    self._unlink_stage_file(stage_path, missing_ok=True)
                except UlogServiceError as exc:
                    cleanup_error = exc
            current.status = "failed"
            current.error = self._job_failure_message(error, cleanup_error)
            current.progress = 0.0
            current.updated_at = self._now_ms()
            return OnboardUlogDownloadJobResponse(
                job=current.model_copy(deep=True),
                timestamp=current.updated_at,
            )

    async def perform_download(self, drone: Any, job_id: str) -> OnboardUlogDownloadJobResponse:
        job_id = str(job_id)
        async with self._lock:
            self._cleanup_expired_jobs_locked(self._now_ms())
            job = self._jobs.get(job_id)
            stage_path = self._job_paths.get(job_id)
            if job is None or stage_path is None:
                raise UlogNotFoundError(f"ULog download job {job_id} not found")
            if job_id in self._active_job_ids or job.status != "queued":
                raise UlogJobConflictError(
                    f"ULog download job {job_id} cannot start from status {job.status}"
                )
            self._active_job_ids.add(job_id)
            job.status = "downloading"
            job.progress = 0.0
            job.error = None
            job.updated_at = self._now_ms()
            fallback_file = self._job_fallback_files.get(job_id)

        stage_identity: tuple[int, int] | None = None
        try:
            if fallback_file is not None:
                stage_identity = self._prepare_stage_file(stage_path)
                async with self._lock:
                    self._job_stage_identities[job_id] = stage_identity
            else:
                # MAVSDK creates the destination itself and rejects an existing
                # file with INVALID_ARGUMENT. Keep the random destination absent
                # until MAVSDK opens it, then pin the created inode below.
                self._prepare_stage_destination(stage_path)

            async def _capture_downloaded_stage_identity() -> tuple[int, int]:
                nonlocal stage_identity
                if stage_identity is None:
                    stage_identity = self._capture_stage_file_identity(stage_path)
                    async with self._lock:
                        current = self._jobs.get(job_id)
                        if current is None:
                            raise UlogNotFoundError(
                                f"ULog download job {job_id} disappeared"
                            )
                        self._job_stage_identities[job_id] = stage_identity
                return stage_identity

            async def _download() -> None:
                if fallback_file is not None:
                    if stage_identity is None:  # pragma: no cover - defensive invariant
                        raise UlogUnsafePathError(
                            f"ULog download job {job_id} has no trusted staging identity"
                        )
                    await asyncio.to_thread(
                        self._copy_file_bounded,
                        fallback_file,
                        stage_path,
                        stage_identity,
                        ulog_download_max_bytes(),
                    )
                    async with self._lock:
                        current = self._jobs.get(job_id)
                        if current is not None:
                            staged_size = self._stage_file_stat(
                                stage_path,
                                expected_identity=stage_identity,
                            ).st_size
                            self._update_job_reservation_locked(job_id, staged_size)
                            current.status = "downloading"
                            current.progress = 1.0
                            current.updated_at = self._now_ms()
                    return

                entry = await self._resolve_download_entry(drone, job)
                progress_stream = drone.log_files.download_log_file(entry, str(stage_path))
                iterator = progress_stream.__aiter__()
                while True:
                    try:
                        progress = await asyncio.wait_for(
                            iterator.__anext__(),
                            timeout=ulog_download_idle_timeout_seconds(),
                        )
                    except StopAsyncIteration:
                        break
                    current_identity = await _capture_downloaded_stage_identity()
                    staged_size = self._assert_staged_size(
                        stage_path,
                        expected_identity=current_identity,
                    )
                    self._assert_free_space_reserve(stage_path.parent)
                    async with self._lock:
                        current = self._jobs.get(job_id)
                        if current is None:
                            raise UlogNotFoundError(
                                f"ULog download job {job_id} disappeared"
                            )
                        self._update_job_reservation_locked(job_id, staged_size)
                        current.status = "downloading"
                        current.progress = max(0.0, min(1.0, float(progress.progress)))
                        current.updated_at = self._now_ms()

                # A conforming downloader normally yields progress, but a
                # completed zero-event stream must still produce and pin a file.
                await _capture_downloaded_stage_identity()

            await asyncio.wait_for(
                _download(),
                timeout=ulog_download_timeout_seconds(),
            )

            if stage_identity is None:  # pragma: no cover - defensive invariant
                raise UlogUnsafePathError(
                    f"ULog download job {job_id} has no trusted staging identity"
                )
            staged_size = self._assert_staged_size(
                stage_path,
                expected_identity=stage_identity,
            )
            self._assert_free_space_reserve(stage_path.parent)
            os.chmod(stage_path, 0o600, follow_symlinks=False)
            async with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    raise UlogNotFoundError(f"ULog download job {job_id} disappeared")
                self._set_job_reservation_locked(job_id, staged_size)
                current.status = "ready"
                current.progress = 1.0
                current.size_bytes = staged_size
                current.updated_at = self._now_ms()
                return OnboardUlogDownloadJobResponse(job=current.model_copy(deep=True), timestamp=current.updated_at)
        except Exception as exc:
            cleanup_error: UlogServiceError | None = None
            try:
                self._unlink_stage_file(stage_path, missing_ok=True)
            except UlogServiceError as stage_cleanup_error:
                cleanup_error = stage_cleanup_error
            async with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    raise
                self._job_stage_identities.pop(job_id, None)
                self._job_reserved_bytes[job_id] = 0
                current.status = "failed"
                current.error = self._job_failure_message(exc, cleanup_error)
                current.progress = 0.0
                current.updated_at = self._now_ms()
                return OnboardUlogDownloadJobResponse(job=current.model_copy(deep=True), timestamp=current.updated_at)
        finally:
            async with self._lock:
                self._active_job_ids.discard(job_id)

    async def get_ready_file(self, job_id: str) -> tuple[Path, OnboardUlogDownloadJob]:
        async with self._lock:
            self._cleanup_expired_jobs_locked(self._now_ms())
            job = self._jobs.get(str(job_id))
            stage_path = self._job_paths.get(str(job_id))
            if job is None or stage_path is None:
                raise UlogNotFoundError(f"ULog download job {job_id} not found")
            if job.status != "ready":
                raise UlogJobConflictError(f"ULog download job {job_id} is not ready")
            identity = self._job_stage_identities.get(str(job_id))
            if identity is None:
                raise UlogUnsafePathError(
                    f"ULog download job {job_id} has no trusted staged-file identity"
                )
            self._stage_file_stat(stage_path, expected_identity=identity)
            return stage_path, job.model_copy(deep=True)

    @asynccontextmanager
    async def lease_ready_file(
        self,
        job_id: str,
    ) -> AsyncIterator[tuple[BinaryIO, Path, OnboardUlogDownloadJob]]:
        """Open and pin one verified staged file for parsing or streaming."""

        normalized_job_id = str(job_id)
        file_fd: int | None = None
        async with self._lock:
            self._cleanup_expired_jobs_locked(self._now_ms())
            job = self._jobs.get(normalized_job_id)
            stage_path = self._job_paths.get(normalized_job_id)
            if job is None or stage_path is None:
                raise UlogNotFoundError(
                    f"ULog download job {normalized_job_id} not found"
                )
            if job.status != "ready":
                raise UlogJobConflictError(
                    f"ULog download job {normalized_job_id} is not ready"
                )
            if normalized_job_id in self._active_job_ids:
                raise UlogJobConflictError(
                    f"ULog download job {normalized_job_id} is already in use"
                )
            identity = self._job_stage_identities.get(normalized_job_id)
            if identity is None:
                raise UlogUnsafePathError(
                    f"ULog download job {normalized_job_id} has no trusted staged-file identity"
                )
            file_fd = self._open_stage_file(
                stage_path,
                expected_identity=identity,
                flags=os.O_RDONLY,
            )
            self._active_job_ids.add(normalized_job_id)
            job_copy = job.model_copy(deep=True)

        try:
            with os.fdopen(file_fd, "rb", closefd=True) as file_handle:
                file_fd = None
                yield file_handle, stage_path, job_copy
        finally:
            if file_fd is not None:
                os.close(file_fd)
            async with self._lock:
                self._active_job_ids.discard(normalized_job_id)

    async def summarize_entry(
        self,
        drone: Any,
        log_id: int,
        request: OnboardUlogDownloadRequest,
    ) -> OnboardUlogSummaryResponse:
        """Stage, parse, summarize, and clean up one onboard ULog."""

        from mds_logging.ulog_analysis import summarize_ulog_file_async
        from src.ulog_proxy_policy import drone_ulog_summary_timeout_seconds

        entries = await self._fetch_entries(drone)
        entry = next((candidate for candidate in entries if candidate.id == int(log_id)), None)
        if entry is None:
            raise UlogNotFoundError(f"Onboard ULog {log_id} not found")
        max_summary_bytes = self._ulog_summary_max_bytes()
        if int(entry.size_bytes) > max_summary_bytes:
            raise UlogSizeLimitError(
                f"Onboard ULog {log_id} is larger than MDS_ULOG_SUMMARY_MAX_BYTES ({max_summary_bytes} bytes)"
            )

        queued = await self.create_download_job(drone, int(log_id), request)
        job_id = queued.job.job_id
        stage_path: Path | None = None
        ready_job: OnboardUlogDownloadJob | None = None
        deleted = False
        try:
            completed = await self.perform_download(drone, job_id)
            if completed.job.status != "ready":
                raise RuntimeError(
                    completed.job.error
                    or f"ULog download job ended with status {completed.job.status}"
                )
            async with self.lease_ready_file(job_id) as (
                _file_handle,
                stage_path,
                ready_job,
            ):
                source_metadata = {
                    "log_id": int(log_id),
                    "date_utc": completed.job.date_utc,
                    "size_bytes": completed.job.size_bytes,
                }
                summary = await summarize_ulog_file_async(
                    stage_path,
                    source_metadata=source_metadata,
                    max_bytes=max_summary_bytes,
                    timeout_seconds=drone_ulog_summary_timeout_seconds(),
                )
                correlation = (
                    summary.get("correlation")
                    if isinstance(summary.get("correlation"), dict)
                    else {}
                )
                evidence = (
                    correlation.get("evidence")
                    if isinstance(correlation.get("evidence"), dict)
                    else {}
                )
                correlation["evidence"] = {
                    **evidence,
                    "target_drone_id": self.hw_id,
                }
                summary["correlation"] = correlation
        finally:
            deleted = await self.delete_job(job_id)

        job = ready_job or queued.job
        summary.pop("raw_content_included", None)
        return OnboardUlogSummaryResponse(
            hw_id=self.hw_id,
            pos_id=job.pos_id,
            log_id=int(log_id),
            staged_job_deleted=deleted,
            timestamp=self._now_ms(),
            **summary,
        )

    async def erase_all(self, drone: Any, *, pos_id: int | None = None) -> OnboardUlogEraseAllResponse:
        fallback_deleted = self._erase_filesystem_logs()
        try:
            await drone.log_files.erase_all_log_files()
        except Exception:
            if not fallback_deleted:
                raise

        return OnboardUlogEraseAllResponse(
            status="accepted",
            hw_id=self.hw_id,
            pos_id=self._resolve_pos_id(pos_id),
            timestamp=self._now_ms(),
        )

    async def _fetch_entries(self, drone: Any) -> list[OnboardUlogEntry]:
        try:
            entries = await drone.log_files.get_entries()
        except LogFilesError as exc:
            result_name = getattr(getattr(exc, "_result", None), "result", None)
            if result_name == LogFilesResult.Result.NO_LOGFILES:
                filesystem_entries = self._list_filesystem_entries()
                if filesystem_entries is not None:
                    return filesystem_entries
                self._fallback_entries = {}
                return []
            filesystem_entries = self._list_filesystem_entries()
            if filesystem_entries is not None:
                return filesystem_entries
            raise
        except Exception:
            filesystem_entries = self._list_filesystem_entries()
            if filesystem_entries is not None:
                return filesystem_entries
            raise

        normalized = [
            OnboardUlogEntry(
                id=int(entry.id),
                date_utc=(entry.date or None),
                size_bytes=int(entry.size_bytes),
            )
            for entry in entries
        ]
        normalized.sort(
            key=lambda entry: ((entry.date_utc or ""), entry.id),
            reverse=True,
        )
        self._fallback_entries = {}
        return normalized

    async def _resolve_download_entry(self, drone: Any, job: OnboardUlogDownloadJob) -> MavsdkLogEntry:
        """Return the current MAVSDK entry for a staged job.

        MAVSDK documents onboard-log download as a two-step flow: first ask the
        vehicle for entries, then pass one of those entries to the download call.
        In production the download job runs after the HTTP request returns, often
        through a fresh MAVSDK connection, so reconstructing an Entry only from
        cached fields can be rejected by PX4/MAVSDK as INVALID_ARGUMENT. Refreshing
        the live entry at download time keeps the job API asynchronous while using
        the current vehicle-side log identifier.
        """
        try:
            live_entries = await drone.log_files.get_entries()
        except Exception:
            return MavsdkLogEntry(int(job.log_id), job.date_utc or "", int(job.size_bytes))

        log_id = int(job.log_id)
        exact_id_matches = [
            entry
            for entry in live_entries
            if self._safe_entry_int(entry, "id") == log_id
        ]
        for entry in exact_id_matches:
            if self._entry_matches_job(entry, job):
                return entry
        if exact_id_matches:
            return exact_id_matches[0]

        for entry in live_entries:
            if self._entry_matches_job(entry, job):
                return entry

        return MavsdkLogEntry(log_id, job.date_utc or "", int(job.size_bytes))

    @classmethod
    def _entry_matches_job(cls, entry: Any, job: OnboardUlogDownloadJob) -> bool:
        entry_size = cls._safe_entry_int(entry, "size_bytes")
        if entry_size is not None and entry_size != int(job.size_bytes):
            return False

        job_date = cls._normalize_entry_date(job.date_utc)
        entry_date = cls._normalize_entry_date(getattr(entry, "date", None))
        if job_date and entry_date and job_date != entry_date:
            return False
        return True

    @staticmethod
    def _safe_entry_int(entry: Any, attr: str) -> int | None:
        try:
            return int(getattr(entry, attr))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_entry_date(value: Any) -> str:
        token = str(value or "").strip()
        if not token:
            return ""
        return token.replace("+00:00", "Z").replace(".000000", "")

    def _list_filesystem_entries(self) -> list[OnboardUlogEntry] | None:
        candidates: list[tuple[_IndexedUlogFile, OnboardUlogEntry]] = []
        saw_existing_root = False
        for root in self._filesystem_fallback_dirs():
            if not root.exists():
                continue
            saw_existing_root = True
            for indexed_file in self._walk_confined_ulog_files(root):
                entry_id = self._fallback_entry_id(
                    indexed_file.path,
                    {entry.id for _, entry in candidates},
                )
                timestamp = self._filesystem_timestamp(
                    indexed_file.path,
                    indexed_file.mtime_ns / 1_000_000_000,
                )
                candidates.append(
                    (
                        indexed_file,
                        OnboardUlogEntry(
                            id=entry_id,
                            date_utc=timestamp,
                            size_bytes=indexed_file.size_bytes,
                        ),
                    )
                )

        if not candidates:
            self._fallback_entries = {}
            return [] if saw_existing_root else None

        candidates.sort(
            key=lambda item: ((item[1].date_utc or ""), item[1].id),
            reverse=True,
        )
        self._fallback_entries = {
            entry.id: indexed_file
            for indexed_file, entry in candidates
        }
        return [entry for _, entry in candidates]

    def _erase_filesystem_logs(self) -> bool:
        deleted = False
        indexed_entries = list(self._fallback_entries.items())
        for entry_id, indexed_file in indexed_entries:
            try:
                self._unlink_indexed_file(indexed_file)
            except UlogNotFoundError:
                pass
            else:
                deleted = True
            self._fallback_entries.pop(entry_id, None)
        return deleted

    def _filesystem_fallback_dirs(self) -> list[Path]:
        raw_value = getattr(
            self.params,
            "ULOG_FILESYSTEM_FALLBACK_DIRS",
            "~/PX4-Autopilot/build/px4_sitl_default/rootfs/log",
        )
        if isinstance(raw_value, (list, tuple, set)):
            values = [str(item).strip() for item in raw_value if str(item).strip()]
        else:
            normalized = str(raw_value or "").replace("\n", ",")
            values = [item.strip() for item in re.split(r"[,:]", normalized) if item.strip()]
        roots: list[Path] = []
        for value in values:
            root = self._canonical_config_path(
                value,
                relative_base=Path(__file__).resolve().parents[1],
                purpose="ULog fallback root",
            )
            self._assert_safe_directory(root, allow_missing=True)
            if root not in roots:
                roots.append(root)
        return roots

    def filesystem_fallback_dirs(self) -> list[Path]:
        return self._filesystem_fallback_dirs()

    @staticmethod
    def _canonical_config_path(
        value: str | os.PathLike[str],
        *,
        relative_base: Path,
        purpose: str,
    ) -> Path:
        raw_path = Path(value).expanduser()
        if ".." in raw_path.parts:
            raise UlogUnsafePathError(f"{purpose} must not contain parent traversal")
        if not raw_path.is_absolute():
            raw_path = relative_base / raw_path
        canonical = Path(os.path.abspath(os.path.normpath(os.fspath(raw_path))))
        if canonical == Path(canonical.anchor):
            raise UlogUnsafePathError(f"{purpose} must not be a filesystem root")
        return canonical

    @classmethod
    def _assert_safe_directory(cls, path: Path, *, allow_missing: bool) -> None:
        canonical = Path(os.path.abspath(os.fspath(path)))
        if canonical == Path(canonical.anchor):
            raise UlogUnsafePathError(f"Unsafe filesystem root is not allowed: {canonical}")

        current = Path(canonical.anchor)
        for part in canonical.parts[1:]:
            current /= part
            try:
                current_stat = current.lstat()
            except FileNotFoundError:
                if allow_missing:
                    return
                raise UlogNotFoundError(f"Required ULog directory does not exist: {current}")
            except OSError as exc:
                raise UlogStorageError(
                    f"Unable to inspect ULog directory {current}: {exc}"
                ) from exc
            if stat.S_ISLNK(current_stat.st_mode):
                raise UlogUnsafePathError(
                    f"Symlinked ULog directory is not allowed: {current}"
                )
            if not stat.S_ISDIR(current_stat.st_mode):
                raise UlogUnsafePathError(
                    f"ULog directory path contains a non-directory: {current}"
                )

    def _walk_confined_ulog_files(self, root: Path) -> list[_IndexedUlogFile]:
        self._assert_safe_directory(root, allow_missing=False)
        indexed: list[_IndexedUlogFile] = []

        def _raise_walk_error(error: OSError) -> None:
            raise UlogStorageError(
                f"Unable to inspect ULog fallback root {root}: {error}"
            ) from error

        for directory_name, child_dirs, file_names in os.walk(
            root,
            topdown=True,
            onerror=_raise_walk_error,
            followlinks=False,
        ):
            directory = Path(directory_name)
            self._assert_confined_directory(directory, root=root)

            for child_name in child_dirs:
                child_path = directory / child_name
                child_stat = self._lstat_path(child_path)
                if stat.S_ISLNK(child_stat.st_mode):
                    raise UlogUnsafePathError(
                        f"Symlinked directory inside ULog root is not allowed: {child_path}"
                    )
                if not stat.S_ISDIR(child_stat.st_mode):
                    raise UlogUnsafePathError(
                        f"Non-directory entry in ULog directory traversal: {child_path}"
                    )

            for file_name in file_names:
                path = directory / file_name
                if path.suffix.lower() != ".ulg":
                    continue
                file_stat = self._lstat_path(path)
                if stat.S_ISLNK(file_stat.st_mode):
                    raise UlogUnsafePathError(
                        f"Symlinked ULog file is not allowed: {path}"
                    )
                if not stat.S_ISREG(file_stat.st_mode):
                    raise UlogUnsafePathError(
                        f"Non-regular ULog file is not allowed: {path}"
                    )
                self._assert_path_confined(path, root=root)
                indexed.append(
                    _IndexedUlogFile(
                        path=path,
                        root=root,
                        device=int(file_stat.st_dev),
                        inode=int(file_stat.st_ino),
                        size_bytes=int(file_stat.st_size),
                        mtime_ns=int(file_stat.st_mtime_ns),
                        ctime_ns=int(file_stat.st_ctime_ns),
                    )
                )
        return indexed

    def _assert_confined_directory(self, directory: Path, *, root: Path) -> None:
        self._assert_path_confined(directory, root=root, allow_root=True)
        self._assert_safe_directory(root, allow_missing=False)
        self._assert_safe_directory(directory, allow_missing=False)

    @staticmethod
    def _assert_path_confined(
        path: Path,
        *,
        root: Path,
        allow_root: bool = False,
    ) -> None:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise UlogUnsafePathError(
                f"ULog path escapes its configured root: {path}"
            ) from exc
        if not allow_root and relative == Path("."):
            raise UlogUnsafePathError(f"ULog file path cannot be the root itself: {path}")

    @staticmethod
    def _lstat_path(path: Path) -> os.stat_result:
        try:
            return path.lstat()
        except FileNotFoundError as exc:
            raise UlogNotFoundError(f"ULog path no longer exists: {path}") from exc
        except OSError as exc:
            raise UlogStorageError(f"Unable to inspect ULog path {path}: {exc}") from exc

    def _validate_indexed_file(self, indexed_file: _IndexedUlogFile) -> None:
        configured_roots = self._filesystem_fallback_dirs()
        if indexed_file.root not in configured_roots:
            raise UlogUnsafePathError(
                f"Indexed ULog root is no longer configured: {indexed_file.root}"
            )
        self._assert_path_confined(indexed_file.path, root=indexed_file.root)
        self._assert_confined_directory(
            indexed_file.path.parent,
            root=indexed_file.root,
        )
        file_stat = self._lstat_path(indexed_file.path)
        self._assert_indexed_identity(indexed_file, file_stat)

    @staticmethod
    def _assert_indexed_identity(
        indexed_file: _IndexedUlogFile,
        file_stat: os.stat_result,
    ) -> None:
        if not stat.S_ISREG(file_stat.st_mode):
            raise UlogUnsafePathError(
                f"Indexed ULog is no longer a regular file: {indexed_file.path}"
            )
        identity = (int(file_stat.st_dev), int(file_stat.st_ino))
        expected = (indexed_file.device, indexed_file.inode)
        if identity != expected:
            raise UlogUnsafePathError(
                f"Indexed ULog identity changed before access: {indexed_file.path}"
            )
        if (
            int(file_stat.st_size) != indexed_file.size_bytes
            or int(file_stat.st_mtime_ns) != indexed_file.mtime_ns
            or int(file_stat.st_ctime_ns) != indexed_file.ctime_ns
        ):
            raise UlogUnsafePathError(
                f"Indexed ULog metadata changed before access: {indexed_file.path}"
            )

    def _open_indexed_file(self, indexed_file: _IndexedUlogFile) -> int:
        self._validate_indexed_file(indexed_file)
        parent_fd = self._open_directory_fd(indexed_file.path.parent)
        try:
            self._assert_open_directory_identity(parent_fd, indexed_file.path.parent)
            try:
                file_fd = os.open(
                    indexed_file.path.name,
                    os.O_RDONLY | self._nofollow_flags(),
                    dir_fd=parent_fd,
                )
            except FileNotFoundError as exc:
                raise UlogNotFoundError(
                    f"Indexed ULog no longer exists: {indexed_file.path}"
                ) from exc
            except OSError as exc:
                raise UlogUnsafePathError(
                    f"Unable to open indexed ULog safely: {indexed_file.path}"
                ) from exc
            try:
                self._assert_indexed_identity(indexed_file, os.fstat(file_fd))
            except Exception:
                os.close(file_fd)
                raise
            return file_fd
        finally:
            os.close(parent_fd)

    def _unlink_indexed_file(self, indexed_file: _IndexedUlogFile) -> None:
        file_fd = self._open_indexed_file(indexed_file)
        parent_fd = self._open_directory_fd(indexed_file.path.parent)
        try:
            self._assert_open_directory_identity(parent_fd, indexed_file.path.parent)
            current_stat = os.stat(
                indexed_file.path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            self._assert_indexed_identity(indexed_file, current_stat)
            os.unlink(indexed_file.path.name, dir_fd=parent_fd)
        except FileNotFoundError as exc:
            raise UlogNotFoundError(
                f"Indexed ULog no longer exists: {indexed_file.path}"
            ) from exc
        except UlogServiceError:
            raise
        except OSError as exc:
            raise UlogStorageError(
                f"Unable to erase indexed ULog {indexed_file.path}: {exc}"
            ) from exc
        finally:
            os.close(file_fd)
            os.close(parent_fd)

    def _secure_stage_dir(self, *, create: bool) -> Path:
        stage_dir = self._stage_dir()
        self._assert_safe_directory(stage_dir, allow_missing=create)
        if create:
            try:
                stage_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                self._assert_safe_directory(stage_dir, allow_missing=False)
            except UlogServiceError:
                raise
            except OSError as exc:
                raise UlogStorageError(
                    f"Unable to prepare ULog staging directory {stage_dir}: {exc}"
                ) from exc
        try:
            os.chmod(stage_dir, 0o700, follow_symlinks=False)
        except OSError as exc:
            raise UlogStorageError(
                f"Unable to secure ULog staging directory {stage_dir}: {exc}"
            ) from exc
        return stage_dir

    def _prepare_stage_file(self, stage_path: Path) -> tuple[int, int]:
        stage_dir = self._secure_stage_dir(create=True)
        if stage_path.parent != stage_dir:
            raise UlogUnsafePathError(
                f"ULog stage file escapes the staging directory: {stage_path}"
            )
        try:
            file_fd = os.open(
                stage_path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | self._nofollow_flags(),
                0o600,
            )
        except FileExistsError as exc:
            raise UlogJobConflictError(
                f"ULog stage file already exists: {stage_path.name}"
            ) from exc
        except OSError as exc:
            raise UlogStorageError(
                f"Unable to create ULog stage file {stage_path}: {exc}"
            ) from exc
        try:
            os.fchmod(file_fd, 0o600)
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise UlogUnsafePathError(
                    f"ULog stage path is not a regular file: {stage_path}"
                )
            return int(file_stat.st_dev), int(file_stat.st_ino)
        finally:
            os.close(file_fd)

    def _prepare_stage_destination(self, stage_path: Path) -> None:
        """Validate a confined, absent destination for MAVSDK to create."""

        stage_dir = self._secure_stage_dir(create=True)
        if stage_path.parent != stage_dir:
            raise UlogUnsafePathError(
                f"ULog stage file escapes the staging directory: {stage_path}"
            )
        parent_fd = self._open_directory_fd(stage_dir)
        try:
            self._assert_open_directory_identity(parent_fd, stage_dir)
            try:
                file_stat = os.stat(
                    stage_path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return
            if not stat.S_ISREG(file_stat.st_mode):
                raise UlogUnsafePathError(
                    f"Unsafe ULog stage destination already exists: {stage_path}"
                )
            raise UlogJobConflictError(
                f"ULog stage file already exists: {stage_path.name}"
            )
        except UlogServiceError:
            raise
        except OSError as exc:
            raise UlogStorageError(
                f"Unable to inspect ULog stage destination {stage_path}: {exc}"
            ) from exc
        finally:
            os.close(parent_fd)

    def _capture_stage_file_identity(self, stage_path: Path) -> tuple[int, int]:
        """Open and pin the regular file created by the MAVSDK downloader."""

        stage_dir = self._secure_stage_dir(create=False)
        if stage_path.parent != stage_dir:
            raise UlogUnsafePathError(
                f"ULog stage file escapes the staging directory: {stage_path}"
            )
        parent_fd = self._open_directory_fd(stage_dir)
        try:
            self._assert_open_directory_identity(parent_fd, stage_dir)
            try:
                file_fd = os.open(
                    stage_path.name,
                    os.O_RDONLY
                    | int(getattr(os, "O_NONBLOCK", 0))
                    | self._nofollow_flags(),
                    dir_fd=parent_fd,
                )
            except FileNotFoundError as exc:
                raise UlogStorageError(
                    f"MAVSDK did not create the ULog stage file: {stage_path}"
                ) from exc
            except OSError as exc:
                raise UlogUnsafePathError(
                    f"Unable to open MAVSDK ULog stage file safely: {stage_path}"
                ) from exc
            try:
                file_stat = os.fstat(file_fd)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise UlogUnsafePathError(
                        f"ULog stage path is not a regular file: {stage_path}"
                    )
                os.fchmod(file_fd, 0o600)
                return int(file_stat.st_dev), int(file_stat.st_ino)
            finally:
                os.close(file_fd)
        finally:
            os.close(parent_fd)

    def _stage_file_stat(
        self,
        stage_path: Path,
        *,
        expected_identity: tuple[int, int],
    ) -> os.stat_result:
        stage_dir = self._secure_stage_dir(create=False)
        if stage_path.parent != stage_dir:
            raise UlogUnsafePathError(
                f"ULog stage file escapes the staging directory: {stage_path}"
            )
        file_stat = self._lstat_path(stage_path)
        if not stat.S_ISREG(file_stat.st_mode):
            raise UlogUnsafePathError(
                f"ULog stage path is not a regular file: {stage_path}"
            )
        identity = (int(file_stat.st_dev), int(file_stat.st_ino))
        if identity != expected_identity:
            raise UlogUnsafePathError(
                f"ULog stage file identity changed during transfer: {stage_path}"
            )
        return file_stat

    def _open_stage_file(
        self,
        stage_path: Path,
        *,
        expected_identity: tuple[int, int],
        flags: int,
    ) -> int:
        self._stage_file_stat(stage_path, expected_identity=expected_identity)
        try:
            file_fd = os.open(stage_path, flags | self._nofollow_flags())
        except OSError as exc:
            raise UlogStorageError(
                f"Unable to open ULog stage file {stage_path}: {exc}"
            ) from exc
        file_stat = os.fstat(file_fd)
        identity = (int(file_stat.st_dev), int(file_stat.st_ino))
        if not stat.S_ISREG(file_stat.st_mode) or identity != expected_identity:
            os.close(file_fd)
            raise UlogUnsafePathError(
                f"ULog stage file identity changed during open: {stage_path}"
            )
        return file_fd

    def _unlink_stage_file(self, stage_path: Path, *, missing_ok: bool) -> None:
        stage_dir = self._secure_stage_dir(create=False)
        if stage_path.parent != stage_dir:
            raise UlogUnsafePathError(
                f"ULog stage file escapes the staging directory: {stage_path}"
            )
        try:
            file_stat = stage_path.lstat()
        except FileNotFoundError:
            if missing_ok:
                return
            raise UlogNotFoundError(f"ULog stage file does not exist: {stage_path}")
        if not stat.S_ISREG(file_stat.st_mode):
            raise UlogUnsafePathError(
                f"Refusing to unlink non-regular ULog stage path: {stage_path}"
            )
        parent_fd = self._open_directory_fd(stage_dir)
        try:
            current_stat = os.stat(
                stage_path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if (
                int(current_stat.st_dev),
                int(current_stat.st_ino),
            ) != (
                int(file_stat.st_dev),
                int(file_stat.st_ino),
            ):
                raise UlogUnsafePathError(
                    f"ULog stage file identity changed before deletion: {stage_path}"
                )
            os.unlink(stage_path.name, dir_fd=parent_fd)
        except FileNotFoundError:
            if not missing_ok:
                raise UlogNotFoundError(
                    f"ULog stage file does not exist: {stage_path}"
                )
        except UlogServiceError:
            raise
        except OSError as exc:
            raise UlogStorageError(
                f"Unable to remove ULog stage file {stage_path}: {exc}"
            ) from exc
        finally:
            os.close(parent_fd)

    def _untracked_stage_bytes(
        self,
        stage_dir: Path,
        *,
        tracked_paths: set[Path],
    ) -> int:
        total = 0
        try:
            candidates = tuple(stage_dir.glob("*.ulg"))
        except OSError as exc:
            raise UlogStorageError(
                f"Unable to inspect ULog staging directory {stage_dir}: {exc}"
            ) from exc
        for path in candidates:
            file_stat = self._lstat_path(path)
            if not stat.S_ISREG(file_stat.st_mode):
                raise UlogUnsafePathError(
                    f"Non-regular ULog stage artifact is not allowed: {path}"
                )
            if path not in tracked_paths:
                total += max(0, int(file_stat.st_size))
        return total

    @staticmethod
    def _nofollow_flags() -> int:
        return int(getattr(os, "O_NOFOLLOW", 0)) | int(getattr(os, "O_CLOEXEC", 0))

    @classmethod
    def _open_directory_fd(cls, path: Path) -> int:
        flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0)) | cls._nofollow_flags()
        try:
            return os.open(path, flags)
        except OSError as exc:
            raise UlogUnsafePathError(
                f"Unable to open ULog directory safely: {path}"
            ) from exc

    @staticmethod
    def _assert_open_directory_identity(directory_fd: int, expected_path: Path) -> None:
        proc_path = Path(f"/proc/self/fd/{directory_fd}")
        if proc_path.exists():
            opened_path = Path(os.path.realpath(proc_path))
            if opened_path != expected_path:
                raise UlogUnsafePathError(
                    f"ULog directory identity changed during access: {expected_path}"
                )

    @staticmethod
    def _assert_free_space_reserve(stage_dir: Path) -> None:
        if shutil.disk_usage(stage_dir).free < ulog_download_min_free_bytes():
            raise UlogStorageError(
                "ULog staging reached the configured free-space reserve"
            )

    @staticmethod
    def _filesystem_timestamp(path: Path, mtime: float) -> str:
        parent_date = path.parent.name
        stem = path.stem
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", parent_date) and re.fullmatch(r"\d{2}_\d{2}_\d{2}", stem):
            return f"{parent_date}T{stem.replace('_', ':')}Z"
        return datetime.fromtimestamp(mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _build_policy_payload(self) -> OnboardUlogPolicy:
        return OnboardUlogPolicy(
            supported=True,
            transport="mavsdk_log_files",
            storage_mode="file_backed",
            list_supported=True,
            download_supported=True,
            erase_all_supported=True,
            single_delete_supported=False,
            download_requires_disarmed=self._safe_bool("ULOG_DOWNLOAD_REQUIRE_DISARMED", True),
            erase_requires_disarmed=self._safe_bool("ULOG_ERASE_REQUIRE_DISARMED", True),
            staged_download_ttl_sec=int(self._safe_float("ULOG_DOWNLOAD_JOB_TTL_SEC", 1800.0)),
            notes=[
                "Onboard file-backed PX4 ULogs only.",
                "Single-log delete is not exposed in the generic MAVSDK log API.",
                "MAVLink log streaming is intentionally out of scope for this surface.",
                "When PX4 ULog files are locally accessible on the companion, filesystem fallback is allowed if MAVSDK log enumeration is unavailable.",
            ],
        )

    def _stage_dir(self) -> Path:
        configured = getattr(
            self.params,
            "ULOG_DOWNLOAD_STAGE_DIR",
            os.path.join("runtime_data", "ulog_downloads"),
        )
        if not isinstance(configured, (str, os.PathLike)):
            configured = os.path.join("runtime_data", "ulog_downloads")
        return self._canonical_config_path(
            configured,
            relative_base=Path(__file__).resolve().parents[1],
            purpose="ULog staging directory",
        )

    def _build_download_filename(self, entry: OnboardUlogEntry, *, pos_id: int | None) -> str:
        parts = ["mds-ulog"]
        if pos_id is not None:
            parts.append(f"P{pos_id}")
        parts.append(f"H{self.hw_id}")
        if entry.date_utc:
            parts.append(self._sanitize_timestamp_token(entry.date_utc))
        parts.append(f"L{entry.id}")
        return "_".join(parts) + ".ulg"

    @staticmethod
    def _sanitize_timestamp_token(value: str) -> str:
        token = value.strip()
        if not token:
            return "unknown"
        token = token.replace(":", "").replace("-", "")
        token = token.replace(".000000", "")
        token = token.replace(".", "")
        token = token.replace("+0000", "Z").replace("+00:00", "Z")
        token = token.replace("T", "T")
        token = re.sub(r"[^A-Za-z0-9TZ]", "", token)
        return token or "unknown"

    def _resolve_pos_id(self, override: int | None) -> int | None:
        if override is not None:
            return int(override)
        return self.pos_id

    def _cleanup_expired_jobs_locked(self, now_ms: int) -> int:
        active_stale_after_ms = int(ulog_download_timeout_seconds() * 1000) + 5000
        expired_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job_id not in self._active_job_ids
            and (
                (job.expires_at is not None and job.expires_at <= now_ms)
                or (
                    job.status in {"queued", "downloading"}
                    and now_ms - job.updated_at > active_stale_after_ms
                )
            )
        ]
        deleted = 0
        for job_id in expired_job_ids:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "expired"
            deleted += int(self._delete_job_locked(job_id))
        return deleted

    def _trim_job_count_locked(self) -> None:
        max_jobs = max(1, int(self._safe_float("ULOG_DOWNLOAD_MAX_JOBS", 8)))
        if len(self._jobs) <= max_jobs:
            return
        sorted_ids = sorted(
            (
                job_id
                for job_id, job in self._jobs.items()
                if job_id not in self._active_job_ids
                if job.status not in {"queued", "downloading"}
            ),
            key=lambda job_id: self._jobs[job_id].updated_at,
        )
        overflow = len(self._jobs) - max_jobs
        for job_id in sorted_ids[:overflow]:
            self._delete_job_locked(job_id)

    def _delete_job_locked(self, job_id: str) -> bool:
        if job_id in self._active_job_ids:
            raise UlogJobConflictError(
                f"ULog download job {job_id} is active and cannot be deleted"
            )
        path = self._job_paths.get(job_id)
        if path is not None:
            self._unlink_stage_file(path, missing_ok=True)
        self._job_paths.pop(job_id, None)
        self._job_access_hashes.pop(job_id, None)
        self._job_fallback_files.pop(job_id, None)
        self._job_reserved_bytes.pop(job_id, None)
        self._job_stage_identities.pop(job_id, None)
        self._active_job_ids.discard(job_id)
        return self._jobs.pop(job_id, None) is not None

    def _make_job_capacity_locked(self, *, expected_size: int, stage_dir: Path) -> None:
        max_jobs = max(1, int(self._safe_float("ULOG_DOWNLOAD_MAX_JOBS", 8)))
        if len(self._jobs) >= max_jobs:
            removable = sorted(
                (
                    job_id
                    for job_id, job in self._jobs.items()
                    if job_id not in self._active_job_ids
                    if job.status not in {"queued", "downloading"}
                ),
                key=lambda job_id: self._jobs[job_id].updated_at,
            )
            required_slots = len(self._jobs) - max_jobs + 1
            for job_id in removable[:required_slots]:
                self._delete_job_locked(job_id)
        if len(self._jobs) >= max_jobs:
            raise UlogCapacityError("All ULog staging job slots are currently active")

        secured_stage_dir = self._secure_stage_dir(create=True)
        if stage_dir != secured_stage_dir:
            raise UlogUnsafePathError(
                f"ULog job stage path is outside the configured staging directory: {stage_dir}"
            )
        tracked_paths = {
            path
            for job_id, path in self._job_paths.items()
            if job_id in self._jobs
        }
        staged_total = (
            sum(max(0, value) for value in self._job_reserved_bytes.values())
            + self._untracked_stage_bytes(
                secured_stage_dir,
                tracked_paths=tracked_paths,
            )
        )
        if staged_total + expected_size > ulog_download_aggregate_max_bytes():
            raise UlogCapacityError("ULog staging aggregate limit would be exceeded")

        free_bytes = shutil.disk_usage(secured_stage_dir).free
        reserve_bytes = ulog_download_min_free_bytes()
        if free_bytes - expected_size < reserve_bytes:
            raise UlogStorageError(
                "Insufficient free disk for ULog staging while preserving the configured reserve"
            )

    def _update_job_reservation_locked(self, job_id: str, staged_size: int) -> None:
        reservation = max(
            max(0, int(staged_size)),
            self._job_reserved_bytes.get(job_id, 0),
        )
        self._set_job_reservation_locked(job_id, reservation)

    def _set_job_reservation_locked(self, job_id: str, reserved_bytes: int) -> None:
        aggregate = sum(
            max(0, value)
            for candidate_id, value in self._job_reserved_bytes.items()
            if candidate_id != job_id
        ) + max(0, int(reserved_bytes))
        if aggregate > ulog_download_aggregate_max_bytes():
            raise UlogCapacityError("ULog staging aggregate limit would be exceeded")
        self._job_reserved_bytes[job_id] = max(0, int(reserved_bytes))

    def _assert_staged_size(
        self,
        stage_path: Path,
        *,
        expected_identity: tuple[int, int],
    ) -> int:
        staged_size = self._stage_file_stat(
            stage_path,
            expected_identity=expected_identity,
        ).st_size
        if staged_size > ulog_download_max_bytes():
            raise UlogSizeLimitError(
                "Staged ULog exceeds MDS_ULOG_DOWNLOAD_MAX_BYTES "
                f"({ulog_download_max_bytes()} bytes)"
            )
        return int(staged_size)

    def _copy_file_bounded(
        self,
        source: _IndexedUlogFile,
        destination: Path,
        destination_identity: tuple[int, int],
        max_bytes: int,
    ) -> None:
        total = 0
        source_fd = self._open_indexed_file(source)
        destination_fd = self._open_stage_file(
            destination,
            expected_identity=destination_identity,
            flags=os.O_WRONLY,
        )
        with os.fdopen(source_fd, "rb", closefd=True) as source_handle, os.fdopen(
            destination_fd,
            "wb",
            closefd=True,
        ) as destination_handle:
            while True:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UlogSizeLimitError(
                        f"Staged ULog exceeds MDS_ULOG_DOWNLOAD_MAX_BYTES ({max_bytes} bytes)"
                    )
                destination_handle.write(chunk)
                if shutil.disk_usage(destination.parent).free < ulog_download_min_free_bytes():
                    raise UlogStorageError(
                        "ULog staging reached the configured free-space reserve"
                    )
            self._assert_indexed_identity(source, os.fstat(source_handle.fileno()))
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        os.chmod(destination, 0o600, follow_symlinks=False)

    def _cleanup_orphaned_stage_files(self) -> None:
        stage_dir = self._secure_stage_dir(create=True)
        cutoff = time.time() - max(
            self._safe_float("ULOG_DOWNLOAD_JOB_TTL_SEC", 1800.0),
            ulog_download_timeout_seconds(),
        )
        for path in stage_dir.glob(f"{self.hw_id}-*.ulg"):
            try:
                candidate_stat = path.lstat()
                if not stat.S_ISREG(candidate_stat.st_mode):
                    raise UlogUnsafePathError(
                        f"Unsafe non-regular ULog stage artifact: {path}"
                    )
                if candidate_stat.st_mtime < cutoff:
                    self._unlink_stage_file(path, missing_ok=True)
            except OSError:
                continue

    @staticmethod
    def _fallback_entry_id(path: Path, occupied: set[int]) -> int:
        digest = hashlib.sha256(str(path).encode("utf-8")).digest()
        candidate = int.from_bytes(digest[:8], "big") & 0x7FFFFFFF
        while candidate in occupied:
            candidate = (candidate + 1) & 0x7FFFFFFF
        return candidate

    @staticmethod
    def _hash_access_token(token: str) -> str:
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    @staticmethod
    def _job_failure_message(
        error: object,
        cleanup_error: UlogServiceError | None,
    ) -> str:
        message = str(error)
        if cleanup_error is not None:
            message = (
                f"{message}; secure stage cleanup was blocked: "
                f"{cleanup_error.code}: {cleanup_error}"
            )
        return message

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def _safe_bool(self, attr: str, default: bool) -> bool:
        value = getattr(self.params, attr, default)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off", ""}
        return bool(value)

    def _safe_float(self, attr: str, default: float) -> float:
        value = getattr(self.params, attr, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _ulog_summary_max_bytes(self) -> int:
        raw = os.getenv("MDS_ULOG_SUMMARY_MAX_BYTES")
        default = 64 * 1024 * 1024
        try:
            value = int(raw) if raw is not None else default
        except (TypeError, ValueError):
            value = default
        return max(1, value)
