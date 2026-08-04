"""Origin, elevation, and launch-position routes for the GCS FastAPI app."""

import csv
import io
import math
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from origin_reference import (
    OriginReferenceError,
    coerce_valid_origin_values,
    resolve_origin_reference,
)

from schemas import (
    GPSGlobalOriginResponse,
    OriginComputeRequest,
    OriginComputeResponse,
    OriginRequest,
    OriginResponse,
)


_LAUNCH_POSITION_FORMATS = {"json", "csv", "kml"}


def _coerce_origin_timestamp_ms(origin: dict[str, Any]) -> int | None:
    timestamp = origin.get("timestamp")
    if not timestamp:
        return None

    try:
        return int(datetime.fromisoformat(timestamp).timestamp() * 1000)
    except (TypeError, ValueError):
        return int(time.time() * 1000)


def _validate_origin(origin: dict[str, Any] | None, *, detail: str, status_code: int) -> dict[str, Any]:
    if not origin or origin.get("lat") in ("", None) or origin.get("lon") in ("", None):
        raise HTTPException(status_code=status_code, detail=detail)
    return origin


def _build_origin_response(origin: dict[str, Any]) -> OriginResponse:
    return OriginResponse(
        lat=float(origin.get("lat", 0)),
        lon=float(origin.get("lon", 0)),
        alt=float(origin.get("alt", 0)),
        timestamp=_coerce_origin_timestamp_ms(origin),
        source=str(origin.get("alt_source", "unknown")),
    )


def _render_launch_positions_csv(payload: dict[str, Any]) -> Response:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "pos_id",
            "hw_id",
            "latitude",
            "longitude",
            "altitude",
            "north",
            "east",
            "trajectory_north",
            "trajectory_east",
        ],
    )
    writer.writeheader()
    writer.writerows(payload.get("positions", []))

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=desired_launch_positions.csv",
        },
    )


def _render_launch_positions_kml(payload: dict[str, Any]) -> Response:
    heading = payload.get("heading", 0)
    positions = payload.get("positions", [])

    lines = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<kml xmlns=\"http://www.opengis.net/kml/2.2\">",
        "  <Document>",
        "    <name>Desired Launch Positions</name>",
        f"    <description>Formation heading {heading:.1f} degrees</description>",
    ]

    for position in positions:
        pos_id = position.get("pos_id")
        hw_id = position.get("hw_id")
        latitude = position.get("latitude")
        longitude = position.get("longitude")
        altitude = position.get("altitude", 0)
        north = position.get("north", 0)
        east = position.get("east", 0)
        trajectory_north = position.get("trajectory_north", 0)
        trajectory_east = position.get("trajectory_east", 0)

        lines.extend([
            "    <Placemark>",
            f"      <name>Drone P{pos_id} | H{hw_id}</name>",
            "      <ExtendedData>",
            f"        <Data name=\"north\"><value>{north}</value></Data>",
            f"        <Data name=\"east\"><value>{east}</value></Data>",
            f"        <Data name=\"trajectory_north\"><value>{trajectory_north}</value></Data>",
            f"        <Data name=\"trajectory_east\"><value>{trajectory_east}</value></Data>",
            "      </ExtendedData>",
            "      <Point>",
            f"        <coordinates>{longitude},{latitude},{altitude}</coordinates>",
            "      </Point>",
            "    </Placemark>",
        ])

    lines.extend([
        "  </Document>",
        "</kml>",
    ])

    return Response(
        content="\n".join(lines),
        media_type="application/vnd.google-earth.kml+xml",
        headers={
            "Content-Disposition": "attachment; filename=desired_launch_positions.kml",
        },
    )


