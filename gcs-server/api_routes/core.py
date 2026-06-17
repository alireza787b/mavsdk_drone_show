"""Core GCS FastAPI routes for health, telemetry, and heartbeats."""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from auth_runtime import authorize_websocket
from node_boot_status import get_all_node_boot_statuses, handle_node_boot_status_post
from presence import build_presence_snapshot, resolve_presence_thresholds
from schemas import (
    HealthCheckResponse,
    HeartbeatData,
    HeartbeatPostResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatStreamMessage,
    NetworkStatusResponse,
    NodeBootStatusPostResponse,
    NodeBootStatusReport,
    NodeBootStatusResponse,
    TelemetryResponse,
    TelemetryStreamMessage,
)

_PROCESS_START_MONOTONIC = time.monotonic()


def _build_health_check_response(deps: Any) -> HealthCheckResponse:
    return HealthCheckResponse(
        status="ok",
        timestamp=int(time.time() * 1000),
        uptime_seconds=max(0.0, time.monotonic() - _PROCESS_START_MONOTONIC),
        version=deps.MDS_VERSION,
    )


def _build_typed_telemetry_response(deps: Any, response: Response | None = None) -> TelemetryResponse:
    telemetry_data = deps.telemetry_data_all_drones
    online_count = len([
        drone for drone in telemetry_data.values()
        if drone and drone.get("telemetry_available", True)
    ])
    if response is not None:
        response.headers["X-MDS-Server-Time"] = str(int(time.time() * 1000))

    return TelemetryResponse(
        telemetry=telemetry_data,
        total_drones=len(telemetry_data),
        online_drones=online_count,
        timestamp=int(time.time() * 1000),
    )


def _build_heartbeat_response(deps: Any) -> HeartbeatResponse:
    heartbeats_dict = deps.get_all_heartbeats()
    drones_config = deps.load_config()
    config_lookup = {str(drone["hw_id"]): drone for drone in drones_config}
    config_hw_ids = set(config_lookup)

    current_time = time.time()
    thresholds = resolve_presence_thresholds(deps.Params)
    heartbeats_list = []
    state_counts: dict[str, int] = {}

    data_lock = getattr(deps, "data_lock", None)
    telemetry_rows = getattr(deps, "telemetry_data_all_drones", {}) or {}
    telemetry_success_times = getattr(deps, "last_telemetry_time", {}) or {}
    if data_lock is not None:
        with data_lock:
            telemetry_rows = {str(key): dict(value or {}) for key, value in telemetry_rows.items()}
            telemetry_success_times = {str(key): value for key, value in telemetry_success_times.items()}
    else:
        telemetry_rows = {str(key): dict(value or {}) for key, value in telemetry_rows.items()}
        telemetry_success_times = {str(key): value for key, value in telemetry_success_times.items()}

    all_hw_ids = sorted(config_hw_ids | {str(key) for key in heartbeats_dict} | set(telemetry_rows))
    for hw_id in all_hw_ids:
        hb_data = heartbeats_dict.get(str(hw_id), {}) if isinstance(heartbeats_dict.get(str(hw_id)), dict) else {}
        last_timestamp = hb_data.get("timestamp", 0)
        presence = build_presence_snapshot(
            hw_id=hw_id,
            heartbeat=hb_data,
            telemetry=telemetry_rows.get(str(hw_id), {}),
            telemetry_success_time=telemetry_success_times.get(str(hw_id)),
            configured=str(hw_id) in config_hw_ids,
            now=current_time,
            thresholds=thresholds,
        )
        is_online = bool(presence["fresh"])
        presence_state = str(presence["state"])
        heartbeat_age_sec = presence.get("heartbeat_age_sec")
        state_counts[presence_state] = state_counts.get(presence_state, 0) + 1

        ip_value = hb_data.get("ip")
        if ip_value is not None:
            ip_value = str(ip_value).strip()
        if ip_value in {"", "unknown", "n/a", "none", None}:
            ip_value = config_lookup.get(str(hw_id), {}).get("ip", "unknown")

        heartbeat_obj = HeartbeatData(
            hw_id=str(hw_id),
            pos_id=int(hb_data.get("pos_id", 0)),
            ip=str(ip_value) if ip_value else "unknown",
            detected_pos_id=hb_data.get("detected_pos_id"),
            runtime_mode=hb_data.get("runtime_mode"),
            last_heartbeat=last_timestamp,
            online=is_online,
            heartbeat_age_sec=heartbeat_age_sec,
            presence_state=presence_state,
            presence=presence,
        )
        heartbeats_list.append(heartbeat_obj)

    online_count = len([heartbeat for heartbeat in heartbeats_list if heartbeat.online])
    return HeartbeatResponse(
        heartbeats=heartbeats_list,
        total_drones=len(heartbeats_list),
        online_count=online_count,
        state_counts=state_counts,
        timestamp=int(time.time() * 1000),
    )


