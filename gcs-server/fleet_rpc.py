"""Bounded asynchronous GCS-to-node RPC transport.

The command API must never perform blocking fleet fan-out on the ASGI event
loop.  This module owns the HTTP client, concurrency limits, deadlines, and
typed per-node outcomes used by launch preparation and command dispatch.

Presence is deliberately absent from this transport.  A cached heartbeat can
explain an outcome to an operator, but only the current RPC attempt can say
whether the command path was reachable for this operation.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import httpx
from pydantic import ValidationError

from command_execution_policy import (
    get_sync_dispatch_deadline,
    mission_is_recovery,
    resolve_mission_type,
)
from src.enums import CommandErrorCode, CommandResultCategory, Mission
from src.live_armability_utils import calculate_live_armability_request_timeout
from src.drone_api_routes import (
    DRONE_LAUNCH_PREPARATION_ROUTE,
    DRONE_SWARM_STATE_ROUTE,
)
from target_command_payloads import validate_per_target_payloads
from src.command_execution_contract import mission_requires_launch_armability_probe
from src.launch_preparation_protocol import (
    LAUNCH_PREPARATION_TOKEN_HEADER,
    LaunchPreparationRequest,
    LaunchPreparationResponse,
    canonical_node_command,
    immutable_command_payload_sha256,
)


def _normalize_drone_id(drone: dict[str, Any]) -> str:
    return str(drone.get("hw_id", "")).strip()


def _compact(value: Any, limit: int = 300) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


_LEGACY_UPDATE_ENVELOPE_FIELDS = frozenset(
    {"target_hw_id", "command_report_capability"}
)
_PYDANTIC_EXTRA_FIELD_ERROR_TYPES = frozenset(
    {"extra_forbidden", "value_error.extra"}
)


def _is_legacy_update_envelope_rejection(
    *,
    status_code: int,
    payload: dict[str, Any],
) -> bool:
    """Recognize only the old-node rejection of the two new envelope fields.

    FastAPI/Pydantic v1 and v2 use different error type names, but both report
    request-body locations.  Requiring exactly the two known errors prevents a
    retry from hiding any other validation failure.
    """

    if status_code != 422:
        return False
    detail = payload.get("detail")
    if not isinstance(detail, list) or len(detail) != 2:
        return False

    rejected_fields: set[str] = set()
    for error in detail:
        if not isinstance(error, dict):
            return False
        if error.get("type") not in _PYDANTIC_EXTRA_FIELD_ERROR_TYPES:
            return False
        location = error.get("loc")
        if (
            not isinstance(location, (list, tuple))
            or len(location) != 2
            or location[0] != "body"
            or location[1] not in _LEGACY_UPDATE_ENVELOPE_FIELDS
        ):
            return False
        rejected_fields.add(location[1])

    return rejected_fields == _LEGACY_UPDATE_ENVELOPE_FIELDS


def _is_exact_nonblank_string(value: Any) -> bool:
    """Return whether *value* is already a canonical, non-blank string.

    Transport acknowledgements are correlation records, not user input.  Do
    not coerce integers or trim whitespace here: accepting either would make a
    malformed response appear to match a command or hardware identity.
    """

    return type(value) is str and bool(value) and value == value.strip()


def _build_target_command_payload(
    command_data: dict[str, Any],
    *,
    drone_id: str,
    callback_capability: str | None,
    per_target_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the one canonical payload shared by prepare and commit."""

    if not _is_exact_nonblank_string(callback_capability) or len(callback_capability) < 43:
        raise ValueError("target-bound callback capability is unavailable")
    command_payload = dict(command_data)
    if per_target_payload is not None:
        command_payload.update(per_target_payload)
    command_payload["target_hw_id"] = drone_id
    command_payload["command_report_capability"] = callback_capability
    if not _is_exact_nonblank_string(command_payload.get("command_id")):
        raise ValueError("command_id is not a canonical non-blank string")
    return canonical_node_command(command_payload)


def _node_error_fields(payload: dict[str, Any], *, fallback_code: str) -> tuple[str, str | None, str | None]:
    # FastAPI wraps structured ``HTTPException.detail`` mappings under the
    # top-level ``detail`` key. Preserve the node's typed root cause while
    # leaving generic string/list framework errors bounded and untrusted.
    nested_detail = payload.get("detail")
    error_payload = nested_detail if isinstance(nested_detail, dict) else payload
    code = _compact(error_payload.get("error_code"), 32) or fallback_code
    message = _compact(error_payload.get("message"), 220)
    detail = _compact(error_payload.get("error_detail"), 500)
    if message is None:
        message = detail or "Drone rejected the request"
    return code, message, detail


