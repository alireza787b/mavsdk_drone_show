import json
import shutil
import sqlite3
import time

from sar.schemas import (
    CoverageWaypoint,
    DroneCoveragePlan,
    DroneSurveyState,
    FindingType,
    FindingPriority,
    QuickScoutFinding,
    QuickScoutOperationRecord,
    SearchArea,
    SearchAreaPoint,
    SurveyConfig,
    SurveyState,
)
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