def _build_network_status_response(deps: Any) -> NetworkStatusResponse:
    network_info = deps.get_network_info_from_heartbeats()
    if not isinstance(network_info, dict):
        network_info = {}
    reachable_count = len([
        network for network in network_info.values()
        if network.get("reachable", False)
    ])

    return NetworkStatusResponse(
        network_status=network_info,
        total_drones=len(network_info),
        reachable_count=reachable_count,
        timestamp=int(time.time() * 1000),
    )


def _build_node_boot_status_response() -> NodeBootStatusResponse:
    nodes = get_all_node_boot_statuses()
    return NodeBootStatusResponse(
        nodes=nodes,
        total_nodes=len(nodes),
        timestamp=int(time.time() * 1000),
    )


def _configured_node_metadata(deps: Any) -> dict[str, dict[str, Any]]:
    loader = getattr(deps, "load_config", None)
    if not callable(loader):
        return {}
    try:
        rows = loader()
    except Exception as exc:
        raise ValueError(f"Unable to load fleet configuration for node boot status: {exc}") from exc
    if not isinstance(rows, list):
        return {}

    configured: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict):
            value = row.get("hw_id")
            pos_id = row.get("pos_id")
            ip = row.get("ip")
        else:
            value = getattr(row, "hw_id", None)
            pos_id = getattr(row, "pos_id", None)
            ip = getattr(row, "ip", None)
        text = str(value if value is not None else "").strip()
        if text:
            configured[text] = {
                "pos_id": pos_id,
                "ip": str(ip).strip() if ip not in (None, "") else None,
            }
    return configured


def _accept_node_boot_status(deps: Any, report: NodeBootStatusReport, request: Request) -> NodeBootStatusPostResponse:
    client_ip = request.client.host if request.client else None
    configured_nodes = _configured_node_metadata(deps)
    if not configured_nodes:
        raise ValueError("Node boot status requires configured fleet hardware IDs")
    node_config = configured_nodes.get(str(report.hw_id).strip())
    if not node_config:
        raise ValueError(f"Node boot status rejected for unconfigured hw_id={report.hw_id}")

    configured_pos_id = node_config.get("pos_id")
    try:
        configured_pos_id = int(configured_pos_id) if configured_pos_id not in (None, "") else None
    except (TypeError, ValueError):
        configured_pos_id = None
    if report.pos_id is not None and configured_pos_id is not None and int(report.pos_id) != configured_pos_id:
        raise ValueError(
            f"Node boot status rejected for hw_id={report.hw_id}: pos_id does not match fleet configuration"
        )

    configured_ip = str(node_config.get("ip") or "").strip() or None
    if report.ip and configured_ip and report.ip.strip() != configured_ip:
        raise ValueError(
            f"Node boot status rejected for hw_id={report.hw_id}: ip does not match fleet configuration"
        )
    source_ip_matched = bool(configured_ip and client_ip == configured_ip)
    identity_trust = "source_ip_matched" if source_ip_matched else "config_bound"
    result = handle_node_boot_status_post(
        hw_id=report.hw_id,
        pos_id=configured_pos_id if configured_pos_id is not None else report.pos_id,
        ip=configured_ip or report.ip or client_ip,
        runtime_mode=report.runtime_mode,
        phase=report.phase,
        status=report.status,
        message=report.message,
        source=report.source,
        timestamp=report.timestamp,
        allowed_hw_ids=set(configured_nodes),
        identity_trust=identity_trust,
        source_ip_matched=source_ip_matched,
    )
    return NodeBootStatusPostResponse(
        success=True,
        message="Node boot status received",
        node=result["node"],
        server_time=int(time.time() * 1000),
    )


