import asyncio
import json
import struct
from types import SimpleNamespace

import pytest
from pymavlink import mavutil
from mavsdk_grpc.param import AllParams, CustomParam, FloatParam, IntParam

from src.px4_param_models import (
    Px4ParamMetadataSource,
    Px4ParamPatchApplyRequest,
    Px4ParamPatchSource,
    Px4ParamSetRequest,
    Px4ParamValueType,
)
from src.px4_params.catalog import Px4ParamCatalogEntry
from src.px4_params.service import Px4ParamService


class FakeParamPlugin:
    def __init__(self):
        self.int_values = {"MAV_SYS_ID": 1}
        self.float_values = {"MPC_XY_CRUISE": 4.5}
        self.custom_values = {"SYS_LABEL": "alpha"}

    async def get_all_params(self):
        return AllParams(
            int_params=[IntParam(name, value) for name, value in self.int_values.items()],
            float_params=[FloatParam(name, value) for name, value in self.float_values.items()],
            custom_params=[CustomParam(name, value) for name, value in self.custom_values.items()],
        )

    async def get_param_int(self, name):
        if name not in self.int_values:
            raise RuntimeError("wrong type")
        return self.int_values[name]

    async def set_param_int(self, name, value):
        if name not in self.int_values:
            raise RuntimeError("unknown param")
        self.int_values[name] = int(value)

    async def get_param_float(self, name):
        if name not in self.float_values:
            raise RuntimeError("wrong type")
        return self.float_values[name]

    async def set_param_float(self, name, value):
        if name not in self.float_values:
            raise RuntimeError("unknown param")
        self.float_values[name] = float(value)

    async def get_param_custom(self, name):
        if name not in self.custom_values:
            raise RuntimeError("wrong type")
        return self.custom_values[name]

    async def set_param_custom(self, name, value):
        if name not in self.custom_values:
            raise RuntimeError("unknown param")
        self.custom_values[name] = str(value)


class FakeComponentInformation:
    async def access_float_params(self):
        return [
            SimpleNamespace(
                name="MPC_XY_CRUISE",
                short_description="Cruise speed",
                long_description="Cruise speed setpoint",
                unit="m/s",
                decimal_places=2,
                start_value=4.5,
                default_value=5.0,
                min_value=0.0,
                max_value=20.0,
            )
        ]


class BrokenComponentInformation:
    async def access_float_params(self):
        raise ValueError("component information unavailable")


def _build_service(*, state_dir=None):
    params = SimpleNamespace(
        PX4_PARAMETER_DOCS_VERSION="main",
        PX4_PARAMETER_DOCS_BASE_TEMPLATE="https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html",
        PX4_PARAMETER_MUTATION_REQUIRE_DISARMED=True,
        PX4_PARAMETER_SNAPSHOT_MAX_AGE_SEC=60.0,
        PX4_PARAMETER_FLOAT_VERIFY_TOLERANCE=1e-6,
        PX4_PARAMETER_MAVLINK_HEARTBEAT_TIMEOUT_SEC=5.0,
        PX4_PARAMETER_MAVLINK_SNAPSHOT_TIMEOUT_SEC=45.0,
        PX4_PARAMETER_MAVLINK_IDLE_TIMEOUT_SEC=1.5,
        PX4_PARAMETER_METADATA_CATALOG_PATHS="",
        PX4_PARAMETER_ONLINE_DOCS_METADATA_ENABLED=False,
        local_mavlink2rest_port=14569,
    )
    if state_dir is not None:
        params.PX4_PARAMETER_OPERATION_STATE_DIR = state_dir
    return Px4ParamService(params, hw_id="7")


def _build_drone():
    return SimpleNamespace(
        param=FakeParamPlugin(),
        component_information=FakeComponentInformation(),
    )


