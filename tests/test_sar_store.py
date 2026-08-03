import json
import asyncio
import shutil
import sqlite3
import threading
import time
from types import SimpleNamespace

from sar.schemas import (
    CoverageWaypoint,
    DroneCoveragePlan,
    DroneSurveyState,
    FindingType,
    FindingPriority,
    QuickScoutCommandAction,
    QuickScoutCommandLifecycleState,
    QuickScoutFinding,
    QuickScoutOperationRecord,
    SearchArea,
    SearchAreaPoint,
    SurveyConfig,
    SurveyState,
)
from sar.command_lifecycle import build_queued_command_batch
from schemas import CommandSubmissionReceipt
from src.enums import Mission
import sar.store as store_module


def _build_operation() -> QuickScoutOperationRecord:
    search_area = SearchArea(
        points=[
            SearchAreaPoint(lat=47.0, lng=8.0),
            SearchAreaPoint(lat=47.001, lng=8.0),
            SearchAreaPoint(lat=47.001, lng=8.001),
        ]
    )
    waypoint = CoverageWaypoint(
        lat=47.0,
        lng=8.0,
        alt_msl=50.0,
        is_survey_leg=True,
        speed_ms=5.0,
        sequence=0,
    )
    plan = DroneCoveragePlan(
        hw_id="1",
        pos_id=0,
        waypoints=[waypoint],
        assigned_area_sq_m=100.0,
        estimated_duration_s=10.0,
        total_distance_m=50.0,
    )
    now = time.time()
    return QuickScoutOperationRecord(
        mission_id="mission-1",
        mission_template="last_known_point",
        mission_label="Harbor sweep",
        mission_profile="rapid_search",
        mission_brief="Search quay perimeter",
        state=SurveyState.READY,
        search_area=search_area,
        survey_config=SurveyConfig(),
        plans=[plan],
        drone_states={
            "1": DroneSurveyState(hw_id="1", state=SurveyState.READY, total_waypoints=0),
        },
        total_area_sq_m=100.0,
        estimated_coverage_time_s=10.0,
        algorithm_used="boustrophedon",
        created_at=now,
        updated_at=now,
    )


def test_quickscout_store_persists_operations(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(tmp_path / "quickscout.sqlite3"))
    store_module._store_instance = None

    store = store_module.get_quickscout_store()
    operation = _build_operation()
    store.save_operation(operation)

    store_module._store_instance = None
    reopened = store_module.get_quickscout_store()
    loaded = reopened.get_operation("mission-1")

    assert loaded is not None
    assert loaded.mission_id == "mission-1"
    assert loaded.mission_template == "last_known_point"
    assert loaded.mission_label == "Harbor sweep"
    assert loaded.state == SurveyState.READY
    assert loaded.total_area_sq_m == 100.0


def test_quickscout_store_persists_typed_command_batch_across_reopen(tmp_path, monkeypatch):
    db_path = tmp_path / "quickscout.sqlite3"
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(db_path))
    store_module._store_instance = None

    operation = _build_operation()
    operation.latest_command_batch = build_queued_command_batch(
        action=QuickScoutCommandAction.LAUNCH,
        attempt=1,
        receipt=CommandSubmissionReceipt(
            command_id="command-1",
            idempotency_key="quickscout:mission-1:launch:1",
            replayed=False,
            mission_type=Mission.QUICKSCOUT.value,
            mission_name="QUICKSCOUT",
            target_drones=["1"],
            tracking_url="/api/v1/commands/command-1",
            message="Tracked command queued.",
            timestamp=1_700_000_000_000,
        ),
        now_ms=1_700_000_000_000,
    )
    store_module.get_quickscout_store().save_operation(operation)

    store_module._store_instance = None
    loaded = store_module.get_quickscout_store().get_operation(operation.mission_id)

    assert loaded.latest_command_batch is not None
    assert loaded.latest_command_batch.action == QuickScoutCommandAction.LAUNCH
    assert loaded.latest_command_batch.state == QuickScoutCommandLifecycleState.QUEUED
    assert loaded.latest_command_batch.targets["1"].state == QuickScoutCommandLifecycleState.QUEUED
    assert loaded.latest_command_batch.receipt.command_id == "command-1"

    with sqlite3.connect(db_path) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM quickscout_operations WHERE mission_id = ?",
                (operation.mission_id,),
            ).fetchone()[0]
        )
    assert "latest_command_batch" in payload


