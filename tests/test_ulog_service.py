import asyncio
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ulog_service import (
    OnboardUlogService,
    UlogCapacityError,
    UlogJobConflictError,
    UlogStorageError,
    UlogUnsafePathError,
)


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


class _TrackingLogFiles(_FakeLogFiles):
    def __init__(self, entries=None):
        super().__init__(entries=entries)
        self.download_attempted = False

    async def download_log_file(self, entry, path):
        self.download_attempted = True
        async for progress in super().download_log_file(entry, path):
            yield progress


class _TrackingDrone:
    def __init__(self, entries=None):
        self.log_files = _TrackingLogFiles(entries=entries)


class _BrokenDrone:
    def __init__(self):
        self.log_files = _BrokenLogFiles()


class _StrictRefetchLogFiles:
    def __init__(self):
        self.calls = 0
        self.initial_entry = SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=512)
        self.live_entry = SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=512)
        self.downloaded_entry = None

    async def get_entries(self):
        self.calls += 1
        if self.calls == 1:
            return [self.initial_entry]
        return [self.live_entry]

    async def download_log_file(self, entry, path):
        if entry is not self.live_entry:
            raise AssertionError("download should use the freshly fetched MAVSDK entry")
        self.downloaded_entry = entry
        Path(path).write_bytes(b"fresh-entry-ulog")
        yield _FakeProgress(1.0)


class _StrictRefetchDrone:
    def __init__(self):
        self.log_files = _StrictRefetchLogFiles()


class _BlockingLogFiles(_FakeLogFiles):
    def __init__(self, entries=None):
        super().__init__(entries=entries)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def download_log_file(self, entry, path):
        Path(path).write_bytes(b"partial")
        self.started.set()
        await self.release.wait()
        Path(path).write_bytes(b"complete")
        yield _FakeProgress(1.0)


class _BlockingDrone:
    def __init__(self, entries=None):
        self.log_files = _BlockingLogFiles(entries=entries)


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
async def test_summarize_entry_returns_derived_envelope_and_cleans_stage(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=512)]
    )

    async def fake_summary(_path, **_kwargs):
        return {
            "source": {"log_id": 9},
            "parser": {"status": "ok"},
            "parsed": True,
            "correlation": {"evidence": {}},
        }

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "mds_logging.ulog_analysis.summarize_ulog_file_async",
            fake_summary,
        )
        summary = await service.summarize_entry(drone, 9, SimpleNamespace(pos_id=3))

    assert summary.hw_id == "7"
    assert summary.pos_id == 3
    assert summary.log_id == 9
    assert summary.raw_content_included is False
    assert summary.staged_job_deleted is True
    assert summary.source.log_id == 9
    assert await service.get_job(next(iter(service._jobs), "missing")) is None


@pytest.mark.asyncio
async def test_summarize_entry_rejects_oversize_before_download(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_ULOG_SUMMARY_MAX_BYTES", "8")
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _TrackingDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=512)]
    )

    with pytest.raises(ValueError, match="MDS_ULOG_SUMMARY_MAX_BYTES"):
        await service.summarize_entry(drone, 9, SimpleNamespace(pos_id=3))

    assert drone.log_files.download_attempted is False
    assert service._jobs == {}
    assert service._job_paths == {}


@pytest.mark.asyncio
async def test_download_refetches_live_mavsdk_entry_before_staging(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _StrictRefetchDrone()

    queued = await service.create_download_job(
        drone,
        9,
        SimpleNamespace(pos_id=3),
    )
    completed = await service.perform_download(drone, queued.job.job_id)

    assert completed.job.status == "ready"
    assert drone.log_files.downloaded_entry is drone.log_files.live_entry
    stage_path, _ = await service.get_ready_file(queued.job.job_id)
    assert stage_path.read_bytes() == b"fresh-entry-ulog"


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
async def test_raw_download_job_requires_matching_capability(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="9", pos_id=5)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=4, date="2026-04-11T10:22:33Z", size_bytes=64)]
    )

    queued = await service.create_download_job(
        drone,
        4,
        SimpleNamespace(pos_id=5),
        access_token="actor-capability",
    )

    assert await service.authorize_job(queued.job.job_id, "actor-capability") is True
    assert await service.authorize_job(queued.job.job_id, "other-capability") is False
    assert await service.authorize_job(queued.job.job_id, None) is False


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

    listed_after_erase = await service.list_entries(drone)
    assert listed_after_erase.count == 0


