"""Drone-local onboard ULog access helpers."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mavsdk.log_files import Entry as MavsdkLogEntry
from mavsdk.log_files import LogFilesError, LogFilesResult

from mds_logging.api_schemas import (
    OnboardUlogDownloadJob,
    OnboardUlogDownloadJobResponse,
    OnboardUlogDownloadRequest,
    OnboardUlogEntry,
    OnboardUlogEraseAllResponse,
    OnboardUlogListResponse,
    OnboardUlogPolicy,
    OnboardUlogPolicyResponse,
)


class OnboardUlogService:
    """Manage onboard PX4 ULog discovery and short-lived staged downloads."""

    def __init__(self, params: Any, *, hw_id: str, pos_id: int | None = None) -> None:
        self.params = params
        self.hw_id = str(hw_id)
        self.pos_id = pos_id if pos_id is None else int(pos_id)
        self._jobs: dict[str, OnboardUlogDownloadJob] = {}
        self._job_paths: dict[str, Path] = {}
        self._fallback_entries: dict[int, Path] = {}
        self._lock = asyncio.Lock()

    def build_policy(self) -> OnboardUlogPolicyResponse:
        return OnboardUlogPolicyResponse(
            hw_id=self.hw_id,
            pos_id=self.pos_id,
            policy=self._build_policy_payload(),
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
            timestamp=self._now_ms(),
        )

    async def create_download_job(
        self,
        drone: Any,
        log_id: int,
        request: OnboardUlogDownloadRequest,
    ) -> OnboardUlogDownloadJobResponse:
        entries = await self._fetch_entries(drone)
        entry = next((candidate for candidate in entries if candidate.id == int(log_id)), None)
        if entry is None:
            raise FileNotFoundError(f"Onboard ULog {log_id} not found")

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
            self._jobs[job.job_id] = job
            self._job_paths[job.job_id] = stage_path
            self._trim_job_count_locked()
            return OnboardUlogDownloadJobResponse(job=job.model_copy(deep=True), timestamp=now_ms)

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
            return self._delete_job_locked(str(job_id))

    async def mark_job_failed(self, job_id: str, error: str) -> Optional[OnboardUlogDownloadJobResponse]:
        async with self._lock:
            current = self._jobs.get(str(job_id))
            if current is None:
                return None
            current.status = "failed"
            current.error = str(error)
            current.progress = 0.0
            current.updated_at = self._now_ms()
            return OnboardUlogDownloadJobResponse(
                job=current.model_copy(deep=True),
                timestamp=current.updated_at,
            )

    async def perform_download(self, drone: Any, job_id: str) -> OnboardUlogDownloadJobResponse:
        job_id = str(job_id)
        async with self._lock:
            job = self._jobs.get(job_id)
            stage_path = self._job_paths.get(job_id)
            if job is None or stage_path is None:
                raise FileNotFoundError(f"ULog download job {job_id} not found")
            job.status = "downloading"
            job.progress = 0.0
            job.error = None
            job.updated_at = self._now_ms()
            stage_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fallback_path = self._fallback_entries.get(int(job.log_id))
            if fallback_path is not None and fallback_path.exists():
                shutil.copy2(fallback_path, stage_path)
                async with self._lock:
                    current = self._jobs.get(job_id)
                    if current is not None:
                        current.status = "downloading"
                        current.progress = 1.0
                        current.updated_at = self._now_ms()
            else:
                entry = MavsdkLogEntry(job.log_id, job.date_utc or "", job.size_bytes)
                async for progress in drone.log_files.download_log_file(entry, str(stage_path)):
                    async with self._lock:
                        current = self._jobs.get(job_id)
                        if current is None:
                            break
                        current.status = "downloading"
                        current.progress = max(0.0, min(1.0, float(progress.progress)))
                        current.updated_at = self._now_ms()

            staged_size = stage_path.stat().st_size if stage_path.exists() else job.size_bytes
            async with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    raise FileNotFoundError(f"ULog download job {job_id} disappeared")
                current.status = "ready"
                current.progress = 1.0
                current.size_bytes = staged_size
                current.updated_at = self._now_ms()
                return OnboardUlogDownloadJobResponse(job=current.model_copy(deep=True), timestamp=current.updated_at)
        except Exception as exc:
            if stage_path.exists():
                stage_path.unlink(missing_ok=True)
            async with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    raise
                current.status = "failed"
                current.error = str(exc)
                current.progress = 0.0
                current.updated_at = self._now_ms()
                return OnboardUlogDownloadJobResponse(job=current.model_copy(deep=True), timestamp=current.updated_at)

    async def get_ready_file(self, job_id: str) -> tuple[Path, OnboardUlogDownloadJob]:
        async with self._lock:
            self._cleanup_expired_jobs_locked(self._now_ms())
            job = self._jobs.get(str(job_id))
            stage_path = self._job_paths.get(str(job_id))
            if job is None or stage_path is None:
                raise FileNotFoundError(f"ULog download job {job_id} not found")
            if job.status != "ready" or not stage_path.exists():
                raise RuntimeError(f"ULog download job {job_id} is not ready")
            return stage_path, job.model_copy(deep=True)

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

    def _list_filesystem_entries(self) -> list[OnboardUlogEntry] | None:
        candidates: list[tuple[Path, OnboardUlogEntry]] = []
        for root in self._filesystem_fallback_dirs():
            if not root.exists():
                continue
            for path in root.rglob("*.ulg"):
                if not path.is_file():
                    continue
                stat = path.stat()
                entry_id = int(zlib.crc32(str(path).encode("utf-8")) & 0x7FFFFFFF)
                timestamp = self._filesystem_timestamp(path, stat.st_mtime)
                candidates.append(
                    (
                        path,
                        OnboardUlogEntry(
                            id=entry_id,
                            date_utc=timestamp,
                            size_bytes=int(stat.st_size),
                        ),
                    )
                )

        if not candidates:
            self._fallback_entries = {}
            return None

        candidates.sort(
            key=lambda item: ((item[1].date_utc or ""), item[1].id),
            reverse=True,
        )
        self._fallback_entries = {entry.id: path for path, entry in candidates}
        return [entry for _, entry in candidates]

    def _erase_filesystem_logs(self) -> bool:
        deleted = False
        for root in self._filesystem_fallback_dirs():
            if not root.exists():
                continue
            for path in root.rglob("*.ulg"):
                if path.is_file():
                    path.unlink(missing_ok=True)
                    deleted = True
        self._fallback_entries = {}
        return deleted

    def _filesystem_fallback_dirs(self) -> list[Path]:
        raw_value = getattr(
            self.params,
            "ULOG_FILESYSTEM_FALLBACK_DIRS",
            "/root/PX4-Autopilot/build/px4_sitl_default/rootfs/log",
        )
        if isinstance(raw_value, (list, tuple, set)):
            values = [str(item).strip() for item in raw_value if str(item).strip()]
        else:
            normalized = str(raw_value or "").replace("\n", ",")
            values = [item.strip() for item in re.split(r"[,:]", normalized) if item.strip()]
        return [Path(value).expanduser() for value in values]

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
        path = Path(configured)
        if not path.is_absolute():
            repo_root = Path(__file__).resolve().parents[1]
            path = repo_root / path
        return path

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

    def _cleanup_expired_jobs_locked(self, now_ms: int) -> None:
        expired_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.expires_at is not None and job.expires_at <= now_ms
        ]
        for job_id in expired_job_ids:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "expired"
            self._delete_job_locked(job_id)

    def _trim_job_count_locked(self) -> None:
        max_jobs = max(1, int(self._safe_float("ULOG_DOWNLOAD_MAX_JOBS", 8)))
        if len(self._jobs) <= max_jobs:
            return
        sorted_ids = sorted(
            self._jobs,
            key=lambda job_id: self._jobs[job_id].updated_at,
        )
        for job_id in sorted_ids[:-max_jobs]:
            self._delete_job_locked(job_id)

    def _delete_job_locked(self, job_id: str) -> bool:
        path = self._job_paths.pop(job_id, None)
        if path and path.exists():
            path.unlink(missing_ok=True)
        return self._jobs.pop(job_id, None) is not None

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