class FleetRPCService:
    """Lifespan-owned, bounded HTTP transport for fleet operations."""

    def __init__(self, params: Any, *, client: httpx.AsyncClient | None = None) -> None:
        self.params = params
        self._client = client
        self._owns_client = client is None
        self._start_lock = asyncio.Lock()
        routine_limit = max(1, int(getattr(params, "GCS_FLEET_RPC_CONCURRENCY", 48)))
        recovery_limit = max(1, int(getattr(params, "GCS_FLEET_RECOVERY_CONCURRENCY", 16)))
        self._routine_limit = routine_limit
        self._recovery_limit = recovery_limit
        # Recovery traffic has reserved capacity and cannot sit behind routine
        # polling or launch preparation.
        self._routine_slots = asyncio.Semaphore(routine_limit)
        self._recovery_slots = asyncio.Semaphore(recovery_limit)

    async def start(self) -> None:
        if self._client is not None:
            return
        async with self._start_lock:
            if self._client is not None:
                return
            connection_limit = self._routine_limit + self._recovery_limit
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=connection_limit,
                    max_keepalive_connections=connection_limit,
                ),
                trust_env=False,
            )

    async def close(self) -> None:
        client = self._client
        self._client = None
        if self._owns_client and client is not None:
            await client.aclose()

    async def _client_or_start(self) -> httpx.AsyncClient:
        await self.start()
        if self._client is None:  # pragma: no cover - defensive lifecycle guard
            raise RuntimeError("Fleet RPC client failed to initialize")
        return self._client

    async def _bounded_map(
        self,
        drones: Iterable[dict[str, Any]],
        operation: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        *,
        recovery: bool,
        deadline_sec: float,
        deadline_result: Callable[[dict[str, Any]], dict[str, Any]],
        started_deadline_result: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run a fleet operation with bounded workers and an operation deadline."""

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        drone_list = list(drones)
        for drone in drone_list:
            queue.put_nowait(drone)

        results: dict[str, dict[str, Any]] = {}
        slots = self._recovery_slots if recovery else self._routine_slots
        worker_limit = self._recovery_limit if recovery else self._routine_limit
        deadline = time.monotonic() + max(0.0, float(deadline_sec))

        async def worker() -> None:
            while True:
                try:
                    drone = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                drone_id = _normalize_drone_id(drone)
                slot_acquired = False
                operation_started = False
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        results[drone_id] = deadline_result(drone)
                        continue

                    # The semaphore is shared by concurrent fleet operations.
                    # Waiting for it is part of this operation's absolute
                    # deadline; a target whose deadline expires in the queue
                    # must never be sent later merely because capacity frees.
                    await asyncio.wait_for(slots.acquire(), timeout=remaining)
                    slot_acquired = True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        results[drone_id] = deadline_result(drone)
                        continue

                    operation_started = True
                    results[drone_id] = await asyncio.wait_for(
                        operation(drone),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    # Once an operation coroutine has started, a POST may
                    # already have crossed the transport boundary. Callers can
                    # therefore distinguish it from work that never left the
                    # queue when the fleet deadline expires.
                    result_factory = (
                        started_deadline_result
                        if operation_started and started_deadline_result is not None
                        else deadline_result
                    )
                    results[drone_id] = result_factory(drone)
                except Exception as exc:  # pragma: no cover - final isolation boundary
                    results[drone_id] = {
                        "success": False,
                        "category": CommandResultCategory.ERROR.value,
                        "delivery_state": "transport_error",
                        "error": f"Fleet RPC worker failed: {_compact(exc, 180)}",
                        "error_code": CommandErrorCode.INTERNAL_ERROR.value,
                        "error_detail": _compact(exc, 500),
                        "drone_ip": drone.get("ip"),
                    }
                finally:
                    if slot_acquired:
                        slots.release()
                    queue.task_done()

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(len(drone_list), worker_limit))
        ]
        if workers:
            await asyncio.gather(*workers)
        return results

    async def prepare_launch(
        self,
        drones: list[dict[str, Any]],
        command_data: dict[str, Any],
        *,
        callback_capabilities: dict[str, str],
        per_target_payloads: dict[str, dict[str, Any]] | None = None,
        require_global_position: bool = True,
        request_timeout_sec: float | None = None,
        operation_deadline_sec: float | None = None,
    ) -> dict[str, Any]:
        """Acquire a command-bound one-use token from every launch target."""

        if not drones:
            return {
                "all_prepared": True,
                "blocked_ids": [],
                "unavailable_ids": [],
                "preparation_tokens": {},
                "results": {},
            }

        mission = resolve_mission_type(command_data.get("mission_type"))
        if not mission_requires_launch_armability_probe(mission):
            raise ValueError("prepare_launch requires a launch-armability mission")
        target_ids = [_normalize_drone_id(drone) for drone in drones]
        per_target_payloads = validate_per_target_payloads(
            mission,
            target_ids,
            per_target_payloads,
        )
        client = await self._client_or_start()
        request_timeout = float(
            request_timeout_sec
            or calculate_live_armability_request_timeout(params=self.params)
        )
        operation_deadline = float(
            operation_deadline_sec
            or getattr(self.params, "GCS_FLEET_PREPARE_DEADLINE_SEC", 30.0)
        )

        async def prepare(drone: dict[str, Any]) -> dict[str, Any]:
            drone_id = _normalize_drone_id(drone)
            try:
                target_command = _build_target_command_payload(
                    command_data,
                    drone_id=drone_id,
                    callback_capability=callback_capabilities.get(drone_id),
                    per_target_payload=(
                        per_target_payloads[drone_id]
                        if per_target_payloads is not None
                        else None
                    ),
                )
                request_model = LaunchPreparationRequest(
                    command=target_command,
                    require_global_position=require_global_position,
                )
            except (TypeError, ValueError, ValidationError) as exc:
                return {
                    "drone_id": drone_id,
                    "success": False,
                    "ready": False,
                    "summary": "Launch preparation request violated the shared command contract",
                    "details": None,
                    "category": CommandResultCategory.ERROR.value,
                    "prepare_state": "unavailable",
                    "error_code": CommandErrorCode.INVALID_FORMAT.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }

            url = (
                f"http://{drone.get('ip')}:{self.params.drone_api_port}"
                f"{DRONE_LAUNCH_PREPARATION_ROUTE}"
            )
            request_started = time.monotonic()
            try:
                response = await client.post(
                    url,
                    json=request_model.model_dump(mode="json"),
                    timeout=request_timeout,
                )
                payload = _response_payload(response)
                if response.status_code != 200:
                    code, message, detail = _node_error_fields(
                        payload,
                        fallback_code=CommandErrorCode.HTTP_ERROR.value,
                    )
                    return {
                        "drone_id": drone_id,
                        "success": False,
                        "ready": False,
                        "summary": f"Launch preparation rejected over HTTP {response.status_code}: {message}",
                        "details": None,
                        "category": CommandResultCategory.REJECTED.value,
                        "prepare_state": "unavailable",
                        "error_code": code,
                        "error_detail": detail,
                        "drone_ip": drone.get("ip"),
                    }
                try:
                    envelope = LaunchPreparationResponse.model_validate(payload)
                except ValidationError as exc:
                    return {
                        "drone_id": drone_id,
                        "success": False,
                        "ready": False,
                        "summary": "Launch preparation response violated the shared response contract",
                        "details": None,
                        "category": CommandResultCategory.ERROR.value,
                        "prepare_state": "unavailable",
                        "error_code": CommandErrorCode.INVALID_FORMAT.value,
                        "error_detail": _compact(exc, 500),
                        "drone_ip": drone.get("ip"),
                    }

                expected_digest = immutable_command_payload_sha256(target_command)
                identity_matches = (
                    envelope.command_id == target_command["command_id"]
                    and envelope.target_hw_id == drone_id
                    and envelope.mission_type == target_command["mission_type"]
                    and envelope.immutable_payload_sha256 == expected_digest
                )
                if not identity_matches:
                    return {
                        "drone_id": drone_id,
                        "success": False,
                        "ready": False,
                        "summary": "Launch preparation response did not match the exact target command",
                        "details": None,
                        "category": CommandResultCategory.REJECTED.value,
                        "prepare_state": "unavailable",
                        "error_code": CommandErrorCode.TARGET_IDENTITY_MISMATCH.value,
                        "error_detail": "Command ID, hardware ID, mission, or immutable payload fingerprint differed",
                        "drone_ip": drone.get("ip"),
                    }
                if envelope.status != "prepared":
                    return {
                        "drone_id": drone_id,
                        "success": False,
                        "ready": False,
                        "summary": envelope.summary,
                        "details": {
                            "observation": (
                                envelope.observation.model_dump(mode="json")
                                if envelope.observation is not None
                                else None
                            )
                        },
                        "category": "blocked",
                        "prepare_state": "blocked",
                        "error_code": envelope.error_code or CommandErrorCode.PREFLIGHT_FAILED.value,
                        "error_detail": envelope.error_detail,
                        "drone_ip": drone.get("ip"),
                    }

                round_trip_ms = max(0, int((time.monotonic() - request_started) * 1_000))
                transport_ms = max(0, round_trip_ms - envelope.server_processing_ms)
                remaining_token_ms = envelope.token_ttl_ms - transport_ms
                if remaining_token_ms <= 0:
                    return {
                        "drone_id": drone_id,
                        "success": False,
                        "ready": False,
                        "summary": "Launch preparation token expired in transit",
                        "details": None,
                        "category": CommandResultCategory.ERROR.value,
                        "prepare_state": "unavailable",
                        "error_code": CommandErrorCode.PREFLIGHT_FAILED.value,
                        "error_detail": "No launch command was dispatched",
                        "drone_ip": drone.get("ip"),
                    }
                return {
                    "drone_id": drone_id,
                    "success": True,
                    "ready": True,
                    "summary": envelope.summary,
                    # Never place the opaque token inside evidence/tracker data.
                    "details": {
                        "observation": envelope.observation.model_dump(mode="json"),
                        "immutable_payload_sha256": envelope.immutable_payload_sha256,
                    },
                    "category": "ready",
                    "prepare_state": "ready",
                    "preparation_token": envelope.preparation_token,
                    "received_at_monotonic": time.monotonic(),
                    "remaining_token_ms": remaining_token_ms,
                    "drone_ip": drone.get("ip"),
                }
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                return {
                    "drone_id": drone_id,
                    "success": False,
                    "ready": False,
                    "summary": f"Launch preparation path unreachable: {exc.__class__.__name__}",
                    "details": None,
                    "category": CommandResultCategory.OFFLINE.value,
                    "prepare_state": "unavailable",
                    "error_code": CommandErrorCode.DRONE_UNREACHABLE.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }
            except httpx.TimeoutException as exc:
                return {
                    "drone_id": drone_id,
                    "success": False,
                    "ready": False,
                    "summary": f"Launch preparation timed out: {exc.__class__.__name__}",
                    "details": None,
                    "category": CommandResultCategory.ERROR.value,
                    "prepare_state": "unavailable",
                    "error_code": CommandErrorCode.TIMEOUT.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }
            except (httpx.HTTPError, ValueError) as exc:
                return {
                    "drone_id": drone_id,
                    "success": False,
                    "ready": False,
                    "summary": f"Launch preparation failed: {_compact(exc, 180)}",
                    "details": None,
                    "category": CommandResultCategory.ERROR.value,
                    "prepare_state": "unavailable",
                    "error_code": CommandErrorCode.INTERNAL_ERROR.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }

        def deadline_result(drone: dict[str, Any]) -> dict[str, Any]:
            return {
                "drone_id": _normalize_drone_id(drone),
                "success": False,
                "ready": False,
                "summary": "Launch preparation did not finish before the fleet deadline",
                "details": None,
                "category": CommandResultCategory.ERROR.value,
                "prepare_state": "unavailable",
                "error_code": CommandErrorCode.TIMEOUT.value,
                "error_detail": "No launch command was dispatched",
                "drone_ip": drone.get("ip"),
            }

        results = await self._bounded_map(
            drones,
            prepare,
            recovery=False,
            deadline_sec=operation_deadline,
            deadline_result=deadline_result,
        )

        # The first token must retain enough node-local lease for the complete
        # bounded commit fan-out. GCS subtracts only its own monotonic elapsed
        # duration and never compares clocks across hosts.
        now = time.monotonic()
        commit_budget_ms = int(
            (
                max(1.0, float(getattr(self.params, "GCS_FLEET_DISPATCH_DEADLINE_SEC", 15.0)))
                + max(0.2, float(getattr(self.params, "GCS_COMMAND_HTTP_TIMEOUT_SEC", 5.0)))
                + 1.0
            )
            * 1_000
        )
        preparation_tokens: dict[str, str] = {}
        for drone_id, result in results.items():
            if result.get("prepare_state") != "ready":
                continue
            received_at = result.pop("received_at_monotonic", None)
            initial_remaining = result.pop("remaining_token_ms", None)
            token = result.pop("preparation_token", None)
            remaining_ms = (
                int(initial_remaining - max(0.0, now - float(received_at)) * 1_000)
                if received_at is not None and initial_remaining is not None
                else 0
            )
            if (
                remaining_ms < commit_budget_ms
                or not _is_exact_nonblank_string(token)
            ):
                result.update(
                    {
                        "success": False,
                        "ready": False,
                        "summary": "Launch preparation lease cannot cover the bounded fleet commit",
                        "category": CommandResultCategory.ERROR.value,
                        "prepare_state": "unavailable",
                        "error_code": CommandErrorCode.PREFLIGHT_FAILED.value,
                        "error_detail": "Prepare the complete fleet again; no launch command was dispatched",
                    }
                )
                continue
            preparation_tokens[drone_id] = token

        blocked_ids = sorted(
            drone_id
            for drone_id, result in results.items()
            if result.get("prepare_state") == "blocked"
        )
        unavailable_ids = sorted(
            drone_id
            for drone_id, result in results.items()
            if result.get("prepare_state") == "unavailable"
        )
        all_prepared = (
            not blocked_ids
            and not unavailable_ids
            and len(preparation_tokens) == len(drones)
        )
        if not all_prepared:
            # Do not expose even otherwise-valid token material to callers when
            # the all-target barrier failed. Tokens simply expire on nodes.
            preparation_tokens = {}
        return {
            "all_prepared": all_prepared,
            "blocked_ids": blocked_ids,
            "unavailable_ids": unavailable_ids,
            "preparation_tokens": preparation_tokens,
            "results": results,
        }

    async def dispatch(
        self,
        drones: list[dict[str, Any]],
        command_data: dict[str, Any],
        *,
        callback_capabilities: dict[str, str] | None = None,
        per_target_payloads: dict[str, dict[str, Any]] | None = None,
        launch_preparation_tokens: dict[str, str] | None = None,
        operation_deadline_sec: float | None = None,
        allow_legacy_update_envelope: bool = False,
    ) -> dict[str, Any]:
        """Dispatch one idempotent command attempt to every committed target."""

        if not drones:
            return {
                "success": 0,
                "offline": 0,
                "rejected": 0,
                "errors": 0,
                "failed": 0,
                "unavailable": 0,
                "total": 0,
                "result_summary": "no targets",
                "results": {},
            }

        mission = resolve_mission_type(command_data.get("mission_type"))
        per_target_payloads = validate_per_target_payloads(
            mission,
            [_normalize_drone_id(drone) for drone in drones],
            per_target_payloads,
        )
        target_ids = {_normalize_drone_id(drone) for drone in drones}
        launch_preparation_required = mission_requires_launch_armability_probe(mission)
        if launch_preparation_required:
            if type(launch_preparation_tokens) is not dict:
                raise ValueError(
                    "launch dispatch requires one command-bound preparation token per target"
                )
            if set(launch_preparation_tokens) != target_ids:
                raise ValueError(
                    "launch preparation token targets must exactly match dispatch targets"
                )
            for target_id, token in launch_preparation_tokens.items():
                if not _is_exact_nonblank_string(token) or len(token) < 43:
                    raise ValueError(
                        f"launch preparation token for target {target_id} is invalid"
                    )
        elif launch_preparation_tokens is not None:
            raise ValueError("non-launch commands must not carry launch preparation tokens")
        client = await self._client_or_start()
        recovery = mission_is_recovery(mission)
        request_timeout = max(
            0.2,
            float(getattr(self.params, "GCS_COMMAND_HTTP_TIMEOUT_SEC", 5.0)),
        )
        operation_deadline = float(
            operation_deadline_sec
            or getattr(
                self.params,
                "GCS_FLEET_RECOVERY_DEADLINE_SEC" if recovery else "GCS_FLEET_DISPATCH_DEADLINE_SEC",
                20.0 if recovery else 15.0,
            )
        )
        # Reuse the existing command policy as the single authority for which
        # missions are strict-sync and how trigger-sooner/guard define their
        # last safe queue time.  FleetRPC contributes only the async fan-out
        # enforcement of that policy.
        sync_dispatch_deadline = get_sync_dispatch_deadline(
            mission,
            command_data,
            params=self.params,
        )
        sync_window_limits_operation = False
        if sync_dispatch_deadline is not None:
            sync_window_remaining = sync_dispatch_deadline - time.time()
            if sync_window_remaining <= operation_deadline:
                operation_deadline = max(0.0, sync_window_remaining)
                sync_window_limits_operation = True

        def sync_window_deadline_result(drone: dict[str, Any]) -> dict[str, Any]:
            return {
                "success": False,
                "category": CommandResultCategory.ERROR.value,
                "delivery_state": "not_dispatched_sync_window",
                "error": "Command was not dispatched because the synchronized dispatch window had passed",
                "error_code": CommandErrorCode.TIMEOUT.value,
                "error_detail": "No POST was started for this target; create a newly scheduled command",
                "drone_ip": drone.get("ip"),
            }

        async def send(drone: dict[str, Any]) -> dict[str, Any]:
            drone_id = _normalize_drone_id(drone)
            callback_capability = (callback_capabilities or {}).get(drone_id)
            try:
                command_payload = _build_target_command_payload(
                    command_data,
                    drone_id=drone_id,
                    callback_capability=callback_capability,
                    per_target_payload=(
                        per_target_payloads[drone_id]
                        if per_target_payloads is not None
                        else None
                    ),
                )
            except (TypeError, ValueError, ValidationError) as exc:
                return {
                    "success": False,
                    "category": CommandResultCategory.ERROR.value,
                    "delivery_state": "not_dispatched_invalid_request",
                    "error": f"Command was not dispatched because its target envelope is invalid: {_compact(exc, 180)}",
                    "error_code": CommandErrorCode.INVALID_FORMAT.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }
            url = (
                f"http://{drone.get('ip')}:{self.params.drone_api_port}/"
                f"{self.params.send_drone_command_URI}"
            )
            command_id = command_payload.get("command_id")
            if not _is_exact_nonblank_string(command_id):
                return {
                    "success": False,
                    "category": CommandResultCategory.ERROR.value,
                    "delivery_state": "not_dispatched_invalid_request",
                    "error": "Command was not dispatched because command_id is not a canonical non-blank string",
                    "error_code": CommandErrorCode.INVALID_FORMAT.value,
                    "error_detail": None,
                    "drone_ip": drone.get("ip"),
                }
            def delivery_unknown(
                *,
                error: str,
                error_code: str,
                error_detail: str | None,
                latency_ms: int | None = None,
            ) -> dict[str, Any]:
                result = {
                    "success": False,
                    "category": CommandResultCategory.ERROR.value,
                    "delivery_state": "delivery_unknown",
                    "error": error,
                    "error_code": error_code,
                    "error_detail": error_detail,
                    "drone_ip": drone.get("ip"),
                }
                if latency_ms is not None:
                    result["latency_ms"] = latency_ms
                return result

            started = time.monotonic()
            try:
                # A worker can be scheduled just after the outer monotonic
                # check. Repeat the wall-clock policy check at the transport
                # boundary so a queued strict-sync target is never sent late.
                if (
                    sync_dispatch_deadline is not None
                    and time.time() >= sync_dispatch_deadline
                ):
                    return sync_window_deadline_result(drone)
                headers = (
                    {
                        LAUNCH_PREPARATION_TOKEN_HEADER: launch_preparation_tokens[drone_id]
                    }
                    if launch_preparation_required
                    else None
                )
                response = await client.post(
                    url,
                    json=command_payload,
                    headers=headers,
                    timeout=request_timeout,
                )
                payload = _response_payload(response)
                used_legacy_update_envelope = False
                if (
                    allow_legacy_update_envelope is True
                    and mission is Mission.UPDATE_CODE
                    and _is_legacy_update_envelope_rejection(
                        status_code=response.status_code,
                        payload=payload,
                    )
                ):
                    # Dropping target_hw_id is safe only after a read from the
                    # same host proves that its runtime hardware identity is
                    # the intended numeric target. Any probe failure leaves
                    # the original schema rejection authoritative.
                    identity_matches = False
                    identity_url = (
                        f"http://{drone.get('ip')}:{self.params.drone_api_port}"
                        f"{DRONE_SWARM_STATE_ROUTE}"
                    )
                    try:
                        identity_response = await client.get(
                            identity_url,
                            timeout=request_timeout,
                        )
                    except httpx.HTTPError:
                        identity_response = None
                    if identity_response is not None and identity_response.status_code == 200:
                        identity_hw_id = _response_payload(identity_response).get("hw_id")
                        identity_matches = (
                            type(identity_hw_id) is int
                            and str(identity_hw_id) == drone_id
                        )

                    if identity_matches:
                        # The first request was rejected by FastAPI schema
                        # validation, before the command handler could run.
                        # Retry the same UPDATE_CODE command ID once using only
                        # the old node's envelope. No flight or recovery
                        # mission can enter this compatibility path.
                        legacy_payload = dict(command_payload)
                        legacy_payload.pop("target_hw_id")
                        legacy_payload.pop("command_report_capability")
                        response = await client.post(
                            url,
                            json=legacy_payload,
                            headers=headers,
                            timeout=request_timeout,
                        )
                        payload = _response_payload(response)
                        used_legacy_update_envelope = True
                latency_ms = int((time.monotonic() - started) * 1000)
                if response.status_code != 200:
                    code, message, detail = _node_error_fields(
                        payload,
                        fallback_code=CommandErrorCode.HTTP_ERROR.value,
                    )
                    # A timeout/throttle/server response can be generated
                    # after the node has accepted or persisted the command.
                    # Likewise, a non-200 2xx response violates our protocol
                    # but may describe a command that already took effect.
                    # Reconciliation must use the same command ID.
                    ambiguous_status = (
                        response.status_code in {408, 425, 429}
                        or response.status_code >= 500
                        or 200 <= response.status_code < 300
                    )
                    if ambiguous_status:
                        return delivery_unknown(
                            error=(
                                f"Command delivery is unknown after HTTP {response.status_code}: "
                                f"{message}"
                            ),
                            error_code=code,
                            error_detail=(
                                detail
                                or "Do not submit a new command ID; reconcile this command's tracker/callback state"
                            ),
                            latency_ms=latency_ms,
                        )
                    return {
                        "success": False,
                        "category": CommandResultCategory.REJECTED.value,
                        "delivery_state": "request_rejected",
                        "error": message,
                        "error_code": code,
                        "error_detail": detail,
                        "drone_ip": drone.get("ip"),
                        "latency_ms": latency_ms,
                    }

                status = payload.get("status")
                response_command_id = payload.get("command_id")
                response_hw_id = payload.get("hw_id")
                if type(status) is not str or status not in {"accepted", "rejected"}:
                    return delivery_unknown(
                        error="Command acknowledgement violated the status contract",
                        error_code=CommandErrorCode.INVALID_FORMAT.value,
                        error_detail=(
                            "Expected exact status 'accepted' or 'rejected'; "
                            f"received {status!r}"
                        ),
                        latency_ms=latency_ms,
                    )
                if (
                    not _is_exact_nonblank_string(response_command_id)
                    or response_command_id != command_id
                ):
                    return delivery_unknown(
                        error="Command acknowledgement could not be correlated to the submitted command",
                        error_code=CommandErrorCode.INVALID_FORMAT.value,
                        error_detail=(
                            f"Expected command_id={command_id!r}; "
                            f"received {response_command_id!r}"
                        ),
                        latency_ms=latency_ms,
                    )

                error_code = payload.get("error_code")
                explicit_identity_rejection = (
                    status == "rejected"
                    and error_code == CommandErrorCode.TARGET_IDENTITY_MISMATCH.value
                    and _is_exact_nonblank_string(response_hw_id)
                )
                if response_hw_id != drone_id and not explicit_identity_rejection:
                    # An accepted ACK from a different hardware identity is
                    # particularly dangerous: the POST reached a node and may
                    # already be executing there.  It is not a safe rejection.
                    return delivery_unknown(
                        error="Command response came from a different drone than the selected target",
                        error_code=CommandErrorCode.TARGET_IDENTITY_MISMATCH.value,
                        error_detail=(
                            f"Intended hardware ID={drone_id}; "
                            f"responding hardware ID={response_hw_id!r}. "
                            "Treat this as possible wrong-target delivery and reconcile before retrying"
                        ),
                        latency_ms=latency_ms,
                    )

                if status == "accepted":
                    return {
                        "success": True,
                        "category": CommandResultCategory.ACCEPTED.value,
                        "delivery_state": (
                            "accepted_legacy_update_envelope"
                            if used_legacy_update_envelope
                            else "accepted"
                        ),
                        "error": None,
                        "error_code": None,
                        "error_detail": None,
                        "drone_ip": drone.get("ip"),
                        "latency_ms": latency_ms,
                    }

                code, message, detail = _node_error_fields(
                    payload,
                    fallback_code=CommandErrorCode.HTTP_ERROR.value,
                )
                return {
                    "success": False,
                    "category": CommandResultCategory.REJECTED.value,
                    "delivery_state": "rejected",
                    "error": message,
                    "error_code": code,
                    "error_detail": detail,
                    "drone_ip": drone.get("ip"),
                    "latency_ms": latency_ms,
                }
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                return {
                    "success": False,
                    "category": CommandResultCategory.OFFLINE.value,
                    "delivery_state": "dispatch_unreachable",
                    "error": f"Command path unreachable: {exc.__class__.__name__}",
                    "error_code": CommandErrorCode.DRONE_UNREACHABLE.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }
            except httpx.PoolTimeout as exc:
                # No connection was acquired, so the POST did not leave this
                # process.  This differs from response/write ambiguity.
                return {
                    "success": False,
                    "category": CommandResultCategory.ERROR.value,
                    "delivery_state": "not_dispatched_transport_capacity",
                    "error": "Command was not dispatched before HTTP connection capacity became available",
                    "error_code": CommandErrorCode.TIMEOUT.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }
            except (
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.ReadError,
                httpx.RemoteProtocolError,
            ) as exc:
                # The node may have accepted the POST before the response was
                # lost.  Do not call this offline or blindly send a new ID.
                return delivery_unknown(
                    error=f"Command delivery is unknown after {exc.__class__.__name__}",
                    error_code=(
                        CommandErrorCode.TIMEOUT.value
                        if isinstance(exc, httpx.TimeoutException)
                        else CommandErrorCode.NETWORK_ERROR.value
                    ),
                    error_detail=_compact(exc, 500),
                )
            except httpx.TimeoutException as exc:
                return {
                    "success": False,
                    "category": CommandResultCategory.ERROR.value,
                    "delivery_state": "transport_timeout",
                    "error": f"Command transport timed out: {exc.__class__.__name__}",
                    "error_code": CommandErrorCode.TIMEOUT.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }
            except httpx.HTTPError as exc:
                # client.post() had started and this exception does not prove
                # that zero request bytes reached the peer.  Fail safely as
                # ambiguous rather than invite a new-ID duplicate.
                return delivery_unknown(
                    error=f"Command delivery is unknown after {exc.__class__.__name__}",
                    error_code=CommandErrorCode.NETWORK_ERROR.value,
                    error_detail=_compact(exc, 500),
                )
            except ValueError as exc:
                return {
                    "success": False,
                    "category": CommandResultCategory.ERROR.value,
                    "delivery_state": "not_dispatched_invalid_request",
                    "error": f"Command request could not be encoded: {_compact(exc, 180)}",
                    "error_code": CommandErrorCode.INVALID_FORMAT.value,
                    "error_detail": _compact(exc, 500),
                    "drone_ip": drone.get("ip"),
                }

        def deadline_result(drone: dict[str, Any]) -> dict[str, Any]:
            return {
                "success": False,
                "category": CommandResultCategory.ERROR.value,
                "delivery_state": "not_dispatched_deadline",
                "error": "Command was not dispatched before the bounded fleet deadline",
                "error_code": CommandErrorCode.TIMEOUT.value,
                "error_detail": None,
                "drone_ip": drone.get("ip"),
            }

        def started_deadline_result(drone: dict[str, Any]) -> dict[str, Any]:
            return {
                "success": False,
                "category": CommandResultCategory.ERROR.value,
                "delivery_state": "delivery_unknown",
                "error": "Command delivery is unknown because the fleet deadline expired after dispatch began",
                "error_code": CommandErrorCode.TIMEOUT.value,
                "error_detail": "Do not submit a new command ID; reconcile this command's tracker/callback state",
                "drone_ip": drone.get("ip"),
            }

        started = time.monotonic()
        results = await self._bounded_map(
            drones,
            send,
            recovery=recovery,
            deadline_sec=operation_deadline,
            deadline_result=(
                sync_window_deadline_result
                if sync_window_limits_operation
                else deadline_result
            ),
            started_deadline_result=started_deadline_result,
        )
        accepted = sum(result.get("success") is True for result in results.values())
        offline = sum(result.get("category") == CommandResultCategory.OFFLINE.value for result in results.values())
        rejected = sum(result.get("category") == CommandResultCategory.REJECTED.value for result in results.values())
        errors = len(results) - accepted - offline - rejected
        parts = []
        for count, label in (
            (accepted, "accepted"),
            (offline, "unreachable"),
            (rejected, "rejected"),
            (errors, "delivery errors"),
        ):
            if count:
                parts.append(f"{count} {label}")

        return {
            "success": accepted,
            "offline": offline,
            "rejected": rejected,
            "errors": errors,
            "failed": rejected + errors,
            "unavailable": offline,
            "total": len(drones),
            "success_rate": (accepted / len(drones)) * 100.0,
            "execution_time": time.monotonic() - started,
            "result_summary": ", ".join(parts) if parts else "no results",
            "results": results,
        }


__all__ = ["FleetRPCService"]