def test_quickscout_store_round_trips_numeric_target_ids_across_reopen(tmp_path, monkeypatch):
    db_path = tmp_path / "quickscout.sqlite3"
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(db_path))
    store_module._store_instance = None
    target_ids = ["1", "2", "10", "100"]

    operation = _build_operation()
    operation.latest_command_batch = build_queued_command_batch(
        action=QuickScoutCommandAction.LAUNCH,
        attempt=1,
        receipt=CommandSubmissionReceipt(
            command_id="command-four-targets",
            idempotency_key="quickscout:mission-1:launch:1",
            replayed=False,
            mission_type=Mission.QUICKSCOUT.value,
            mission_name="QUICKSCOUT",
            target_drones=target_ids,
            tracking_url="/api/v1/commands/command-four-targets",
            message="Tracked command queued.",
            timestamp=1_700_000_000_000,
        ),
        now_ms=1_700_000_000_000,
    )
    store_module.get_quickscout_store().save_operation(operation)

    store_module._store_instance = None
    loaded = store_module.get_quickscout_store().get_operation(operation.mission_id)

    assert loaded is not None
    assert loaded.latest_command_batch is not None
    assert loaded.latest_command_batch.receipt.target_drones == target_ids
    assert set(loaded.latest_command_batch.targets) == set(target_ids)


def test_quickscout_store_serializes_concurrent_mission_mutations(tmp_path):
    db_path = tmp_path / "quickscout.sqlite3"
    first_store = store_module.QuickScoutStore(str(db_path))
    second_store = store_module.QuickScoutStore(str(db_path))
    operation = _build_operation()
    operation.state = SurveyState.EXECUTING
    operation.drone_states["1"].state = SurveyState.EXECUTING
    operation.drone_states["1"].total_waypoints = 10
    first_store.save_operation(operation)

    first_mutation_entered = threading.Event()
    second_mutation_started = threading.Event()
    release_first_mutation = threading.Event()

    def update_progress(current):
        first_mutation_entered.set()
        assert release_first_mutation.wait(timeout=2.0)
        current.drone_states["1"].current_waypoint_index = 4
        current.drone_states["1"].coverage_percent = 40.0
        return current

    def update_lifecycle(current):
        current.latest_command_batch = build_queued_command_batch(
            action=QuickScoutCommandAction.PAUSE,
            attempt=1,
            receipt=CommandSubmissionReceipt(
                command_id="pause-command",
                idempotency_key="quickscout:mission-1:pause:1",
                replayed=False,
                mission_type=Mission.HOLD.value,
                mission_name=Mission.HOLD.name,
                target_drones=["1"],
                tracking_url="/api/v1/commands/pause-command",
                message="Tracked command queued.",
                timestamp=1_700_000_000_000,
            ),
            now_ms=1_700_000_000_000,
        )
        return current

    first_thread = threading.Thread(
        target=lambda: first_store.mutate_operation(operation.mission_id, update_progress)
    )

    def run_second_mutation():
        second_mutation_started.set()
        second_store.mutate_operation(operation.mission_id, update_lifecycle)

    second_thread = threading.Thread(target=run_second_mutation)
    first_thread.start()
    assert first_mutation_entered.wait(timeout=2.0)
    second_thread.start()
    assert second_mutation_started.wait(timeout=2.0)
    release_first_mutation.set()
    first_thread.join(timeout=2.0)
    second_thread.join(timeout=2.0)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    loaded = first_store.get_operation(operation.mission_id)
    assert loaded is not None
    assert loaded.drone_states["1"].current_waypoint_index == 4
    assert loaded.drone_states["1"].coverage_percent == 40.0
    assert loaded.latest_command_batch is not None
    assert loaded.latest_command_batch.receipt.command_id == "pause-command"


