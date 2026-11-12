"""Native disarmed-policy evidence without hardware or flight prerequisites."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.drone_api_server import DroneAPIServer
from src.px4_params.service import Px4ParamService


def _server(*, cached_armed=None, require_disarmed=True):
    server = object.__new__(DroneAPIServer)
    server.params = SimpleNamespace(PX4_PARAMETER_MUTATION_REQUIRE_DISARMED=require_disarmed)
    server.drone_config = SimpleNamespace(is_armed=cached_armed)
    server._px4_param_service = Px4ParamService(server.params, hw_id="1")
    return server


def _drone(armed):
    async def samples():
        yield armed
    return SimpleNamespace(telemetry=SimpleNamespace(armed=samples))


@pytest.mark.parametrize("cached", [None, False])
async def test_missing_native_arm_state_is_not_confirmed_disarm(cached):
    with pytest.raises(HTTPException, match="confirmed live disarm"):
        await _server(cached_armed=cached)._assert_live_px4_param_mutation_allowed(SimpleNamespace())


async def test_live_disarm_is_sufficient_without_gps_health_or_landing_state():
    await _server()._assert_live_px4_param_mutation_allowed(_drone(False))


@pytest.mark.parametrize("armed", [True, None, 0, "false"])
async def test_armed_or_untyped_native_state_does_not_admit_writes(armed):
    with pytest.raises(HTTPException):
        await _server(cached_armed=False)._assert_live_px4_param_mutation_allowed(_drone(armed))


async def test_existing_policy_opt_out_does_not_add_a_flight_gate():
    await _server(require_disarmed=False)._assert_live_px4_param_mutation_allowed(SimpleNamespace())