def create_origin_router(deps: Any) -> APIRouter:
    router = APIRouter()

    def _reference_max_age_ms() -> int:
        configured_seconds = getattr(deps.Params, "LOCAL_MAVLINK_STALE_TIMEOUT_SEC", 15)
        try:
            return max(1, int(float(configured_seconds) * 1000))
        except (TypeError, ValueError):
            return 15_000

    def _compute_drone_reference_candidate(hw_id: str) -> dict[str, Any]:
        drones_config = deps.load_config() or []
        with deps.telemetry_lock:
            telemetry_snapshot = {
                key: dict(value or {})
                for key, value in (deps.telemetry_data_all_drones or {}).items()
            }

        try:
            reference = resolve_origin_reference(
                hw_id=hw_id,
                drones_config=drones_config,
                telemetry_snapshot=telemetry_snapshot,
                now_ms=int(time.time() * 1000),
                max_age_ms=_reference_max_age_ms(),
            )
        except OriginReferenceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        sim_mode = getattr(deps.Params, "sim_mode", False)
        intended_north, intended_east = deps.get_expected_position_from_trajectory(
            reference["pos_id"],
            sim_mode,
        )
        if intended_north is None or intended_east is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "ORIGIN_REFERENCE_TRAJECTORY_MISSING",
                    "message": (
                        f"No trajectory start is available for show slot {reference['pos_id']}. "
                        "Import or select the mission trajectories before setting origin."
                    ),
                },
            )

        try:
            intended_north = float(intended_north)
            intended_east = float(intended_east)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ORIGIN_REFERENCE_TRAJECTORY_INVALID",
                    "message": f"Show slot {reference['pos_id']} has invalid trajectory start offsets.",
                },
            ) from exc
        if not math.isfinite(intended_north) or not math.isfinite(intended_east):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ORIGIN_REFERENCE_TRAJECTORY_INVALID",
                    "message": f"Show slot {reference['pos_id']} has non-finite trajectory start offsets.",
                },
            )

        origin_lat, origin_lon = deps.compute_origin_from_drone(
            reference["latitude"],
            reference["longitude"],
            intended_north,
            intended_east,
        )
        try:
            origin_lat, origin_lon, origin_alt = coerce_valid_origin_values(
                origin_lat,
                origin_lon,
                reference["altitude_msl"],
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ORIGIN_REFERENCE_COMPUTATION_INVALID",
                    "message": "The computed formation origin is invalid; review the reference telemetry and trajectory start.",
                },
            ) from exc
        return {
            "status": "success",
            "origin": {
                "lat": origin_lat,
                "lon": origin_lon,
                "alt": origin_alt,
                "source": "drone_global_position_msl",
            },
            "reference": reference,
            "intended_offset": {
                "north_m": intended_north,
                "east_m": intended_east,
            },
        }

    @router.get("/api/v1/origin", response_model=OriginResponse, tags=["Origin"])
    async def get_origin():
        """Get current origin coordinates."""
        try:
            origin = _validate_origin(
                deps.load_origin(),
                detail="Origin not set",
                status_code=404,
            )
            return _build_origin_response(origin)
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"Error retrieving origin: {exc}", "origin")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/origin", response_model=OriginResponse, tags=["Origin"])
    async def set_origin(origin_req: OriginRequest):
        """Persist a manual origin or atomically derive one from live drone telemetry."""
        try:
            if origin_req.method == "drone_reference":
                candidate = _compute_drone_reference_candidate(origin_req.hw_id)
                candidate_origin = candidate["origin"]
                reference = candidate["reference"]
                origin_data = {
                    "lat": candidate_origin["lat"],
                    "lon": candidate_origin["lon"],
                    "alt": candidate_origin["alt"],
                    "alt_source": candidate_origin["source"],
                    "reference_hw_id": reference["hw_id"],
                    "reference_pos_id": reference["pos_id"],
                    "reference_position_timestamp_ms": reference["position_timestamp_ms"],
                    "timestamp": datetime.now().isoformat(),
                    "version": 2,
                }
            else:
                origin_data = {
                    "lat": origin_req.lat,
                    "lon": origin_req.lon,
                    "alt": float(origin_req.alt),
                    "alt_source": "manual",
                    "timestamp": datetime.now().isoformat(),
                    "version": 2,
                }
            deps.save_origin(origin_data)

            return OriginResponse(
                lat=float(origin_data["lat"]),
                lon=float(origin_data["lon"]),
                alt=float(origin_data["alt"]),
                timestamp=int(time.time() * 1000),
                source=str(origin_data["alt_source"]),
            )
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"Error setting origin: {exc}", "origin")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/navigation/global-origin", response_model=GPSGlobalOriginResponse, tags=["Origin"])
    async def get_gps_global_origin():
        """Get GPS global origin."""
        try:
            origin = deps.load_origin()
            has_origin = bool(origin and origin.get("lat") not in ("", None) and origin.get("lon") not in ("", None))

            return GPSGlobalOriginResponse(
                latitude=float(origin.get("lat", 0)) if origin else 0,
                longitude=float(origin.get("lon", 0)) if origin else 0,
                altitude=float(origin.get("alt", 0)) if origin else 0,
                has_origin=has_origin,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/origin/elevation", tags=["Origin"])
    async def get_elevation_endpoint(
        lat: float = Query(..., description="Latitude"),
        lon: float = Query(..., description="Longitude"),
    ):
        """Get elevation data for coordinates."""
        try:
            elevation_data = deps.get_elevation(lat, lon)
            if elevation_data:
                return JSONResponse(content=elevation_data)
            raise HTTPException(status_code=500, detail="Failed to fetch elevation data")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/origin/bootstrap", response_model=OriginResponse, tags=["Origin"])
    async def get_origin_bootstrap():
        """Canonical origin bootstrap payload for flight/runtime consumers."""
        try:
            origin = _validate_origin(
                deps.load_origin(),
                detail="Origin not set. Use dashboard to set origin.",
                status_code=404,
            )
            return _build_origin_response(origin)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to retrieve origin: {exc}") from exc

    async def _build_origin_bootstrap_payload():
        """Lightweight endpoint for drones to fetch origin before flight."""
        try:
            origin = _validate_origin(
                deps.load_origin(),
                detail="Origin not set. Use dashboard to set origin.",
                status_code=404,
            )
            return JSONResponse(content={
                "lat": float(origin["lat"]),
                "lon": float(origin["lon"]),
                "alt": float(origin.get("alt", 0)),
                "timestamp": origin.get("timestamp", ""),
                "source": origin.get("alt_source", "unknown"),
            })
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to retrieve origin: {exc}") from exc

    @router.get("/api/v1/origin/deviations", tags=["Origin"])
    async def get_position_deviations():
        """Compare expected launch geometry with current telemetry for all configured drones."""
        try:
            origin = _validate_origin(
                deps.load_origin(),
                detail="Origin coordinates not set on GCS",
                status_code=400,
            )
            origin_lat = float(origin["lat"])
            origin_lon = float(origin["lon"])
            origin_alt = float(origin.get("alt", 0))

            drones_config = deps.load_config()
            if not drones_config:
                raise HTTPException(status_code=500, detail="No drones configuration found")

            with deps.telemetry_lock:
                telemetry_data_copy = deps.telemetry_data_all_drones.copy()

            report = deps.build_position_deviation_report(
                telemetry_data_copy,
                drones_config,
                origin_lat,
                origin_lon,
                origin_alt,
                trajectory_resolver=deps.get_expected_position_from_trajectory,
            )
            return JSONResponse(content=report)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/origin/compute", response_model=OriginComputeResponse, tags=["Origin"])
    async def compute_origin_endpoint(payload: OriginComputeRequest):
        """Preview origin from a configured drone's fresh, valid global position."""
        try:
            return OriginComputeResponse(**_compute_drone_reference_candidate(payload.hw_id))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/origin/launch-positions", tags=["Origin"])
    async def get_desired_launch_positions(
        heading: float = Query(0, ge=0, lt=360, description="Formation heading (degrees)"),
        format: str = Query("json", description="Output format (json/csv/kml)"),
    ):
        """Calculate desired launch positions and export them in the requested format."""
        try:
            normalized_format = str(format).strip().lower()
            if normalized_format not in _LAUNCH_POSITION_FORMATS:
                raise HTTPException(status_code=400, detail="format must be one of: json, csv, kml")

            origin_data = _validate_origin(
                deps.load_origin(),
                detail="Origin not set",
                status_code=400,
            )
            origin_lat = float(origin_data["lat"])
            origin_lon = float(origin_data["lon"])
            origin_alt = float(origin_data.get("alt", 0))

            drones = deps.load_config()
            if not drones:
                raise HTTPException(status_code=404, detail="No drones configured")

            payload = deps.build_desired_launch_positions_report(
                drones,
                origin_lat,
                origin_lon,
                origin_alt,
                heading,
                getattr(deps.Params, "sim_mode", False),
                trajectory_resolver=deps.get_expected_position_from_trajectory,
            )

            if normalized_format == "csv":
                return _render_launch_positions_csv(payload)
            if normalized_format == "kml":
                return _render_launch_positions_kml(payload)
            return JSONResponse(content=payload)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