def test_quickscout_service_serializes_concurrent_pause_and_abort(
    tmp_path,
    monkeypatch,
):
    import sar.service as service_module
    from fastapi import HTTPException

    store = store_module.QuickScoutStore(str(tmp_path / "quickscout.sqlite3"))
    operation = _build_operation()
    operation.state = SurveyState.EXECUTING
    operation.drone_states["1"].state = SurveyState.EXECUTING
    operation.started_at = time.time()
    store.save_operation(operation)
    service = service_module.QuickScoutService(store=store)
    submitted_requests = []

    async def exercise_concurrent_controls():
        submission_started = asyncio.Event()
        release_submission = asyncio.Event()

        async def fake_submit(_deps, request, **_kwargs):
            submitted_requests.append(request)
            submission_started.set()
            await release_submission.wait()
            return CommandSubmissionReceipt(
                command_id="serialized-control",
                idempotency_key=request.idempotency_key,
                replayed=False,
                mission_type=request.mission_type,
                mission_name=Mission(request.mission_type).name,
                target_drones=list(request.target_drone_ids),
                tracking_url="/api/v1/commands/serialized-control",
                message="Tracked command queued.",
                timestamp=1_700_000_000_000,
            )

        monkeypatch.setattr(service_module, "submit_tracked_command", fake_submit)
        deps = SimpleNamespace()
        pause_task = asyncio.create_task(
            service.pause_and_command(deps, operation.mission_id)
        )
        await asyncio.wait_for(submission_started.wait(), timeout=2.0)
        abort_task = asyncio.create_task(
            service.abort_and_command(deps, operation.mission_id)
        )
        await asyncio.sleep(0)
        release_submission.set()
        return await asyncio.gather(pause_task, abort_task, return_exceptions=True)

    pause_result, abort_result = asyncio.run(exercise_concurrent_controls())

    assert pause_result.latest_command_batch.action == QuickScoutCommandAction.PAUSE
    assert isinstance(abort_result, HTTPException)
    assert abort_result.status_code == 409
    assert abort_result.detail["code"] == "quickscout_command_in_progress"
    assert len(submitted_requests) == 1
    loaded = store.get_operation(operation.mission_id)
    assert loaded is not None
    assert loaded.latest_command_batch is not None
    assert loaded.latest_command_batch.action == QuickScoutCommandAction.PAUSE


def test_reconciliation_merges_with_progress_written_while_tracker_read_is_in_flight(
    tmp_path,
):
    import sar.service as service_module

    store = store_module.QuickScoutStore(str(tmp_path / "quickscout.sqlite3"))
    operation = _build_operation()
    operation.state = SurveyState.EXECUTING
    operation.drone_states["1"].state = SurveyState.EXECUTING
    operation.drone_states["1"].total_waypoints = 10
    operation.latest_command_batch = build_queued_command_batch(
        action=QuickScoutCommandAction.LAUNCH,
        attempt=1,
        receipt=CommandSubmissionReceipt(
            command_id="launch-command",
            idempotency_key="quickscout:mission-1:launch:1",
            replayed=False,
            mission_type=Mission.QUICKSCOUT.value,
            mission_name=Mission.QUICKSCOUT.name,
            target_drones=["1"],
            tracking_url="/api/v1/commands/launch-command",
            message="Tracked command queued.",
            timestamp=1_700_000_000_000,
        ),
        now_ms=1_700_000_000_000,
    )
    store.save_operation(operation)
    service = service_module.QuickScoutService(store=store)

    async def exercise_overlap():
        tracker_read_started = asyncio.Event()
        release_tracker_read = asyncio.Event()

        class DelayedTracker:
            async def get_status(self, _command_id):
                tracker_read_started.set()
                await release_tracker_read.wait()
                return {
                    "command_id": "launch-command",
                    "target_drones": ["1"],
                    "phase": "pending_execution",
                    "outcome": None,
                    "params": {"trigger_time": 1_700_000_005},
                    "timeout_at": 1_700_000_120_000,
                    "preparations": {"details": {}},
                    "acks": {
                        "details": {
                            "1": {
                                "category": "accepted",
                                "delivery_state": "accepted",
                            }
                        }
                    },
                    "executions": {"started_hw_ids": [], "details": {}},
                    "late_reports": {},
                    "progress": {"message": "Waiting for execution evidence."},
                }

        tracker = DelayedTracker()
        deps = SimpleNamespace(get_command_tracker=lambda: tracker)
        reconcile_task = asyncio.create_task(
            service.reconcile_latest_command(deps, operation.mission_id)
        )
        await asyncio.wait_for(tracker_read_started.wait(), timeout=2.0)
        assert service.update_drone_progress(
            operation.mission_id,
            "1",
            current_waypoint_index=3,
            total_waypoints=10,
            distance_covered_m=25.0,
        )
        release_tracker_read.set()
        await reconcile_task

    asyncio.run(exercise_overlap())

    loaded = store.get_operation(operation.mission_id)
    assert loaded is not None
    assert loaded.drone_states["1"].current_waypoint_index == 3
    assert loaded.drone_states["1"].distance_covered_m == 25.0
    assert loaded.latest_command_batch is not None
    assert loaded.latest_command_batch.state == QuickScoutCommandLifecycleState.ACCEPTED


