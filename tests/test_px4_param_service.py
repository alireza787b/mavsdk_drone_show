from types import SimpleNamespace

from mavsdk.component_information import FloatParam as ComponentFloatParam
from mavsdk.param import AllParams, CustomParam, FloatParam, IntParam

from src.px4_param_models import (
    Px4ParamPatchApplyRequest,
    Px4ParamPatchSource,
    Px4ParamSetRequest,
    Px4ParamValueType,
)
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
            ComponentFloatParam(
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


def _build_service():
    params = SimpleNamespace(
        PX4_PARAMETER_DOCS_VERSION="main",
        PX4_PARAMETER_DOCS_BASE_TEMPLATE="https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html",
        PX4_PARAMETER_MUTATION_REQUIRE_DISARMED=True,
        PX4_PARAMETER_SNAPSHOT_MAX_AGE_SEC=60.0,
        PX4_PARAMETER_FLOAT_VERIFY_TOLERANCE=1e-6,
    )
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
