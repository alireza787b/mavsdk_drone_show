"""Core GCS FastAPI routes for health, telemetry, and heartbeats."""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from schemas import (
    HealthCheckResponse,
    HeartbeatData,
    HeartbeatPostResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatStreamMessage,
    NetworkStatusResponse,
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

    current_time = time.time()
    heartbeat_timeout = deps.Params.TELEMETRY_POLLING_TIMEOUT
    heartbeats_list = []

    for hw_id, hb_data in heartbeats_dict.items():
        last_timestamp = hb_data.get("timestamp", 0)
        if last_timestamp:
            time_diff = current_time - (last_timestamp / 1000.0)
            is_online = time_diff < heartbeat_timeout
        else:
            is_online = False

        network_info = hb_data.get("network_info", {})
        latency_ms = network_info.get("latency_ms") if network_info else None

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
            latency_ms=latency_ms,
        )
        heartbeats_list.append(heartbeat_obj)

    online_count = len([heartbeat for heartbeat in heartbeats_list if heartbeat.online])
    return HeartbeatResponse(
        heartbeats=heartbeats_list,
        total_drones=len(heartbeats_list),
        online_count=online_count,
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
        await websocket.accept()
        deps.log_system_event("Telemetry WebSocket client connected", "INFO", "websocket")

        try:
            while True:
                message = TelemetryStreamMessage(
                    type="telemetry",
                    timestamp=int(time.time() * 1000),
                    data=deps.telemetry_data_all_drones,
                )
                await websocket.send_json(message.model_dump())
                await asyncio.sleep(1.0)
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

    @router.get("/api/v1/fleet/heartbeats", response_model=HeartbeatResponse, tags=["Heartbeat"])
    async def get_heartbeats():
        return _build_heartbeat_response(deps)

    @router.get("/api/v1/fleet/network-status", response_model=NetworkStatusResponse, tags=["Heartbeat"])
    async def get_network_status():
        return _build_network_status_response(deps)

    @router.websocket("/ws/heartbeats")
    async def websocket_heartbeats(websocket: WebSocket):
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
