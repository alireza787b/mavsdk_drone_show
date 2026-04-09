import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("psutil", MagicMock())

mavsdk_module = types.ModuleType("mavsdk")
mavsdk_module.System = MagicMock()
mavsdk_system_module = types.ModuleType("mavsdk.system")
mavsdk_system_module.System = MagicMock()
mavsdk_telemetry_module = types.ModuleType("mavsdk.telemetry")
mavsdk_telemetry_module.FlightMode = types.SimpleNamespace()
mavsdk_telemetry_module.LandedState = types.SimpleNamespace()
mavsdk_module.telemetry = mavsdk_telemetry_module
mavsdk_module.action = MagicMock()
mavsdk_offboard_module = types.ModuleType("mavsdk.offboard")
for name in (
    "PositionNedYaw",
    "VelocityBodyYawspeed",
    "PositionGlobalYaw",
    "VelocityNedYaw",
    "AccelerationNed",
):
    setattr(mavsdk_offboard_module, name, MagicMock())
mavsdk_offboard_module.OffboardError = Exception
sys.modules.setdefault("mavsdk", mavsdk_module)
sys.modules.setdefault("mavsdk.system", mavsdk_system_module)
sys.modules.setdefault("mavsdk.telemetry", mavsdk_telemetry_module)
sys.modules.setdefault("mavsdk.offboard", mavsdk_offboard_module)
sys.modules.setdefault("mavsdk.action", types.SimpleNamespace(ActionError=Exception))

import actions


@pytest.mark.asyncio
async def test_apply_common_params_reads_configured_common_params_file(tmp_path, mocker):
    common_file = tmp_path / "common_params.csv"
    common_file.write_text(
        "param_name,param_value\n"
        "GF_ACTION,3\n"
        "GF_MAX_HOR_DIST,3000\n"
    )

    led_instance = MagicMock()
    set_parameters = mocker.patch("actions.set_parameters", new=mocker.AsyncMock())
    mocker.patch("actions.LEDController.get_instance", return_value=led_instance)
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch.object(actions.Params, "COMMON_PARAMS_FILE", str(common_file))

    drone = SimpleNamespace(action=SimpleNamespace(reboot=mocker.AsyncMock()))

    await actions.apply_common_params(drone, reboot_after=False)

    set_parameters.assert_awaited_once_with(
        drone,
        {
            "GF_ACTION": "3",
            "GF_MAX_HOR_DIST": "3000",
        },
    )
    drone.action.reboot.assert_not_awaited()

