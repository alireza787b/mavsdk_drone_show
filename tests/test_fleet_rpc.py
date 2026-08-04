import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest


def _params(**overrides):
    values = {
        "drone_api_port": 7070,
        "send_drone_command_URI": "api/v1/commands",
        "GCS_FLEET_RPC_CONCURRENCY": 8,
        "GCS_FLEET_RECOVERY_CONCURRENCY": 2,
        "GCS_FLEET_PREPARE_DEADLINE_SEC": 2.0,
        "GCS_FLEET_DISPATCH_DEADLINE_SEC": 2.0,
        "GCS_FLEET_RECOVERY_DEADLINE_SEC": 2.0,
        "GCS_COMMAND_HTTP_TIMEOUT_SEC": 1.0,
        "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC": 0.1,
        "OFFBOARD_ARM_MAX_ATTEMPTS": 1,
        "OFFBOARD_ARM_RETRY_DELAY_SEC": 0.0,
        "OFFBOARD_ARM_ACTION_TIMEOUT_SEC": 0.1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _drones(count):
    return [
        {"hw_id": str(index), "ip": f"10.0.{index // 250}.{index % 250 + 1}"}
        for index in range(1, count + 1)
    ]


def _callback_capabilities(drones):
    return {
        str(drone["hw_id"]): f"cap-{str(drone['hw_id']):0>39}"[:43]
        for drone in drones
    }


def _launch_tokens(drones):
    return {
        str(drone["hw_id"]): f"prepare-{drone['hw_id']}-" + ("x" * 48)
        for drone in drones
    }


def _prepared_launch_payload(
    request,
    target_hw_id=None,
    *,
    token_ttl_ms=90_000,
    server_processing_ms=0,
):
    from src.launch_preparation_protocol import immutable_command_payload_sha256

    request_payload = json.loads(request.content)
    command = request_payload["command"]
    hw_id = command["target_hw_id"] if target_hw_id is None else target_hw_id
    return {
        "schema_version": 1,
        "status": "prepared",
        "command_id": command["command_id"],
        "target_hw_id": hw_id,
        "mission_type": command["mission_type"],
        "immutable_payload_sha256": immutable_command_payload_sha256(command),
        "ready": True,
        "summary": "ready",
        "observation": {
            "schema_version": 1,
            "observation_id": f"probe-{hw_id}",
            "source": "test",
            "observed_at_ms": 1_000,
            "valid_until_ms": 6_000,
            "require_global_position": True,
            "ready": True,
            "blockers": [],
            "checks": {},
            "battery": {},
        },
        "preparation_token": f"prepare-{hw_id}-" + ("x" * 48),
        "token_ttl_ms": token_ttl_ms,
        "server_processing_ms": server_processing_ms,
    }


@pytest.fixture(autouse=True)
def _supply_target_bound_callback_capabilities(monkeypatch):
    """Keep transport tests focused while exercising the v2 dispatch envelope."""
    from fleet_rpc import FleetRPCService

    original_dispatch = FleetRPCService.dispatch

    async def authenticated_dispatch(self, drones, command_data, **kwargs):
        if "callback_capabilities" not in kwargs:
            kwargs["callback_capabilities"] = _callback_capabilities(drones)
        if (
            "launch_preparation_tokens" not in kwargs
            and mission_requires_launch_armability_probe(command_data.get("mission_type"))
        ):
            kwargs["launch_preparation_tokens"] = _launch_tokens(drones)
        return await original_dispatch(self, drones, command_data, **kwargs)

    from src.command_execution_contract import mission_requires_launch_armability_probe

    monkeypatch.setattr(FleetRPCService, "dispatch", authenticated_dispatch)


@pytest.mark.asyncio
async def test_launch_preparation_is_bounded_for_one_thousand_targets():
    from fleet_rpc import FleetRPCService

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def handler(request):
        nonlocal active, peak
        octets = [int(part) for part in request.url.host.split(".")]
        hw_id = str(octets[2] * 250 + octets[3] - 1)
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.001)
        async with lock:
            active -= 1
        return httpx.Response(
            200,
            request=request,
            json=_prepared_launch_payload(
                request,
                target_hw_id=hw_id,
                server_processing_ms=1,
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(
        _params(
            GCS_FLEET_RPC_CONCURRENCY=12,
            # This test proves bounded fan-out and complete classification,
            # not wall-clock performance on a contended CI host. Dedicated
            # deadline tests below cover expiry behavior.
            GCS_FLEET_PREPARE_DEADLINE_SEC=10.0,
        ),
        client=client,
    )
    try:
        drones = _drones(1000)
        result = await service.prepare_launch(
            drones,
            {
                "mission_type": 3,
                "trigger_time": 0,
                "command_id": "prepare-load",
            },
            callback_capabilities=_callback_capabilities(drones),
        )
    finally:
        await client.aclose()

    assert result["all_prepared"] is True
    assert len(result["results"]) == 1000
    assert len(result["preparation_tokens"]) == 1000
    assert peak <= 12


@pytest.mark.asyncio
async def test_prepare_barrier_and_common_commit_scale_to_one_thousand_targets():
    from command_execution_policy import resolve_strict_sync_trigger_time
    from fleet_rpc import FleetRPCService
    from src.enums import Mission

    active = 0
    peak = 0
    seen_targets = set()
    seen_capabilities = set()
    seen_tokens = set()
    seen_triggers = set()
    lock = asyncio.Lock()

    async def handler(request):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.01)
        if request.url.path.endswith("/preflight/launch-preparations"):
            response = httpx.Response(
                200,
                request=request,
                json=_prepared_launch_payload(request, server_processing_ms=10),
            )
        else:
            payload = json.loads(request.content)
            seen_targets.add(payload["target_hw_id"])
            seen_capabilities.add(payload["command_report_capability"])
            seen_tokens.add(request.headers["X-MDS-Launch-Preparation"])
            seen_triggers.add(payload["trigger_time"])
            response = httpx.Response(
                200,
                request=request,
                json={
                    "status": "accepted",
                    "command_id": payload["command_id"],
                    "hw_id": payload["target_hw_id"],
                },
            )
        async with lock:
            active -= 1
        return response

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    params = _params(
        GCS_FLEET_RPC_CONCURRENCY=12,
        GCS_FLEET_PREPARE_DEADLINE_SEC=10.0,
        GCS_FLEET_DISPATCH_DEADLINE_SEC=10.0,
        trigger_sooner_seconds=0,
        COMMAND_SYNC_DISPATCH_GUARD_SEC=1.0,
    )
    service = FleetRPCService(
        params,
        client=client,
    )
    drones = _drones(1000)
    capabilities = _callback_capabilities(drones)
    command = {
        "mission_type": Mission.HOVER_TEST.value,
        "trigger_time": 0,
        "command_id": "strict-load",
    }
    try:
        preparation = await service.prepare_launch(
            drones,
            command,
            callback_capabilities=capabilities,
        )
        assert preparation["all_prepared"] is True
        common_trigger = resolve_strict_sync_trigger_time(
            Mission.HOVER_TEST,
            requested_trigger_time=0,
            params=params,
        )
        result = await service.dispatch(
            drones,
            {**command, "trigger_time": common_trigger},
            callback_capabilities=capabilities,
            launch_preparation_tokens=preparation["preparation_tokens"],
        )
    finally:
        await client.aclose()

    assert result["success"] == 1000
    assert result["total"] == 1000
    assert common_trigger > int(time.time())
    assert seen_triggers == {common_trigger}
    assert len(seen_targets) == 1000
    assert len(seen_capabilities) == 1000
    assert len(seen_tokens) == 1000
    assert not any(capability in json.dumps(result) for capability in seen_capabilities)
    assert not any(token in json.dumps(result) for token in seen_tokens)
    assert peak <= 12


@pytest.mark.asyncio
async def test_one_thousand_slow_targets_stop_cleanly_at_single_gcs_deadline():
    """A single GCS does not claim atomic 1,000-node delivery at 1 s RTT.

    With the default 48 routine slots, a 15 second budget cannot cover the 21
    serial waves needed at that latency. The transport must stop boundedly,
    classify only started POSTs as ambiguous, and prove the remaining targets
    were never dispatched.
    """
    from fleet_rpc import FleetRPCService

    started_targets = set()

    async def handler(request):
        payload = json.loads(request.content)
        started_targets.add(payload["target_hw_id"])
        await asyncio.sleep(1.0)
        return httpx.Response(500, request=request)

    drones = _drones(1000)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(
        _params(GCS_FLEET_RPC_CONCURRENCY=48),
        client=client,
    )
    try:
        result = await service.dispatch(
            drones,
            {
                "mission_type": 8,
                "trigger_time": 0,
                "command_id": "slow-scale-envelope",
            },
            callback_capabilities=_callback_capabilities(drones),
            operation_deadline_sec=0.05,
        )
    finally:
        await client.aclose()

    classifications = {
        target_id: item["delivery_state"]
        for target_id, item in result["results"].items()
    }
    ambiguous = {
        target_id
        for target_id, state in classifications.items()
        if state == "delivery_unknown"
    }
    never_sent = {
        target_id
        for target_id, state in classifications.items()
        if state == "not_dispatched_deadline"
    }
    assert started_targets == ambiguous
    assert 1 <= len(ambiguous) <= 48
    assert len(never_sent) == 1000 - len(ambiguous)
    assert result["execution_time"] < 0.5


@pytest.mark.asyncio
async def test_dispatch_applies_exact_quickscout_payload_for_each_target():
    from fleet_rpc import FleetRPCService

    received = {}

    async def handler(request):
        payload = json.loads(request.content)
        received[payload["target_hw_id"]] = payload
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "accepted",
                "command_id": payload["command_id"],
                "hw_id": payload["target_hw_id"],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    trigger_time = int(time.time()) + 100
    try:
        result = await service.dispatch(
            _drones(2),
            {
                "mission_type": 5,
                "command_id": "quickscout-batch",
                "trigger_time": trigger_time,
            },
            per_target_payloads={
                "1": {"waypoints": [{"sequence": 1, "lat": 1.0}]},
                "2": {"waypoints": [{"sequence": 2, "lat": 2.0}]},
            },
        )
    finally:
        await client.aclose()

    assert result["success"] == 2
    assert received["1"]["waypoints"] == [{"lat": 1.0, "sequence": 1}]
    assert received["2"]["waypoints"] == [{"lat": 2.0, "sequence": 2}]
    assert received["1"]["command_id"] == received["2"]["command_id"] == "quickscout-batch"
    assert received["1"]["trigger_time"] == received["2"]["trigger_time"] == trigger_time


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "per_target_payloads",
    [
        {"1": {"waypoints": [{"sequence": 1}]}},
        {
            "1": {"waypoints": [{"sequence": 1}]},
            "2": {"waypoints": [{"sequence": 2}], "trigger_time": 999},
        },
    ],
)
async def test_dispatch_rejects_invalid_per_target_payload_map_before_post(per_target_payloads):
    from fleet_rpc import FleetRPCService

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, request=request, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        with pytest.raises(ValueError):
            await service.dispatch(
                _drones(2),
                {"mission_type": 5, "command_id": "quickscout-invalid"},
                per_target_payloads=per_target_payloads,
            )
    finally:
        await client.aclose()

    assert calls == 0