@pytest.mark.asyncio
async def test_filesystem_job_keeps_bound_source_across_later_inventory_refresh(tmp_path):
    params = _make_params(tmp_path)
    log_root = Path(params.ULOG_FILESYSTEM_FALLBACK_DIRS)
    first = log_root / "2026-04-11" / "08_38_11.ulg"
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(b"first-flight")
    service = OnboardUlogService(params, hw_id="21", pos_id=4)
    drone = _BrokenDrone()

    listed = await service.list_entries(drone)
    queued = await service.create_download_job(
        drone,
        listed.files[0].id,
        SimpleNamespace(pos_id=4),
    )

    second = log_root / "2026-04-12" / "09_00_00.ulg"
    second.parent.mkdir(parents=True, exist_ok=True)
    second.write_bytes(b"second-flight")
    await service.list_entries(drone)

    completed = await service.perform_download(drone, queued.job.job_id)
    stage_path, _ = await service.get_ready_file(queued.job.job_id)

    assert completed.job.status == "ready"
    assert stage_path.read_bytes() == b"first-flight"


@pytest.mark.asyncio
async def test_active_jobs_are_not_evicted_when_capacity_is_full(tmp_path):
    params = _make_params(tmp_path)
    params.ULOG_DOWNLOAD_MAX_JOBS = 1
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[
            SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=32),
            SimpleNamespace(id=10, date="2026-04-11T10:23:33Z", size_bytes=32),
        ]
    )

    first = await service.create_download_job(drone, 9, SimpleNamespace(pos_id=3))
    with pytest.raises(UlogCapacityError, match="currently active") as error:
        await service.create_download_job(drone, 10, SimpleNamespace(pos_id=3))

    assert error.value.code == "ulog_capacity_exceeded"
    assert error.value.http_status == 429
    assert await service.get_job(first.job.job_id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured_root",
    [
        "/",
        "safe/../escape",
    ],
)
async def test_filesystem_fallback_rejects_unsafe_configured_roots(
    tmp_path,
    configured_root,
):
    params = _make_params(tmp_path)
    params.ULOG_FILESYSTEM_FALLBACK_DIRS = configured_root
    service = OnboardUlogService(params, hw_id="21", pos_id=4)

    with pytest.raises(UlogUnsafePathError) as error:
        await service.list_entries(_BrokenDrone())

    assert error.value.code == "ulog_unsafe_path"
    assert error.value.http_status == 409


@pytest.mark.asyncio
async def test_filesystem_fallback_rejects_symlink_root(tmp_path):
    params = _make_params(tmp_path)
    actual_root = tmp_path / "actual-root"
    actual_root.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(actual_root, target_is_directory=True)
    params.ULOG_FILESYSTEM_FALLBACK_DIRS = str(linked_root)
    service = OnboardUlogService(params, hw_id="21", pos_id=4)

    with pytest.raises(UlogUnsafePathError, match="Symlinked ULog directory"):
        await service.list_entries(_BrokenDrone())


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_kind", ["directory_symlink", "file_symlink", "fifo"])
async def test_filesystem_fallback_rejects_unsafe_entries(tmp_path, unsafe_kind):
    params = _make_params(tmp_path)
    root = Path(params.ULOG_FILESYSTEM_FALLBACK_DIRS)
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.ulg").write_bytes(b"outside")

    if unsafe_kind == "directory_symlink":
        (root / "linked").symlink_to(outside, target_is_directory=True)
    elif unsafe_kind == "file_symlink":
        (root / "linked.ulg").symlink_to(outside / "outside.ulg")
    else:
        os.mkfifo(root / "pipe.ulg")

    service = OnboardUlogService(params, hw_id="21", pos_id=4)
    with pytest.raises(UlogUnsafePathError):
        await service.list_entries(_BrokenDrone())


