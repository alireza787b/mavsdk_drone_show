"""ULog metadata identity tests; all state and vehicle bytes are disposable."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mds_logging.api_schemas import OnboardUlogDownloadRequest
from src.ulog_request_receipts import (
    UlogRequestConflict, UlogRequestReceiptStore, UlogRequestStorageError, native_download_job_id,
)
from src.ulog_service import OnboardUlogService, UlogJobConflictError


def test_receipt_claim_survives_reopen_and_never_recycles_at_capacity(tmp_path):
    path = tmp_path / "requests.sqlite3"
    store = UlogRequestReceiptStore(path, max_records=1)
    payload = {"status": "unknown", "request_id": "request-a"}
    assert store.claim("actor-runtime", "request-a", "file-a", payload) == (payload, True)
    reopened = UlogRequestReceiptStore(path, max_records=1)
    assert reopened.claim("actor-runtime", "request-a", "file-a", payload) == (payload, False)
    with pytest.raises(UlogRequestConflict):
        reopened.claim("actor-runtime", "request-a", "file-b", payload)
    with pytest.raises(UlogRequestStorageError, match="capacity"):
        reopened.claim("actor-runtime", "request-b", "file-b", payload)
    assert reopened.get("actor-runtime", "request-a") == payload
    assert reopened.get("another-actor", "request-a") is None


def test_receipt_rejects_symlink_and_oversized_metadata(tmp_path):
    target = tmp_path / "target"
    target.write_text("private")
    link = tmp_path / "receipt.sqlite3"
    link.symlink_to(target)
    with pytest.raises(UlogRequestStorageError):
        UlogRequestReceiptStore(link)
    store = UlogRequestReceiptStore(tmp_path / "safe.sqlite3")
    with pytest.raises(UlogRequestStorageError, match="bounded"):
        store.claim("scope", "request", "fingerprint", {"raw": "x" * 9000})
    assert target.read_text() == "private"


class FakeLogs:
    def __init__(self):
        self.reads = 0

    async def get_entries(self):
        self.reads += 1
        return [SimpleNamespace(id=9, date="2026-11-12T12:00:00Z", size_bytes=64)]


def service(tmp_path):
    return OnboardUlogService(SimpleNamespace(
        ULOG_DOWNLOAD_STAGE_DIR=str(tmp_path / "stage"), ULOG_DOWNLOAD_MAX_JOBS=8,
        ULOG_FILESYSTEM_FALLBACK_DIRS=str(tmp_path / "absent-log-root"),
        ULOG_DOWNLOAD_JOB_TTL_SEC=1800, runtime_mode="sitl",
    ), hw_id="5", pos_id=2)


@pytest.mark.asyncio
async def test_native_request_dedups_before_relisting_and_schedules_once(tmp_path):
    instance = service(tmp_path)
    drone = SimpleNamespace(log_files=FakeLogs())
    request = OnboardUlogDownloadRequest(request_id="request-native")
    first = await instance.create_download_job(drone, 9, request, access_token="capability")
    second = await instance.create_download_job(drone, 9, request, access_token="capability")
    assert first.job.job_id == second.job.job_id == native_download_job_id("5", request.request_id, "capability")
    assert drone.log_files.reads == 1
    assert await instance.claim_download_start(first.job.job_id)
    assert not await instance.claim_download_start(first.job.job_id)
    assert await instance.authorize_job(first.job.job_id, "capability")
    with pytest.raises(UlogJobConflictError, match="different"):
        await instance.create_download_job(drone, 10, request, access_token="capability")
    instance.params.runtime_mode = "real"
    with pytest.raises(UlogJobConflictError, match="different"):
        await instance.create_download_job(drone, 9, request, access_token="capability")
    assert b"capability" not in instance._download_request_store().path.read_bytes()


@pytest.mark.asyncio
async def test_native_restart_does_not_restage_previously_claimed_request(tmp_path):
    first = service(tmp_path)
    drone = SimpleNamespace(log_files=FakeLogs())
    request = OnboardUlogDownloadRequest(request_id="request-restart")
    created = await first.create_download_job(drone, 9, request, access_token="capability")
    restarted = service(tmp_path)
    assert await restarted.get_job(created.job.job_id) is None
    with pytest.raises(UlogJobConflictError, match="restart"):
        await restarted.create_download_job(drone, 9, request, access_token="capability")
    assert drone.log_files.reads == 1
    assert not list(Path(first.params.ULOG_DOWNLOAD_STAGE_DIR).glob("*.ulg"))


@pytest.mark.asyncio
async def test_native_receipt_is_claimed_before_inventory_await(tmp_path):
    instance = service(tmp_path)
    request = OnboardUlogDownloadRequest(request_id="request-lost")
    class BrokenInventory:
        async def get_entries(self):
            raise RuntimeError("inventory unavailable")
    drone = SimpleNamespace(log_files=BrokenInventory())
    with pytest.raises(RuntimeError):
        await instance.create_download_job(drone, 9, request, access_token="capability")
    with pytest.raises(UlogJobConflictError, match="will not be replayed"):
        await instance.create_download_job(drone, 9, request, access_token="capability")
