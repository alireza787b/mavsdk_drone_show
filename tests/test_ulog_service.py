import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ulog_service import OnboardUlogService


class _FakeProgress:
    def __init__(self, progress):
        self.progress = progress


class _FakeLogFiles:
    def __init__(self, entries=None):
        self._entries = entries or []
        self.erased = False

    async def get_entries(self):
        return list(self._entries)

    async def download_log_file(self, entry, path):
        target = Path(path)
        target.write_bytes(b"first")
        yield _FakeProgress(0.25)
        target.write_bytes(b"finished-ulog")
        yield _FakeProgress(1.0)

    async def erase_all_log_files(self):
        self.erased = True


class _BrokenLogFiles(_FakeLogFiles):
    async def get_entries(self):
        raise RuntimeError("Socket closed")

    async def download_log_file(self, entry, path):
        raise RuntimeError("download unavailable")


class _FakeDrone:
    def __init__(self, entries=None):
        self.log_files = _FakeLogFiles(entries=entries)


class _BrokenDrone:
    def __init__(self):
        self.log_files = _BrokenLogFiles()


def _make_params(tmp_path):
    return SimpleNamespace(
        ULOG_DOWNLOAD_REQUIRE_DISARMED=True,
        ULOG_ERASE_REQUIRE_DISARMED=True,
        ULOG_DOWNLOAD_JOB_TTL_SEC=1800.0,
        ULOG_DOWNLOAD_MAX_JOBS=8,
        ULOG_DOWNLOAD_STAGE_DIR=str(tmp_path / "ulog-stage"),
        ULOG_FILESYSTEM_FALLBACK_DIRS=str(tmp_path / "px4-log-root"),
    )


@pytest.mark.asyncio
async def test_list_entries_sorts_newest_first_and_builds_policy(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[
            SimpleNamespace(id=2, date="2026-04-11T10:00:00Z", size_bytes=220),
            SimpleNamespace(id=1, date="2026-04-11T09:00:00Z", size_bytes=120),
        ]
    )

    response = await service.list_entries(drone)

    assert response.hw_id == "7"
    assert response.pos_id == 3
    assert response.count == 2
    assert [entry.id for entry in response.files] == [2, 1]
    assert response.policy.download_supported is True
    assert response.policy.storage_mode == "file_backed"


@pytest.mark.asyncio
async def test_create_and_complete_download_job_stages_named_file(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=512)]
    )

    queued = await service.create_download_job(
        drone,
        9,
        SimpleNamespace(pos_id=3),
    )
    assert queued.job.status == "queued"
    assert queued.job.download_filename == "mds-ulog_P3_H7_20260411T102233Z_L9.ulg"

    completed = await service.perform_download(drone, queued.job.job_id)
    assert completed.job.status == "ready"
    assert completed.job.progress == 1.0
    assert completed.job.size_bytes == len(b"finished-ulog")

    stage_path, ready_job = await service.get_ready_file(queued.job.job_id)
    assert stage_path.exists()
    assert ready_job.download_filename.endswith(".ulg")


@pytest.mark.asyncio
async def test_mark_failed_and_delete_cleanup(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="9", pos_id=5)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=4, date="2026-04-11T10:22:33Z", size_bytes=64)]
    )

    queued = await service.create_download_job(
        drone,
        4,
        SimpleNamespace(pos_id=5),
    )
    failed = await service.mark_job_failed(queued.job.job_id, "connect timeout")
    assert failed is not None
    assert failed.job.status == "failed"
    assert failed.job.error == "connect timeout"

    deleted = await service.delete_job(queued.job.job_id)
    assert deleted is True
    assert await service.get_job(queued.job.job_id) is None


@pytest.mark.asyncio
async def test_erase_all_reports_acceptance(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="11", pos_id=2)
    drone = _FakeDrone(entries=[])

    response = await service.erase_all(drone)

    assert response.status == "accepted"
    assert response.hw_id == "11"
    assert response.pos_id == 2
    assert drone.log_files.erased is True


@pytest.mark.asyncio
async def test_filesystem_fallback_lists_downloads_and_erases_when_mavsdk_is_unavailable(tmp_path):
    params = _make_params(tmp_path)
    log_root = Path(params.ULOG_FILESYSTEM_FALLBACK_DIRS) / "2026-04-11"
    log_root.mkdir(parents=True, exist_ok=True)
    fallback_file = log_root / "08_38_11.ulg"
    fallback_file.write_bytes(b"fallback-ulog")

    service = OnboardUlogService(params, hw_id="21", pos_id=4)
    drone = _BrokenDrone()

    listed = await service.list_entries(drone)
    assert listed.count == 1
    assert listed.files[0].date_utc == "2026-04-11T08:38:11Z"

    queued = await service.create_download_job(drone, listed.files[0].id, SimpleNamespace(pos_id=4))
    completed = await service.perform_download(drone, queued.job.job_id)
    assert completed.job.status == "ready"

    stage_path, _ = await service.get_ready_file(queued.job.job_id)
    assert stage_path.read_bytes() == b"fallback-ulog"

    response = await service.erase_all(drone)
    assert response.status == "accepted"
    assert not fallback_file.exists()