async def test_build_snapshot_returns_sorted_rows_with_docs_and_float_metadata():
    service = _build_service()
    drone = _build_drone()

    snapshot = await service.build_snapshot(drone)

    assert snapshot.snapshot.hw_id == "7"
    assert snapshot.snapshot.total_params == 3
    assert [row.name for row in snapshot.rows] == ["MAV_SYS_ID", "MPC_XY_CRUISE", "SYS_LABEL"]

    float_row = next(row for row in snapshot.rows if row.name == "MPC_XY_CRUISE")
    assert float_row.docs_url.endswith("#MPC_XY_CRUISE")
    assert float_row.short_description == "Cruise speed"
    assert float_row.default_value == 5.0
    assert float_row.min_value == 0.0
    assert float_row.max_value == 20.0


async def test_build_snapshot_uses_catalog_metadata_for_non_float_rows(tmp_path):
    catalog_path = tmp_path / "parameters.json"
    catalog_path.write_text(json.dumps({
        "version": 1,
        "parameters": [
            {
                "name": "MAV_SYS_ID",
                "shortDesc": "System ID",
                "longDesc": "MAVLink system identifier.",
                "default": 1,
                "min": 1,
                "max": 255,
                "rebootRequired": True,
                "group": "MAVLink",
                "category": "Standard",
                "type": "Int32",
            }
        ],
    }))
    service = _build_service()
    service.params.PX4_PARAMETER_METADATA_CATALOG_PATHS = str(catalog_path)
    drone = _build_drone()

    snapshot = await service.build_snapshot(drone)

    mav_sys_id = next(row for row in snapshot.rows if row.name == "MAV_SYS_ID")
    assert mav_sys_id.short_description == "System ID"
    assert mav_sys_id.long_description == "MAVLink system identifier."
    assert mav_sys_id.default_value == 1
    assert mav_sys_id.min_value == 1
    assert mav_sys_id.max_value == 255
    assert mav_sys_id.reboot_required is True
    assert mav_sys_id.group == "MAVLink"
    assert "px4_build_catalog" in mav_sys_id.metadata_sources


async def test_build_snapshot_labels_docs_cache_metadata(monkeypatch):
    service = _build_service()
    drone = _build_drone()

    monkeypatch.setattr(
        "src.px4_params.service.load_px4_param_catalog_index",
        lambda _params: {
            "MAV_SYS_ID": Px4ParamCatalogEntry(
                name="MAV_SYS_ID",
                source=Px4ParamMetadataSource.PX4_DOCS_CACHE,
                short_description="System ID from docs",
                long_description="System ID from docs\n\nExtended system identifier guidance.",
                default_value=1,
                group="MAVLink",
            )
        },
    )

    snapshot = await service.build_snapshot(drone)

    mav_sys_id = next(row for row in snapshot.rows if row.name == "MAV_SYS_ID")
    assert mav_sys_id.short_description == "System ID from docs"
    assert mav_sys_id.long_description == "Extended system identifier guidance."
    assert "px4_docs_cache" in mav_sys_id.metadata_sources


async def test_build_snapshot_falls_back_to_mavlink_listing_when_bulk_rpc_is_unavailable():
    service = _build_service()

    class _UnavailableBulkParamPlugin:
        async def get_all_params(self):
            raise RuntimeError("GetAllParams unimplemented")

    drone = SimpleNamespace(
        param=_UnavailableBulkParamPlugin(),
        component_information=FakeComponentInformation(),
    )

    service._collect_mavlink_param_entries_blocking = lambda component_id: [
        {
            "name": "MAV_SYS_ID",
            "value_type": Px4ParamValueType.INT,
            "value": 7,
        },
        {
            "name": "MPC_XY_CRUISE",
            "value_type": Px4ParamValueType.FLOAT,
            "value": 4.5,
        },
    ]

    snapshot = await service.build_snapshot(drone)

    assert snapshot.snapshot.total_params == 2
    assert [row.name for row in snapshot.rows] == ["MAV_SYS_ID", "MPC_XY_CRUISE"]
    assert next(row for row in snapshot.rows if row.name == "MPC_XY_CRUISE").default_value == 5.0