@pytest.mark.asyncio
async def test_filesystem_copy_rejects_inode_replacement_after_inventory(tmp_path):
    params = _make_params(tmp_path)
    source = (
        Path(params.ULOG_FILESYSTEM_FALLBACK_DIRS)
        / "2026-04-11"
        / "08_38_11.ulg"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"trusted-flight")
    service = OnboardUlogService(params, hw_id="21", pos_id=4)
    drone = _BrokenDrone()

    listed = await service.list_entries(drone)
    queued = await service.create_download_job(
        drone,
        listed.files[0].id,
        SimpleNamespace(pos_id=4),
    )
    source.unlink()
    source.write_bytes(b"replacement")

    completed = await service.perform_download(drone, queued.job.job_id)

    assert completed.job.status == "failed"
    assert "changed before access" in (completed.job.error or "")
    assert source.read_bytes() == b"replacement"


@pytest.mark.asyncio
async def test_filesystem_erase_only_removes_indexed_files(tmp_path):
    params = _make_params(tmp_path)
    root = Path(params.ULOG_FILESYSTEM_FALLBACK_DIRS)
    indexed = root / "2026-04-11" / "08_38_11.ulg"
    indexed.parent.mkdir(parents=True)
    indexed.write_bytes(b"indexed")
    service = OnboardUlogService(params, hw_id="21", pos_id=4)
    drone = _BrokenDrone()

    listed = await service.list_entries(drone)
    assert listed.count == 1
    unindexed = root / "2026-04-12" / "09_00_00.ulg"
    unindexed.parent.mkdir(parents=True)
    unindexed.write_bytes(b"created-after-inventory")

    response = await service.erase_all(drone)

    assert response.status == "accepted"
    assert not indexed.exists()
    assert unindexed.read_bytes() == b"created-after-inventory"


@pytest.mark.asyncio
async def test_filesystem_erase_rejects_replaced_symlink_without_touching_target(tmp_path):
    params = _make_params(tmp_path)
    source = Path(params.ULOG_FILESYSTEM_FALLBACK_DIRS) / "flight.ulg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"indexed")
    outside = tmp_path / "outside.ulg"
    outside.write_bytes(b"must-remain")
    service = OnboardUlogService(params, hw_id="21", pos_id=4)
    drone = _BrokenDrone()

    await service.list_entries(drone)
    source.unlink()
    source.symlink_to(outside)

    with pytest.raises(UlogUnsafePathError):
        await service.erase_all(drone)

    assert outside.read_bytes() == b"must-remain"
    assert source.is_symlink()


@pytest.mark.asyncio
async def test_stage_directory_and_download_file_use_restrictive_permissions(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=32)]
    )

    queued = await service.create_download_job(drone, 9, SimpleNamespace(pos_id=3))
    completed = await service.perform_download(drone, queued.job.job_id)
    stage_path, _ = await service.get_ready_file(queued.job.job_id)

    assert completed.job.status == "ready"
    assert stat.S_IMODE(Path(params.ULOG_DOWNLOAD_STAGE_DIR).stat().st_mode) == 0o700
    assert stat.S_IMODE(stage_path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_stage_directory_symlink_is_rejected(tmp_path):
    actual_stage = tmp_path / "actual-stage"
    actual_stage.mkdir()
    linked_stage = tmp_path / "linked-stage"
    linked_stage.symlink_to(actual_stage, target_is_directory=True)
    params = _make_params(tmp_path)
    params.ULOG_DOWNLOAD_STAGE_DIR = str(linked_stage)

    with pytest.raises(UlogUnsafePathError, match="Symlinked ULog directory"):
        OnboardUlogService(params, hw_id="7", pos_id=3)


@pytest.mark.asyncio
async def test_aggregate_staging_quota_rejects_new_job(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_ULOG_DOWNLOAD_AGGREGATE_MAX_BYTES", "48")
    monkeypatch.setenv("MDS_ULOG_DOWNLOAD_MIN_FREE_BYTES", "1")
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[
            SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=32),
            SimpleNamespace(id=10, date="2026-04-11T10:23:33Z", size_bytes=32),
        ]
    )

    await service.create_download_job(drone, 9, SimpleNamespace(pos_id=3))
    with pytest.raises(UlogCapacityError, match="aggregate limit"):
        await service.create_download_job(drone, 10, SimpleNamespace(pos_id=3))