def _accept_heartbeat(deps: Any, heartbeat: HeartbeatRequest, request: Request) -> HeartbeatPostResponse:
    client_ip = request.client.host if request.client else None
    heartbeat_ip = heartbeat.ip.strip() if heartbeat.ip else None
    if heartbeat_ip in {"", "unknown", "n/a", "none"}:
        heartbeat_ip = None
    observed_ip = heartbeat_ip or client_ip

    heartbeat_result = deps.handle_heartbeat_post(
        pos_id=heartbeat.pos_id,
        hw_id=heartbeat.hw_id,
        detected_pos_id=heartbeat.detected_pos_id,
        ip=observed_ip,
        timestamp=heartbeat.timestamp,
        network_info=heartbeat.network_info,
        runtime_mode=heartbeat.runtime_mode,
    )

    observer = getattr(deps, "observe_fleet_candidate_heartbeat", None)
    if heartbeat_result.get("accepted", True) and callable(observer):
        try:
            observer(
                {
                    "pos_id": heartbeat.pos_id,
                    "hw_id": heartbeat.hw_id,
                    "detected_pos_id": heartbeat.detected_pos_id,
                    "ip": observed_ip,
                    "timestamp": heartbeat.timestamp,
                    "network_info": heartbeat.network_info,
                    "runtime_mode": heartbeat.runtime_mode,
                }
            )
        except Exception as exc:  # pragma: no cover - heartbeat acceptance remains primary
            deps.log_system_error(f"Fleet candidate heartbeat observation failed: {exc}", "fleet_enrollment")

    return HeartbeatPostResponse(
        success=True,
        message=heartbeat_result.get("message", "Heartbeat received"),
        server_time=int(time.time() * 1000),
    )


def create_core_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/system/health", response_model=HealthCheckResponse, tags=["System"])
    @router.get("/ping", response_model=HealthCheckResponse, tags=["System"])
    @router.get("/health", response_model=HealthCheckResponse, tags=["System"])
    async def health_check():
        return _build_health_check_response(deps)

    @router.get("/api/v1/fleet/telemetry", response_model=TelemetryResponse, tags=["Telemetry"])
    async def get_telemetry_typed(response: Response):
        return _build_typed_telemetry_response(deps, response=response)

    @router.websocket("/ws/telemetry")
    async def websocket_telemetry(websocket: WebSocket):
        if await authorize_websocket(websocket) is None:
            return
        await websocket.accept()
        deps.log_system_event("Telemetry WebSocket client connected", "INFO", "websocket")
        try:
            requested_interval_ms = int(websocket.query_params.get("interval_ms", "1000"))
        except (TypeError, ValueError):
            requested_interval_ms = 1000
        stream_interval_sec = max(0.5, min(requested_interval_ms / 1000.0, 6.0))

        try:
            while True:
                message = TelemetryStreamMessage(
                    type="telemetry",
                    timestamp=int(time.time() * 1000),
                    data=deps.telemetry_data_all_drones,
                )
                await websocket.send_json(message.model_dump())
                await asyncio.sleep(stream_interval_sec)
        except WebSocketDisconnect:
            deps.log_system_event("Telemetry WebSocket client disconnected", "INFO", "websocket")
        except Exception as exc:
            deps.log_system_error(f"Telemetry WebSocket error: {exc}", "websocket")

    @router.post("/api/v1/fleet/heartbeats", response_model=HeartbeatPostResponse, tags=["Heartbeat"])
    async def post_heartbeat(heartbeat: HeartbeatRequest, request: Request):
        try:
            return _accept_heartbeat(deps, heartbeat, request)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/fleet/node-boot-status", response_model=NodeBootStatusPostResponse, tags=["Fleet"])
    async def post_node_boot_status(report: NodeBootStatusReport, request: Request):
        try:
            return _accept_node_boot_status(deps, report, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/fleet/node-boot-status", response_model=NodeBootStatusResponse, tags=["Fleet"])
    async def get_node_boot_status():
        return _build_node_boot_status_response()

    @router.get("/api/v1/fleet/heartbeats", response_model=HeartbeatResponse, tags=["Heartbeat"])
    async def get_heartbeats():
        return _build_heartbeat_response(deps)

    @router.get("/api/v1/fleet/network-status", response_model=NetworkStatusResponse, tags=["Heartbeat"])
    async def get_network_status():
        return _build_network_status_response(deps)

    @router.websocket("/ws/heartbeats")
    async def websocket_heartbeats(websocket: WebSocket):
        if await authorize_websocket(websocket) is None:
            return
        await websocket.accept()
        deps.log_system_event("Heartbeat WebSocket client connected", "INFO", "websocket")

        try:
            while True:
                heartbeat_snapshot = _build_heartbeat_response(deps)
                message = HeartbeatStreamMessage(
                    type="heartbeat",
                    timestamp=int(time.time() * 1000),
                    data=heartbeat_snapshot.heartbeats,
                )
                await websocket.send_json(message.model_dump())
                await asyncio.sleep(2.0)
        except WebSocketDisconnect:
            deps.log_system_event("Heartbeat WebSocket client disconnected", "INFO", "websocket")
        except Exception as exc:
            deps.log_system_error(f"Heartbeat WebSocket error: {exc}", "websocket")

    return router