@pytest.mark.asyncio
async def test_dispatch_fails_closed_before_post_when_target_capability_is_missing():
    from fleet_rpc import FleetRPCService

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, request=request, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-no-capability"},
            callback_capabilities={},
        )
    finally:
        await client.aclose()

    assert calls == 0
    assert result["success"] == 0
    assert result["results"]["1"]["delivery_state"] == "not_dispatched_invalid_request"
    assert "capability" in result["results"]["1"]["error"]


@pytest.mark.asyncio
async def test_prepare_rejects_token_from_wrong_node_identity():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        return httpx.Response(
            200,
            request=request,
            json=_prepared_launch_payload(request, target_hw_id="99"),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        drones = [{"hw_id": "1", "ip": "10.0.0.1"}]
        result = await service.prepare_launch(
            drones,
            {"mission_type": 10, "trigger_time": 0, "command_id": "wrong-node"},
            callback_capabilities=_callback_capabilities(drones),
        )
    finally:
        await client.aclose()

    assert result["all_prepared"] is False
    assert result["preparation_tokens"] == {}
    assert result["unavailable_ids"] == ["1"]
    assert result["results"]["1"]["error_code"] == "E108"


@pytest.mark.asyncio
async def test_prepare_rejects_coerced_numeric_node_identity():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        return httpx.Response(
            200,
            request=request,
            json=_prepared_launch_payload(request, target_hw_id=1),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        drones = [{"hw_id": "1", "ip": "10.0.0.1"}]
        result = await service.prepare_launch(
            drones,
            {"mission_type": 10, "trigger_time": 0, "command_id": "numeric-node"},
            callback_capabilities=_callback_capabilities(drones),
        )
    finally:
        await client.aclose()

    assert result["all_prepared"] is False
    assert result["unavailable_ids"] == ["1"]
    assert result["results"]["1"]["error_code"] == "E107"


@pytest.mark.asyncio
async def test_prepare_does_not_restart_node_token_lease_after_network_delay():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        await asyncio.sleep(0.02)
        return httpx.Response(
            200,
            request=request,
            json=_prepared_launch_payload(request, token_ttl_ms=5),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        drones = [{"hw_id": "1", "ip": "10.0.0.1"}]
        result = await service.prepare_launch(
            drones,
            {"mission_type": 10, "trigger_time": 0, "command_id": "expired-token"},
            callback_capabilities=_callback_capabilities(drones),
        )
    finally:
        await client.aclose()

    assert result["all_prepared"] is False
    assert result["unavailable_ids"] == ["1"]
    assert "expired in transit" in result["results"]["1"]["summary"]


@pytest.mark.asyncio
async def test_prepare_does_not_charge_node_processing_against_token_lease():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        await asyncio.sleep(0.02)
        return httpx.Response(
            200,
            request=request,
            json=_prepared_launch_payload(
                request,
                token_ttl_ms=90_000,
                server_processing_ms=20,
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        drones = [{"hw_id": "1", "ip": "10.0.0.1"}]
        result = await service.prepare_launch(
            drones,
            {"mission_type": 10, "trigger_time": 0, "command_id": "processing-time"},
            callback_capabilities=_callback_capabilities(drones),
        )
    finally:
        await client.aclose()

    assert result["all_prepared"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"status": "prepared", "ready": "false", "summary": "malformed"},
        {
            "status": "rejected",
            "ready": True,
            "summary": "probe failed",
            "observation": {"observed_at_ms": 1_000, "valid_until_ms": 6_000},
        },
    ],
)
async def test_prepare_fails_closed_on_malformed_payload(payload):
    from fleet_rpc import FleetRPCService

    async def handler(request):
        return httpx.Response(200, request=request, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        drones = [{"hw_id": "1", "ip": "10.0.0.1"}]
        result = await service.prepare_launch(
            drones,
            {"mission_type": 10, "trigger_time": 0, "command_id": "malformed-prepare"},
            callback_capabilities=_callback_capabilities(drones),
        )
    finally:
        await client.aclose()

    assert result["all_prepared"] is False
    assert result["unavailable_ids"] == ["1"]


@pytest.mark.asyncio
async def test_prepare_rejects_tokens_that_cannot_cover_commit_after_fanout():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        await asyncio.sleep(0.01)
        octets = [int(part) for part in request.url.host.split(".")]
        hw_id = str(octets[2] * 250 + octets[3] - 1)
        return httpx.Response(
            200,
            request=request,
            json=_prepared_launch_payload(
                request,
                target_hw_id=hw_id,
                token_ttl_ms=5,
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(GCS_FLEET_RPC_CONCURRENCY=1), client=client)
    try:
        drones = _drones(3)
        result = await service.prepare_launch(
            drones,
            {"mission_type": 10, "trigger_time": 0, "command_id": "barrier-expiry"},
            callback_capabilities=_callback_capabilities(drones),
        )
    finally:
        await client.aclose()

    assert result["all_prepared"] is False
    assert result["unavailable_ids"]
    assert any(
        "expired" in item["summary"]
        for item in result["results"].values()
    )


@pytest.mark.asyncio
async def test_dispatch_attempts_every_committed_target_and_preserves_node_error_detail():
    from fleet_rpc import FleetRPCService

    requested_payloads = {}

    async def handler(request):
        requested_payloads[request.url.host] = json.loads(request.content)
        if request.url.host == "10.0.0.2":
            return httpx.Response(
                200,
                request=request,
                json={
                    "status": "rejected",
                    "command_id": "cmd-1",
                    "hw_id": "2",
                    "message": "Not ready",
                    "error_code": "E202",
                    "error_detail": "Current PX4 observation is blocked by home position",
                },
            )
        return httpx.Response(
            200,
            request=request,
            json={"status": "accepted", "command_id": "cmd-1", "hw_id": "1"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [
                {"hw_id": "1", "ip": "10.0.0.1"},
                {"hw_id": "2", "ip": "10.0.0.2"},
            ],
            {"mission_type": 10, "command_id": "cmd-1"},
        )
    finally:
        await client.aclose()

    assert set(requested_payloads) == {"10.0.0.1", "10.0.0.2"}
    assert requested_payloads["10.0.0.1"]["target_hw_id"] == "1"
    assert requested_payloads["10.0.0.2"]["target_hw_id"] == "2"
    assert result["success"] == 1
    assert result["rejected"] == 1
    assert result["results"]["2"]["error_code"] == "E202"
    assert "home position" in result["results"]["2"]["error_detail"]


@pytest.mark.asyncio
async def test_dispatch_rejects_ack_from_wrong_node_identity():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "accepted",
                "command_id": "cmd-target-bound",
                "hw_id": "99",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-target-bound", "target_hw_id": "spoofed"},
        )
    finally:
        await client.aclose()

    assert result["success"] == 0
    assert result["rejected"] == 0
    assert result["errors"] == 1
    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"
    assert result["results"]["1"]["error_code"] == "E108"
    assert "wrong-target" in result["results"]["1"]["error_detail"]


@pytest.mark.asyncio
async def test_dispatch_treats_explicit_target_identity_rejection_as_definite():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "rejected",
                "command_id": payload["command_id"],
                "hw_id": "99",
                "error_code": "E108",
                "message": "Command reached a different drone",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-mismatch-rejected"},
        )
    finally:
        await client.aclose()

    assert result["rejected"] == 1
    assert result["errors"] == 0
    assert result["results"]["1"]["delivery_state"] == "rejected"
    assert result["results"]["1"]["error_code"] == "E108"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_payload",
    [
        {"hw_id": "1", "command_id": "cmd-strict"},
        {"status": "", "hw_id": "1", "command_id": "cmd-strict"},
        {"status": "success", "hw_id": "1", "command_id": "cmd-strict"},
        {"status": "accepted", "hw_id": "1"},
        {"status": "accepted", "hw_id": "1", "command_id": "another-command"},
        {"status": "accepted", "hw_id": 1, "command_id": "cmd-strict"},
    ],
)
async def test_dispatch_never_accepts_malformed_or_uncorrelated_ack(response_payload):
    from fleet_rpc import FleetRPCService

    async def handler(request):
        return httpx.Response(200, request=request, json=response_payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-strict"},
        )
    finally:
        await client.aclose()

    assert result["success"] == 0
    assert result["errors"] == 1
    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [201, 408, 425, 429, 500, 503])
async def test_dispatch_ambiguous_http_response_is_delivery_unknown(status_code):
    from fleet_rpc import FleetRPCService

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, request=request, json={"message": "response lost downstream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-http-unknown"},
        )
    finally:
        await client.aclose()

    assert calls == 1
    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"
    assert result["results"]["1"]["category"] == "error"


@pytest.mark.asyncio
async def test_dispatch_preserves_typed_node_error_from_fastapi_detail_envelope():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        return httpx.Response(
            503,
            request=request,
            json={
                "detail": {
                    "status": "delivery_unknown",
                    "error_code": "E500",
                    "message": "Node mutation outcome is unknown",
                    "error_detail": "Artifact commit failed after preparation",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-node-detail"},
        )
    finally:
        await client.aclose()

    target = result["results"]["1"]
    assert target["delivery_state"] == "delivery_unknown"
    assert target["error_code"] == "E500"
    assert "Node mutation outcome is unknown" in target["error"]
    assert target["error_detail"] == "Artifact commit failed after preparation"


@pytest.mark.asyncio
async def test_dispatch_definite_http_client_rejection_is_not_delivery_unknown():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        return httpx.Response(422, request=request, json={"message": "invalid request"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-http-rejected"},
        )
    finally:
        await client.aclose()

    assert result["rejected"] == 1
    assert result["results"]["1"]["delivery_state"] == "request_rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("extra_error_type", ["value_error.extra", "extra_forbidden"])
async def test_update_code_can_bridge_exact_legacy_envelope_rejection(extra_error_type):
    from fleet_rpc import FleetRPCService
    from src.enums import Mission

    requests = []
    request_sequence = []
    capability = "field-recovery-secret-" + ("x" * 43)

    async def handler(request):
        request_sequence.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, request=request, json={"hw_id": 1})
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                422,
                request=request,
                json={
                    "detail": [
                        {
                            "type": extra_error_type,
                            "loc": ["body", "command_report_capability"],
                            "msg": "extra field",
                            "input": capability,
                        },
                        {
                            "type": extra_error_type,
                            "loc": ["body", "target_hw_id"],
                            "msg": "extra field",
                            "input": "1",
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "accepted",
                "command_id": payload["command_id"],
                "hw_id": "1",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": Mission.UPDATE_CODE.value, "command_id": "update-legacy"},
            callback_capabilities={"1": capability},
            allow_legacy_update_envelope=True,
        )
    finally:
        await client.aclose()

    assert len(requests) == 2
    assert request_sequence == [
        ("POST", "/api/v1/commands"),
        ("GET", "/api/v1/swarm/state"),
        ("POST", "/api/v1/commands"),
    ]
    current_payload, legacy_payload = requests
    assert current_payload["command_id"] == legacy_payload["command_id"] == "update-legacy"
    assert set(current_payload) - set(legacy_payload) == {
        "target_hw_id",
        "command_report_capability",
    }
    assert all(
        legacy_payload[key] == value
        for key, value in current_payload.items()
        if key not in {"target_hw_id", "command_report_capability"}
    )
    assert result["success"] == 1
    assert result["results"]["1"]["delivery_state"] == "accepted_legacy_update_envelope"
    assert capability not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mission_type", "allow_bridge", "status_code", "detail"),
    [
        (
            103,
            False,
            422,
            [
                {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                {
                    "type": "extra_forbidden",
                    "loc": ["body", "command_report_capability"],
                },
            ],
        ),
        (
            102,
            True,
            422,
            [
                {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                {
                    "type": "extra_forbidden",
                    "loc": ["body", "command_report_capability"],
                },
            ],
        ),
        (
            103,
            True,
            400,
            [
                {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                {
                    "type": "extra_forbidden",
                    "loc": ["body", "command_report_capability"],
                },
            ],
        ),
        (
            103,
            True,
            422,
            [{"type": "extra_forbidden", "loc": ["body", "target_hw_id"]}],
        ),
        (
            103,
            True,
            422,
            [
                {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                {
                    "type": "value_error.missing",
                    "loc": ["body", "command_report_capability"],
                },
            ],
        ),
        (
            103,
            True,
            422,
            [
                {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                {"type": "extra_forbidden", "loc": ["body", "unexpected"]},
            ],
        ),
    ],
)
async def test_legacy_envelope_bridge_rejects_every_nonexact_case(
    mission_type,
    allow_bridge,
    status_code,
    detail,
):
    from fleet_rpc import FleetRPCService

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, request=request, json={"detail": detail})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": mission_type, "command_id": "no-legacy-bridge"},
            allow_legacy_update_envelope=allow_bridge,
        )
    finally:
        await client.aclose()

    assert calls == 1
    assert result["rejected"] == 1
    assert result["results"]["1"]["delivery_state"] == "request_rejected"


@pytest.mark.asyncio
async def test_legacy_update_envelope_bridge_retries_only_once():
    from fleet_rpc import FleetRPCService
    from src.enums import Mission

    methods = []

    async def handler(request):
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, request=request, json={"hw_id": 1})
        return httpx.Response(
            422,
            request=request,
            json={
                "detail": [
                    {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                    {
                        "type": "extra_forbidden",
                        "loc": ["body", "command_report_capability"],
                    },
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": Mission.UPDATE_CODE.value, "command_id": "one-retry"},
            allow_legacy_update_envelope=True,
        )
    finally:
        await client.aclose()

    assert methods == ["POST", "GET", "POST"]
    assert result["rejected"] == 1
    assert result["results"]["1"]["delivery_state"] == "request_rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity_status", "identity_payload"),
    [
        (404, {"detail": "not found"}),
        (200, {}),
        (200, {"hw_id": "1"}),
        (200, {"hw_id": True}),
        (200, {"hw_id": 2}),
    ],
)
async def test_legacy_update_bridge_requires_exact_typed_identity(
    identity_status,
    identity_payload,
):
    from fleet_rpc import FleetRPCService
    from src.enums import Mission

    methods = []

    async def handler(request):
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(
                identity_status,
                request=request,
                json=identity_payload,
            )
        return httpx.Response(
            422,
            request=request,
            json={
                "detail": [
                    {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                    {
                        "type": "extra_forbidden",
                        "loc": ["body", "command_report_capability"],
                    },
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": Mission.UPDATE_CODE.value, "command_id": "identity-bound"},
            allow_legacy_update_envelope=True,
        )
    finally:
        await client.aclose()

    assert methods == ["POST", "GET"]
    assert result["rejected"] == 1
    assert result["results"]["1"]["delivery_state"] == "request_rejected"


@pytest.mark.asyncio
async def test_legacy_update_bridge_does_not_retry_when_identity_probe_is_unreachable():
    from fleet_rpc import FleetRPCService
    from src.enums import Mission

    methods = []

    async def handler(request):
        methods.append(request.method)
        if request.method == "GET":
            raise httpx.ConnectError("identity route unreachable", request=request)
        return httpx.Response(
            422,
            request=request,
            json={
                "detail": [
                    {"type": "value_error.extra", "loc": ["body", "target_hw_id"]},
                    {
                        "type": "value_error.extra",
                        "loc": ["body", "command_report_capability"],
                    },
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": Mission.UPDATE_CODE.value, "command_id": "identity-offline"},
            allow_legacy_update_envelope=True,
        )
    finally:
        await client.aclose()

    assert methods == ["POST", "GET"]
    assert result["rejected"] == 1
    assert result["results"]["1"]["delivery_state"] == "request_rejected"


@pytest.mark.asyncio
async def test_legacy_update_identity_probe_remains_inside_fleet_deadline():
    from fleet_rpc import FleetRPCService
    from src.enums import Mission

    methods = []

    async def handler(request):
        methods.append(request.method)
        if request.method == "GET":
            await asyncio.sleep(0.2)
            return httpx.Response(200, request=request, json={"hw_id": 1})
        return httpx.Response(
            422,
            request=request,
            json={
                "detail": [
                    {"type": "extra_forbidden", "loc": ["body", "target_hw_id"]},
                    {
                        "type": "extra_forbidden",
                        "loc": ["body", "command_report_capability"],
                    },
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    started = time.monotonic()
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": Mission.UPDATE_CODE.value, "command_id": "identity-deadline"},
            allow_legacy_update_envelope=True,
            operation_deadline_sec=0.01,
        )
    finally:
        await client.aclose()

    assert time.monotonic() - started < 0.1
    assert methods == ["POST", "GET"]
    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"


@pytest.mark.asyncio
async def test_post_read_timeout_is_delivery_unknown_and_is_not_retried():
    from fleet_rpc import FleetRPCService

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("response lost", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "same-id-for-safe-recovery"},
        )
    finally:
        await client.aclose()

    assert calls == 1
    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"
    assert result["results"]["1"]["category"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type",
    [httpx.WriteTimeout, httpx.ReadError, httpx.RemoteProtocolError],
)
async def test_post_response_or_write_failure_is_delivery_unknown(exception_type):
    from fleet_rpc import FleetRPCService

    async def handler(request):
        raise exception_type("transport boundary failed", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-transport-unknown"},
        )
    finally:
        await client.aclose()

    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception_type", "expected_state", "expected_category"),
    [
        (httpx.ConnectError, "dispatch_unreachable", "offline"),
        (httpx.ConnectTimeout, "dispatch_unreachable", "offline"),
        (httpx.PoolTimeout, "not_dispatched_transport_capacity", "error"),
    ],
)
async def test_pre_delivery_transport_failure_is_not_marked_ambiguous(
    exception_type,
    expected_state,
    expected_category,
):
    from fleet_rpc import FleetRPCService

    async def handler(request):
        raise exception_type("could not begin request", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(), client=client)
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "cmd-not-delivered"},
        )
    finally:
        await client.aclose()

    assert result["results"]["1"]["delivery_state"] == expected_state
    assert result["results"]["1"]["category"] == expected_category


@pytest.mark.asyncio
async def test_started_post_deadline_is_unknown_while_queued_target_is_not_dispatched():
    from fleet_rpc import FleetRPCService

    async def handler(request):
        await asyncio.sleep(0.2)
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "accepted",
                "command_id": payload["command_id"],
                "hw_id": payload["target_hw_id"],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(GCS_FLEET_RPC_CONCURRENCY=1), client=client)
    try:
        result = await service.dispatch(
            [
                {"hw_id": "1", "ip": "10.0.0.1"},
                {"hw_id": "2", "ip": "10.0.0.2"},
            ],
            {"mission_type": 10, "command_id": "deadline-bound"},
            operation_deadline_sec=0.01,
        )
    finally:
        await client.aclose()

    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"
    assert result["results"]["2"]["delivery_state"] == "not_dispatched_deadline"


@pytest.mark.asyncio
async def test_shared_slot_wait_obeys_call_deadline_without_late_dispatch():
    from fleet_rpc import FleetRPCService

    first_started = asyncio.Event()
    release_first = asyncio.Event()
    received_command_ids = []

    async def handler(request):
        payload = json.loads(request.content)
        received_command_ids.append(payload["command_id"])
        if payload["command_id"] == "occupies-shared-slot":
            first_started.set()
            await release_first.wait()
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "accepted",
                "command_id": payload["command_id"],
                "hw_id": payload["target_hw_id"],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(_params(GCS_FLEET_RPC_CONCURRENCY=1), client=client)
    first_task = asyncio.create_task(
        service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "occupies-shared-slot"},
            operation_deadline_sec=1.0,
        )
    )
    await asyncio.wait_for(first_started.wait(), timeout=0.5)

    try:
        second = await asyncio.wait_for(
            service.dispatch(
                [{"hw_id": "2", "ip": "10.0.0.2"}],
                {"mission_type": 10, "command_id": "must-not-dispatch-late"},
                operation_deadline_sec=0.02,
            ),
            timeout=0.2,
        )
        assert second["results"]["2"]["delivery_state"] == "not_dispatched_deadline"
        assert received_command_ids == ["occupies-shared-slot"]
    finally:
        release_first.set()
        await first_task
        await client.aclose()


@pytest.mark.asyncio
async def test_strict_sync_fanout_never_posts_targets_after_safe_window(monkeypatch):
    import fleet_rpc
    from fleet_rpc import FleetRPCService

    posted_targets = []
    wall_clock = {"now": 1_000.9}
    monkeypatch.setattr(
        fleet_rpc,
        "time",
        SimpleNamespace(
            monotonic=time.monotonic,
            time=lambda: wall_clock["now"],
        ),
    )

    async def handler(request):
        payload = json.loads(request.content)
        posted_targets.append(payload["target_hw_id"])
        # Keep the first in-flight request unresolved until the strict-sync
        # window passes. The second target must remain undispatched.
        wall_clock["now"] = 1_002.0
        await asyncio.sleep(0.2)
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "accepted",
                "command_id": payload["command_id"],
                "hw_id": payload["target_hw_id"],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(
        _params(
            GCS_FLEET_RPC_CONCURRENCY=1,
            trigger_sooner_seconds=0,
            COMMAND_SYNC_DISPATCH_GUARD_SEC=0,
        ),
        client=client,
    )
    try:
        result = await service.dispatch(
            [
                {"hw_id": "1", "ip": "10.0.0.1"},
                {"hw_id": "2", "ip": "10.0.0.2"},
            ],
            {
                "mission_type": 1,
                "command_id": "strict-sync-window",
                "trigger_time": 1_001,
            },
            operation_deadline_sec=1.0,
        )
    finally:
        await client.aclose()

    assert posted_targets == ["1"]
    assert result["results"]["1"]["delivery_state"] == "delivery_unknown"
    assert result["results"]["2"]["delivery_state"] == "not_dispatched_sync_window"


@pytest.mark.asyncio
async def test_expired_strict_sync_command_is_not_posted(monkeypatch):
    from fleet_rpc import FleetRPCService

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(
        _params(trigger_sooner_seconds=0, COMMAND_SYNC_DISPATCH_GUARD_SEC=0),
        client=client,
    )
    try:
        result = await service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {
                "mission_type": 1,
                "command_id": "already-expired-show",
                "trigger_time": time.time() - 1,
            },
        )
    finally:
        await client.aclose()

    assert calls == 0
    assert result["results"]["1"]["delivery_state"] == "not_dispatched_sync_window"


@pytest.mark.asyncio
async def test_recovery_capacity_is_reserved_from_slow_routine_dispatch():
    from fleet_rpc import FleetRPCService

    release_routine = asyncio.Event()
    routine_started = asyncio.Event()

    async def handler(request):
        payload = json.loads(request.content)
        if payload["mission_type"] == 10:
            routine_started.set()
            await release_routine.wait()
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "accepted",
                "command_id": payload["command_id"],
                "hw_id": "1",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = FleetRPCService(
        _params(GCS_FLEET_RPC_CONCURRENCY=1, GCS_FLEET_RECOVERY_CONCURRENCY=1),
        client=client,
    )
    routine_task = asyncio.create_task(
        service.dispatch(
            [{"hw_id": "1", "ip": "10.0.0.1"}],
            {"mission_type": 10, "command_id": "launch"},
        )
    )
    await asyncio.wait_for(routine_started.wait(), timeout=0.5)

    try:
        recovery = await asyncio.wait_for(
            service.dispatch(
                [{"hw_id": "1", "ip": "10.0.0.1"}],
                {"mission_type": 101, "command_id": "land"},
            ),
            timeout=0.5,
        )
        assert recovery["success"] == 1
    finally:
        release_routine.set()
        await routine_task
        await client.aclose()