async def test_build_snapshot_treats_component_information_failures_as_best_effort():
    service = _build_service()

    class _UnavailableBulkParamPlugin:
        async def get_all_params(self):
            raise RuntimeError("GetAllParams unimplemented")

    drone = SimpleNamespace(
        param=_UnavailableBulkParamPlugin(),
        component_information=BrokenComponentInformation(),
    )

    service._collect_mavlink_param_entries_blocking = lambda component_id: [
        {
            "name": "MAV_SYS_ID",
            "value_type": Px4ParamValueType.INT,
            "value": 7,
        }
    ]

    snapshot = await service.build_snapshot(drone)

    assert snapshot.snapshot.total_params == 1
    row = snapshot.rows[0]
    assert row.name == "MAV_SYS_ID"
    assert row.short_description is None


async def test_get_param_value_auto_detects_type():
    service = _build_service()
    drone = _build_drone()

    response = await service.get_param_value(drone, "sys_label")

    assert response.row.name == "SYS_LABEL"
    assert response.row.value_type == Px4ParamValueType.CUSTOM
    assert response.row.value == "alpha"


async def test_set_param_value_verifies_readback():
    service = _build_service()
    drone = _build_drone()

    response = await service.set_param_value(
        drone,
        "MAV_SYS_ID",
        Px4ParamSetRequest(
            component_id=1,
            value_type=Px4ParamValueType.INT,
            value=9,
            verify_readback=True,
        ),
    )

    assert response.applied is True
    assert response.verified is True
    assert response.actual_value == 9
    assert drone.param.int_values["MAV_SYS_ID"] == 9


async def test_apply_patch_reports_partial_failures():
    service = _build_service()
    drone = _build_drone()

    response = await service.apply_patch(
        drone,
        Px4ParamPatchApplyRequest(
            source=Px4ParamPatchSource.API,
            verify_readback=True,
            entries=[
                {
                    "name": "MAV_SYS_ID",
                    "value_type": "int",
                    "value": 11,
                },
                {
                    "name": "NO_SUCH_PARAM",
                    "value_type": "int",
                    "value": 1,
                },
            ],
        ),
    )

    assert response.applied_count == 1
    assert response.failed_count == 1
    assert response.verified_count == 1
    assert response.results[0].applied is True
    assert response.results[1].applied is False


def test_decode_mavlink_param_value_handles_integer_and_float_payloads():
    service = _build_service()

    encoded_int = struct.unpack(">f", struct.pack(">i", 42))[0]
    int_type, int_value = service._decode_mavlink_param_value(
        mavutil.mavlink.MAV_PARAM_TYPE_INT32,
        encoded_int,
    )
    float_type, float_value = service._decode_mavlink_param_value(
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        12.75,
    )

    assert int_type == Px4ParamValueType.INT
    assert int_value == 42
    assert float_type == Px4ParamValueType.FLOAT
    assert float_value == 12.75


def _reviewed_request(*, operation_id="op-1", entries=None, **overrides):
    return Px4ParamPatchApplyRequest(
        operation_id=operation_id, expected_hw_id="7",
        entries=entries or [{"name": "MAV_SYS_ID", "value_type": "int", "value": 9, "expected_current_value": 1}],
        **overrides,
    )


