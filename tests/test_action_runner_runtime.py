import json
import sys
import types
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("psutil", MagicMock())

mavsdk_module = types.ModuleType("mavsdk")
mavsdk_module.System = MagicMock()
mavsdk_system_module = types.ModuleType("mavsdk.system")
mavsdk_system_module.System = MagicMock()
mavsdk_telemetry_module = types.ModuleType("mavsdk.telemetry")
mavsdk_telemetry_module.FlightMode = types.SimpleNamespace(
    HOLD=types.SimpleNamespace(name="HOLD"),
    RETURN_TO_LAUNCH=types.SimpleNamespace(name="RETURN_TO_LAUNCH"),
)
mavsdk_telemetry_module.LandedState = types.SimpleNamespace(LANDING="LANDING", ON_GROUND="ON_GROUND")
mavsdk_module.telemetry = mavsdk_telemetry_module
mavsdk_module.action = MagicMock()
mavsdk_offboard_module = types.ModuleType("mavsdk.offboard")
for name in ("PositionNedYaw", "VelocityNedYaw"):
    setattr(mavsdk_offboard_module, name, MagicMock())
mavsdk_offboard_module.OffboardError = Exception
sys.modules.setdefault("mavsdk", mavsdk_module)
sys.modules.setdefault("mavsdk.system", mavsdk_system_module)
sys.modules.setdefault("mavsdk.telemetry", mavsdk_telemetry_module)
sys.modules.setdefault("mavsdk.offboard", mavsdk_offboard_module)
sys.modules.setdefault("mavsdk.action", types.SimpleNamespace(ActionError=Exception))

import actions
from src.action_runners import ActionExecutionContext, ActionInvocation, ActionSpec, load_request_payload


def test_load_request_payload_from_inline_json():
    payload = load_request_payload(request_json='{"frame":"body","distance":1}')

    assert payload == {"frame": "body", "distance": 1}


def test_load_request_payload_from_file(tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"frame": "ned", "north": 2}), encoding="utf-8")

    payload = load_request_payload(request_file=str(payload_file))

    assert payload == {"frame": "ned", "north": 2}


def test_load_request_payload_rejects_non_object_json():
    with pytest.raises(ValueError, match="JSON object"):
        load_request_payload(request_json='["not", "an", "object"]')


def test_load_request_payload_rejects_dual_sources(tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="mutually exclusive"):
        load_request_payload(request_json="{}", request_file=str(payload_file))


def test_get_action_spec_returns_expected_connection_policy():
    takeoff = actions.get_action_spec("takeoff")
    update_code = actions.get_action_spec("update_code")
    precision_move = actions.get_action_spec("precision_move")

    assert takeoff is not None
    assert takeoff.requires_connection is True
    assert update_code is not None
    assert update_code.requires_connection is False
    assert precision_move is not None
    assert precision_move.requires_connection is True


@pytest.mark.asyncio
async def test_perform_action_skips_mavsdk_for_non_connection_runner(mocker):
    runner = AsyncMock(return_value=True)
    spec = ActionSpec(name="dummy", runner=runner, requires_connection=False)
    mocker.patch("actions.get_action_spec", return_value=spec)
    start_server = mocker.patch("actions.start_mavsdk_server")

    await actions.perform_action("dummy", request_payload={"hello": "world"})

    start_server.assert_not_called()
    runner.assert_awaited_once()
    context, invocation = runner.await_args.args
    assert isinstance(context, ActionExecutionContext)
    assert isinstance(invocation, ActionInvocation)
    assert invocation.request_payload == {"hello": "world"}