@pytest.mark.asyncio
async def test_free_space_reserve_uses_typed_storage_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_ULOG_DOWNLOAD_MIN_FREE_BYTES", "100")
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=32)]
    )
    monkeypatch.setattr(
        "src.ulog_service.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=120),
    )

    with pytest.raises(UlogStorageError) as error:
        await service.create_download_job(drone, 9, SimpleNamespace(pos_id=3))

    assert error.value.code == "ulog_storage_unavailable"
    assert error.value.http_status == 507


@pytest.mark.asyncio
async def test_expired_job_cleanup_removes_record_and_staged_file(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=32)]
    )

    queued = await service.create_download_job(drone, 9, SimpleNamespace(pos_id=3))
    completed = await service.perform_download(drone, queued.job.job_id)
    stage_path, _ = await service.get_ready_file(queued.job.job_id)
    service._jobs[queued.job.job_id].expires_at = service._now_ms() - 1

    deleted = await service.cleanup_expired_jobs()

    assert completed.job.status == "ready"
    assert deleted == 1
    assert not stage_path.exists()
    assert await service.get_job(queued.job.job_id) is None


@pytest.mark.asyncio
async def test_delete_rejects_active_download_then_succeeds_after_completion(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _BlockingDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=32)]
    )

    queued = await service.create_download_job(drone, 9, SimpleNamespace(pos_id=3))
    transfer = asyncio.create_task(service.perform_download(drone, queued.job.job_id))
    await asyncio.wait_for(drone.log_files.started.wait(), timeout=1)

    with pytest.raises(UlogJobConflictError) as error:
        await service.delete_job(queued.job.job_id)

    assert error.value.code == "ulog_job_conflict"
    assert error.value.http_status == 409
    drone.log_files.release.set()
    completed = await asyncio.wait_for(transfer, timeout=1)
    assert completed.job.status == "ready"
    assert await service.delete_job(queued.job.job_id) is True


@pytest.mark.asyncio
async def test_ready_file_lease_blocks_delete_and_expiry_until_reader_closes(tmp_path):
    params = _make_params(tmp_path)
    service = OnboardUlogService(params, hw_id="7", pos_id=3)
    drone = _FakeDrone(
        entries=[SimpleNamespace(id=9, date="2026-04-11T10:22:33Z", size_bytes=32)]
    )

    queued = await service.create_download_job(drone, 9, SimpleNamespace(pos_id=3))
    completed = await service.perform_download(drone, queued.job.job_id)

    async with service.lease_ready_file(queued.job.job_id) as (
        file_handle,
        stage_path,
        ready_job,
    ):
        service._jobs[queued.job.job_id].expires_at = service._now_ms() - 1

        assert completed.job.status == "ready"
        assert ready_job.job_id == queued.job.job_id
        assert file_handle.read() == b"finished-ulog"
        assert await service.cleanup_expired_jobs() == 0
        assert stage_path.is_file()
        with pytest.raises(UlogJobConflictError):
            await service.delete_job(queued.job.job_id)

    assert await service.cleanup_expired_jobs() == 1
    assert not stage_path.exists()