def test_quickscout_store_persists_findings(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(tmp_path / "quickscout.sqlite3"))
    store_module._store_instance = None

    store = store_module.get_quickscout_store()
    store.save_operation(_build_operation())
    finding = QuickScoutFinding(
        id="finding-1",
        lat=47.0,
        lng=8.0,
        notes="marker",
        mission_id="mission-1",
        summary="Dock contact",
        type=FindingType.VESSEL,
        priority=FindingPriority.HIGH,
    )
    store.save_finding("mission-1", finding)

    store_module._store_instance = None
    reopened = store_module.get_quickscout_store()
    loaded = reopened.list_findings("mission-1")

    assert len(loaded) == 1
    assert loaded[0].id == "finding-1"
    assert loaded[0].notes == "marker"
    assert loaded[0].summary == "Dock contact"


def test_quickscout_store_recreates_runtime_directory_between_connections(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_data" / "quickscout" / "quickscout.sqlite3"
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(db_path))
    store_module._store_instance = None

    store = store_module.get_quickscout_store()
    shutil.rmtree(db_path.parent)

    assert list(store.list_operations()) == []
    assert db_path.exists()


def test_quickscout_store_migrates_legacy_poi_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "quickscout.sqlite3"
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(db_path))
    store_module._store_instance = None

    operation = _build_operation()
    payload = QuickScoutFinding(
        id="legacy-poi-1",
        lat=47.0,
        lng=8.0,
        summary="Legacy dock contact",
        mission_id=operation.mission_id,
    ).model_dump(mode="json")

    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE quickscout_operations (
            mission_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE quickscout_pois (
            poi_id TEXT PRIMARY KEY,
            mission_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            updated_at REAL NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO quickscout_operations (mission_id, state, created_at, updated_at, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            operation.mission_id,
            operation.state.value,
            float(operation.created_at),
            float(operation.updated_at),
            json.dumps(operation.model_dump(mode="json"), sort_keys=True),
        ),
    )
    connection.execute(
        """
        INSERT INTO quickscout_pois (poi_id, mission_id, timestamp, updated_at, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            payload["id"],
            operation.mission_id,
            float(payload.get("timestamp") or operation.created_at),
            float(operation.updated_at),
            json.dumps(payload, sort_keys=True),
        ),
    )
    connection.commit()
    connection.close()

    reopened = store_module.get_quickscout_store()
    loaded = reopened.list_findings(operation.mission_id)

    assert len(loaded) == 1
    assert loaded[0].id == "legacy-poi-1"
    assert loaded[0].summary == "Legacy dock contact"
