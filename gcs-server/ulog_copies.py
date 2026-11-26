"""Bounded, verified GCS copies of actor-bound onboard ULog jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
from collections import Counter
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse

from mds_logging.api_schemas import OnboardUlogDownloadJob
from src.ulog_transfer_policy import (
    ulog_download_aggregate_max_bytes,
    ulog_download_max_bytes,
    ulog_download_min_free_bytes,
    ulog_download_timeout_seconds,
)
from ulog_job_handles import resolve_ulog_job_handle

logger = logging.getLogger(__name__)
MAGIC = b"ULog\x01\x12\x35"
MAX_ACTIVE = 4


def _now() -> int:
    return int(time.time() * 1000)


class InvalidCopy(ValueError):
    pass


class GcsUlogCopies:
    def __init__(self, root: Path):
        self.root = root
        self.jobs: dict[str, OnboardUlogDownloadJob] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.leases: Counter[str] = Counter()
        self.reserved: dict[str, int] = {}
        self.next_sweep = 0.0

    @staticmethod
    def key(owner: str, drone_id: int, node_job_id: str) -> str:
        return hashlib.sha256(f"{owner}:{drone_id}:{node_job_id}".encode()).hexdigest()

    def sweep(self) -> None:
        now = time.monotonic()
        if now < self.next_sweep:
            return
        for key, job in list(self.jobs.items()):
            if key not in self.tasks and job.expires_at and job.expires_at <= _now():
                self.jobs.pop(key, None)
        for path in self.root.glob("*.json"):
            key = path.stem
            if key in self.tasks or self.leases[key]:
                continue
            if self.metadata(key) is None:
                self.purge(key)
        for path in self.root.iterdir() if self.root.exists() else ():
            key = path.stem
            if (path.suffix in {".part", ".tmp", ".ulg"} and key not in self.tasks
                    and not self.leases[key] and not (self.root / f"{key}.json").exists()):
                path.unlink(missing_ok=True)
        self.next_sweep = now + 30

    def purge(self, key: str) -> None:
        for suffix in ("json", "ulg", "part", "tmp"):
            (self.root / f"{key}.{suffix}").unlink(missing_ok=True)

    def metadata(self, key: str) -> dict | None:
        try:
            metadata = json.loads((self.root / f"{key}.json").read_text())
            if metadata["expires_at"] > _now() and (metadata.get("deleted")
                    or (self.root / f"{key}.ulg").stat().st_size == metadata["size"]):
                return metadata
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    @contextmanager
    def lease(self, key: str):
        self.sweep()
        metadata = self.metadata(key)
        if metadata is None or metadata.get("deleted"):
            raise HTTPException(409, "The verified GCS copy is unavailable. Check the transfer status.")
        self.leases[key] += 1
        try:
            yield self.root / f"{key}.ulg", metadata
        finally:
            self.leases[key] -= 1
            if self.leases[key] == 0:
                del self.leases[key]

    def delete(self, key: str, expires_at: int | None) -> None:
        if key in self.tasks or self.leases[key]:
            raise HTTPException(409, "This transfer is still in use.")
        if key in self.jobs:
            self._state(key, status="expired", phase=None, error="The GCS copy was removed.")
        self.purge(key)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._publish(key, {"expires_at": expires_at or _now() + 1_800_000, "deleted": True})

    async def maintain(self) -> None:
        try:
            while True:
                try:
                    self.sweep()
                except OSError:
                    logger.exception("Unable to clean the GCS ULog cache")
                await asyncio.sleep(30)
        finally:
            tasks = list(self.tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def watch(self, owner: str, drone_id: int, job: OnboardUlogDownloadJob,
              ip: str, expected_size: int | None, expected_date: str | None) -> OnboardUlogDownloadJob:
        self.sweep()
        if job.expires_at and job.expires_at <= _now():
            return job.model_copy(update={"status": "expired"})
        resolved = resolve_ulog_job_handle(job.job_id, drone_id=drone_id, owner_fingerprint=owner)
        key = self.key(owner, drone_id, resolved.node_job_id)
        metadata = self.metadata(key)
        if metadata and metadata.get("deleted"):
            return job.model_copy(update={"status": "expired", "phase": None, "error": "The GCS copy was removed."})
        if metadata:
            return job.model_copy(update={
                "status": "ready", "phase": "verified", "progress": 1.0,
                "size_bytes": metadata["size"], "bytes_received": metadata["size"],
                "updated_at": metadata["verified_at"], "error": None,
            })
        if expected_date and job.date_utc != expected_date:
            return job.model_copy(update={"status": "failed", "phase": None, "error": "The aircraft now lists a different log under this ID. Refresh its inventory."})
        if key not in self.jobs:
            if len(self.tasks) >= MAX_ACTIVE:
                return job.model_copy(update={"status": "queued", "phase": "waiting", "progress": 0.0})
            self.jobs[key] = job.model_copy(update={"status": "queued", "phase": "aircraft", "progress": 0.0})
            task = asyncio.create_task(self._prepare(key, ip, resolved, job, expected_size))
            self.tasks[key] = task
        return self.jobs[key]

    def _state(self, key: str, **updates) -> None:
        self.jobs[key] = self.jobs[key].model_copy(update={"updated_at": _now(), **updates})

    async def _prepare(self, key, ip, resolved, original, expected_size) -> None:
        from log_proxy import (
            DroneProxyResponseError, DroneProxyUnavailableError, fetch_drone_ulog_download_job,
        )

        deadline = min(original.expires_at or (_now() + 900_000),
                       _now() + int(1000 * ulog_download_timeout_seconds()))
        # A queued job publishes the inventory size. A recovered ready job
        # publishes its actual size, so it cannot prove the inventory size.
        expected_size = expected_size or (original.size_bytes if original.status != "ready" else 0)
        try:
            async with asyncio.timeout(max(0.001, (deadline - _now()) / 1000)):
                delay = 1
                job = original
                while job.status != "ready":
                    if job.status in {"failed", "expired"}:
                        self._state(key, status=job.status, error=job.error, phase=None)
                        return
                    try:
                        data = await fetch_drone_ulog_download_job(ip, resolved.node_job_id,
                                                                  access_token=resolved.access_token)
                        job = OnboardUlogDownloadJob.model_validate(data["job"])
                    except (DroneProxyUnavailableError, DroneProxyResponseError) as exc:
                        if getattr(exc, "status_code", None) in {404, 410}:
                            self._state(key, status="expired", phase=None, error="The aircraft copy is no longer available.")
                            return
                        self._state(key, error="Aircraft connection interrupted. Reconnecting…")
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 15)
                        continue
                    if (job.job_id != resolved.node_job_id or job.hw_id != original.hw_id
                            or job.log_id != original.log_id or job.date_utc != original.date_utc):
                        raise InvalidCopy("The aircraft returned a different log. Refresh its inventory.")
                    if job.status == "ready":
                        break
                    expected_size = expected_size or max(0, job.size_bytes)
                    self._state(key, status=job.status, phase="aircraft", progress=job.progress,
                                size_bytes=job.size_bytes, error=None)
                    delay = 1
                    await asyncio.sleep(1.5)

                total = job.size_bytes
                if total < 16 or total > ulog_download_max_bytes():
                    raise InvalidCopy("The aircraft returned an invalid log size.")
                if expected_size and expected_size != total:
                    raise InvalidCopy(f"Incomplete log. Inventory listed {expected_size:,} bytes and the aircraft staged {total:,}.")
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
                used = sum(path.stat().st_size for path in self.root.glob("*.ulg"))
                if used + sum(self.reserved.values()) + total > ulog_download_aggregate_max_bytes():
                    raise InvalidCopy("GCS log storage is full. Remove a prepared copy or wait for it to expire.")
                self.reserved[key] = total
                for retry in range(3):
                    try:
                        await self._copy(key, ip, resolved, original, total, deadline)
                        return
                    except (DroneProxyUnavailableError, DroneProxyResponseError, httpx.TransportError) as exc:
                        if retry == 2 or getattr(exc, "status_code", None) in {404, 410}:
                            raise InvalidCopy("Could not finish copying from the aircraft. Check its connection and prepare the log again.") from exc
                        self._state(key, error="Copy interrupted. Reconnecting to the same aircraft copy…")
                        await asyncio.sleep(2 ** retry)
        except TimeoutError:
            self._state(key, status="failed", phase=None, error="The transfer timed out. Check the connection and retry.")
        except InvalidCopy as exc:
            self._state(key, status="failed", phase=None, error=str(exc))
        except Exception:
            logger.exception("Unable to prepare ULog on GCS")
            self._state(key, status="failed", phase=None, error="The GCS could not prepare this log. Check storage and retry.")
        finally:
            self.reserved.pop(key, None)
            self.tasks.pop(key, None)
            (self.root / f"{key}.part").unlink(missing_ok=True)
            (self.root / f"{key}.tmp").unlink(missing_ok=True)

    async def _copy(self, key, ip, resolved, original, total, deadline):
        from log_proxy import open_drone_ulog_download_stream

        if shutil.disk_usage(self.root).free < total + ulog_download_min_free_bytes():
            raise InvalidCopy("GCS storage has insufficient free space for this log.")
        self._state(key, status="downloading", phase="copy", progress=0.0,
                    bytes_received=0, size_bytes=total, error=None)
        client, upstream = await open_drone_ulog_download_stream(ip, resolved.node_job_id,
                                                                 access_token=resolved.access_token)
        partial = self.root / f"{key}.part"
        digest, header, count = hashlib.sha256(), bytearray(), 0
        try:
            if upstream.status_code != 200 or upstream.headers.get("content-encoding", "identity") != "identity":
                raise InvalidCopy("The aircraft did not return a complete raw log stream.")
            length = upstream.headers.get("content-length")
            if length is not None and length != str(total):
                raise InvalidCopy("The aircraft response length does not match the staged log.")
            with partial.open("wb") as output:
                os.fchmod(output.fileno(), 0o600)
                async for chunk in upstream.aiter_bytes(chunk_size=256 * 1024):
                    count += len(chunk)
                    if count > total or shutil.disk_usage(self.root).free < ulog_download_min_free_bytes():
                        raise InvalidCopy("The received log exceeded its allowed size or available GCS storage.")
                    header.extend(chunk[:max(0, 16 - len(header))])
                    digest.update(chunk)
                    output.write(chunk)
                    self._state(key, bytes_received=count, progress=count / total)
                self._state(key, phase="verify")
                if count != total or len(header) < 16 or header[:len(MAGIC)] != MAGIC:
                    raise InvalidCopy("The received file is incomplete or has an invalid PX4 ULog header.")
                self._sync(output)
        finally:
            try:
                await upstream.aclose()
            finally:
                await client.aclose()
        metadata = {
            "size": count, "sha256": digest.hexdigest(), "verified_at": _now(),
            "expires_at": original.expires_at or deadline,
            "filename": Path(original.download_filename or f"PX4-H{original.hw_id}-{original.log_id}.ulg").name,
            "log_id": original.log_id, "date_utc": original.date_utc, "pos_id": original.pos_id,
        }
        # The metadata is the commit marker. A crash between renames can
        # leave an orphan, but it cannot publish an incomplete download.
        partial.replace(self.root / f"{key}.ulg")
        self._publish(key, metadata)
        self._state(key, status="ready", phase="verified", progress=1.0)

    def _publish(self, key: str, metadata: dict) -> None:
        temporary = self.root / f"{key}.tmp"
        temporary.write_text(json.dumps(metadata))
        temporary.replace(self.root / f"{key}.json")

    @staticmethod
    def _sync(output):
        output.flush()
        os.fsync(output.fileno())


class VerifiedUlogResponse(FileResponse):
    """Keep the staged file leased until ASGI finishes or disconnects."""

    def __init__(self, lease):
        self.lease = lease
        path, meta = lease.__enter__()
        try:
            super().__init__(path, filename=meta["filename"], media_type="application/octet-stream",
                             headers={"ETag": f'"{meta["sha256"]}"', "Cache-Control": "private, no-cache"})
        except BaseException:
            lease.__exit__(None, None, None)
            raise

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.lease.__exit__(None, None, None)


@lru_cache(maxsize=4)
def _copies(state_dir: str) -> GcsUlogCopies:
    return GcsUlogCopies(Path(state_dir) / "ulog-copies")


def get_ulog_copies() -> GcsUlogCopies:
    from src.params import Params

    return _copies(str(Params.GCS_COMMAND_STATE_DIR))