async def test_reviewed_patch_checks_all_expected_values_before_any_write(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    response = await service.apply_patch(drone, _reviewed_request(entries=[
        {"name": "MAV_SYS_ID", "value_type": "int", "value": 9, "expected_current_value": 1},
        {"name": "MPC_XY_CRUISE", "value_type": "float", "value": 8.0, "expected_current_value": 3.0},
    ]))
    assert response.applied_count == 0
    assert drone.param.int_values["MAV_SYS_ID"] == 1
    assert all(result.error_phase == "precondition" for result in response.results)


async def test_native_idempotency_survives_service_restart_and_rejects_payload_conflict(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    first = await service.apply_patch(drone, _reviewed_request())
    restarted = _build_service(state_dir=tmp_path)
    drone.param.int_values["MAV_SYS_ID"] = 12
    replay = await restarted.apply_patch(drone, _reviewed_request())
    assert replay.model_dump() == first.model_dump()
    assert drone.param.int_values["MAV_SYS_ID"] == 12
    with pytest.raises(ValueError, match="different"):
        await restarted.apply_patch(drone, _reviewed_request(entries=[
            {"name": "MAV_SYS_ID", "value_type": "int", "value": 8, "expected_current_value": 1},
        ]))


async def test_unknown_write_outcome_is_not_replayed_or_followed_by_more_writes(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    writes = []

    async def uncertain_write(name, value):
        writes.append(name)
        drone.param.int_values[name] = value
        raise TimeoutError("write acknowledgment lost")

    drone.param.set_param_int = uncertain_write
    request = _reviewed_request(entries=[
        {"name": "MAV_SYS_ID", "value_type": "int", "value": 9, "expected_current_value": 1},
        {"name": "MPC_XY_CRUISE", "value_type": "float", "value": 8.0, "expected_current_value": 4.5},
    ])
    response = await service.apply_patch(drone, request)
    assert response.results[0].outcome == "unknown"
    assert response.results[0].applied is False  # acknowledgment, not proof of no write
    assert response.results[1].outcome == "not_attempted"
    replay = await _build_service(state_dir=tmp_path).apply_patch(drone, request)
    assert replay.results[0].outcome == "unknown"
    assert writes == ["MAV_SYS_ID"]
    assert drone.param.float_values["MPC_XY_CRUISE"] == 4.5


async def test_cancelled_native_write_remains_unknown_after_restart(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    write_started = asyncio.Event()
    writes = []

    async def interrupted_write(name, value):
        writes.append(name)
        write_started.set()
        await asyncio.Event().wait()

    drone.param.set_param_int = interrupted_write
    task = asyncio.create_task(service.apply_patch(drone, _reviewed_request()))
    await asyncio.wait_for(write_started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    response = await _build_service(state_dir=tmp_path).apply_patch(drone, _reviewed_request())
    assert response.results[0].outcome == "unknown"
    assert writes == ["MAV_SYS_ID"]


async def test_write_acknowledged_but_readback_unavailable_is_not_reported_as_failed_write(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    wrote = False

    async def write(name, value):
        nonlocal wrote
        wrote = True

    async def read(name):
        if wrote:
            raise TimeoutError("readback unavailable")
        return 1

    drone.param.set_param_int, drone.param.get_param_int = write, read
    response = await service.apply_patch(drone, _reviewed_request())
    result = response.results[0]
    assert result.applied is True
    assert result.write_acknowledged is True
    assert result.verified is False
    assert result.outcome == "written_unverified"
    assert result.readback_status == "unavailable"
    assert result.error_phase == "readback"


async def test_readback_mismatch_is_explicit(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()

    async def mismatched_write(name, value):
        drone.param.int_values[name] = value + 1

    drone.param.set_param_int = mismatched_write
    response = await service.apply_patch(drone, _reviewed_request())
    assert response.results[0].outcome == "verification_failed"
    assert response.results[0].actual_value == 10
    assert response.applied_count == 1
    assert response.failed_count == 1


async def test_native_identity_and_component_eligibility_reject_before_vehicle_access(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    request = _reviewed_request().model_copy(update={"expected_hw_id": "8"})
    with pytest.raises(ValueError, match="identity"):
        await service.apply_patch(drone, request)
    with pytest.raises(ValueError, match="component 1"):
        await service.apply_patch(drone, _reviewed_request(entries=[
            {"component_id": 2, "name": "MAV_SYS_ID", "value_type": "int", "value": 9},
        ]))
    with pytest.raises(ValueError, match="component 1"):
        await service.build_snapshot(drone, component_id=2)
    assert drone.param.int_values["MAV_SYS_ID"] == 1


async def test_concurrent_same_operation_is_only_written_once(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    original_write = drone.param.set_param_int
    writes = []

    async def write(name, value):
        writes.append(name)
        await asyncio.sleep(0)
        await original_write(name, value)

    drone.param.set_param_int = write
    responses = await asyncio.gather(
        service.apply_patch(drone, _reviewed_request()), service.apply_patch(drone, _reviewed_request()),
    )
    assert writes == ["MAV_SYS_ID"]
    assert responses[0].model_dump() == responses[1].model_dump()


async def test_vehicle_range_is_enforced_but_reference_catalog_range_is_not(monkeypatch):
    service, drone = _build_service(), _build_drone()
    request = Px4ParamPatchApplyRequest(entries=[
        {"name": "MPC_XY_CRUISE", "value_type": "float", "value": 21.0},
    ])
    response = await service.apply_patch(drone, request)
    assert response.results[0].error_phase == "precondition"
    assert drone.param.float_values["MPC_XY_CRUISE"] == 4.5
    drone.component_information = None
    monkeypatch.setattr(service, "_load_catalog_metadata", lambda: {
        "MPC_XY_CRUISE": Px4ParamCatalogEntry(name="MPC_XY_CRUISE", max_value=1.0),
    })
    response = await service.apply_patch(drone, request)
    assert response.results[0].outcome == "verified"


async def test_docs_metadata_is_reference_only_not_a_firmware_matched_catalog(monkeypatch):
    service, drone = _build_service(), _build_drone()
    drone.component_information = None
    monkeypatch.setattr(service, "_load_catalog_metadata", lambda: {
        "MAV_SYS_ID": Px4ParamCatalogEntry(name="MAV_SYS_ID", source=Px4ParamMetadataSource.PX4_DOCS_CACHE, default_value=1),
    })
    snapshot = await service.build_snapshot(drone)
    assert snapshot.snapshot.metadata_quality == "reference_only"
    assert snapshot.snapshot.metadata_catalog_available is False
    assert snapshot.rows[0].metadata_authority == "reference_only"
    assert snapshot.rows[0].authoritative_fields == []
    assert "component_information" in snapshot.snapshot.metadata_warning
    assert "No reference metadata is promoted" in snapshot.snapshot.metadata_warning


async def test_vehicle_metadata_wins_over_unmatched_reference_catalog(monkeypatch):
    service, drone = _build_service(), _build_drone()
    monkeypatch.setattr(service, "_load_catalog_metadata", lambda: {
        "MPC_XY_CRUISE": Px4ParamCatalogEntry(name="MPC_XY_CRUISE", min_value=100.0, max_value=200.0, default_value=150.0),
    })
    snapshot = await service.build_snapshot(drone)
    row = next(row for row in snapshot.rows if row.name == "MPC_XY_CRUISE")
    assert row.min_value == 0.0
    assert row.max_value == 20.0
    assert row.default_value == 5.0
    assert row.metadata_authority == "vehicle"
    assert "min_value" in row.authoritative_fields


async def test_full_native_journal_keeps_existing_receipts_and_refuses_new_identities(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    service._operations.max_records = 1
    first = await service.apply_patch(drone, _reviewed_request())
    with pytest.raises(RuntimeError, match="journal is full"):
        await service.apply_patch(drone, _reviewed_request(operation_id="new-op", entries=[
            {"name": "MAV_SYS_ID", "value_type": "int", "value": 10, "expected_current_value": 9},
        ]))
    replay = await service.apply_patch(drone, _reviewed_request())
    assert replay.model_dump() == first.model_dump()
    assert drone.param.int_values["MAV_SYS_ID"] == 9


async def test_mid_patch_arm_guard_failure_stops_reviewed_remainder(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    checks = 0

    async def guard(_drone):
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise ValueError("native arm state is armed or unavailable")

    response = await service.apply_patch(drone, _reviewed_request(entries=[
        {"name": "MAV_SYS_ID", "value_type": "int", "value": 9, "expected_current_value": 1},
        {"name": "MPC_XY_CRUISE", "value_type": "float", "value": 8.0, "expected_current_value": 4.5},
        {"name": "SYS_LABEL", "value_type": "custom", "value": "beta", "expected_current_value": "alpha"},
    ]), mutation_guard=guard)
    assert [result.outcome for result in response.results] == ["verified", "failed", "not_attempted"]
    assert response.results[1].error_phase == "precondition"
    assert drone.param.float_values["MPC_XY_CRUISE"] == 4.5
    assert drone.param.custom_values["SYS_LABEL"] == "alpha"


async def test_journal_byte_limit_admission_is_fail_closed_but_existing_receipts_still_recover(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()
    first = await service.apply_patch(drone, _reviewed_request())
    service._operations.max_bytes = 16384
    with pytest.raises(RuntimeError, match="storage capacity"):
        await service.apply_patch(drone, _reviewed_request(operation_id="new-op", entries=[
            {"name": "MAV_SYS_ID", "value_type": "int", "value": 10, "expected_current_value": 9},
        ]))
    replay = await service.apply_patch(drone, _reviewed_request())
    assert replay.model_dump() == first.model_dump()
    assert drone.param.int_values["MAV_SYS_ID"] == 9


async def test_receipt_storage_is_reserved_before_write_for_escaped_errors(tmp_path):
    service, drone = _build_service(state_dir=tmp_path), _build_drone()

    async def guard(_drone):
        raise ValueError("\x00" * 2048)

    response = await service.apply_patch(drone, _reviewed_request(), mutation_guard=guard)
    assert response.results[0].outcome == "failed"
    replay = await _build_service(state_dir=tmp_path).apply_patch(drone, _reviewed_request())
    assert replay.model_dump() == response.model_dump()


def test_legacy_absolute_tolerance_cannot_widen_native_wire_identity():
    service = _build_service()
    service.params.PX4_PARAMETER_FLOAT_VERIFY_TOLERANCE = 100.0
    assert not service._values_match(Px4ParamValueType.FLOAT, 1e-7, 0.0)
    assert not service._values_match(Px4ParamValueType.FLOAT, 1e-7, 2e-7)
    rounded = struct.unpack("!f", struct.pack("!f", 1000.00001))[0]
    assert service._values_match(Px4ParamValueType.FLOAT, 1000.00001, rounded)


async def test_tiny_float_readback_mismatch_is_not_verified():
    service, drone = _build_service(), _build_drone()
    drone.param.float_values["MPC_XY_CRUISE"] = 1e-7

    async def incorrectly_written_float(name, value):
        drone.param.float_values[name] = 0.0

    drone.param.set_param_float = incorrectly_written_float
    response = await service.apply_patch(drone, Px4ParamPatchApplyRequest(entries=[
        {"name": "MPC_XY_CRUISE", "value_type": "float", "value": 1e-7, "expected_current_value": 1e-7},
    ]))
    assert response.results[0].outcome == "verification_failed"
    assert response.results[0].verified is False
    assert response.results[0].actual_value == 0.0


async def test_tiny_float_expected_value_drift_blocks_write():
    service, drone = _build_service(), _build_drone()
    drone.param.float_values["MPC_XY_CRUISE"] = 0.0
    response = await service.apply_patch(drone, Px4ParamPatchApplyRequest(entries=[
        {"name": "MPC_XY_CRUISE", "value_type": "float", "value": 2e-7, "expected_current_value": 1e-7},
    ]))
    assert response.applied_count == 0
    assert response.results[0].error_phase == "precondition"
    assert drone.param.float_values["MPC_XY_CRUISE"] == 0.0
