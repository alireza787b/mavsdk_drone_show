"""GCS management and network helper routes."""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from schemas import GCSConfigResponse, GCSConfigSaveResponse, GCSConfigUpdateRequest


def _build_gcs_config_response(deps: Any) -> GCSConfigResponse:
    return GCSConfigResponse(
        sim_mode=bool(deps.Params.sim_mode),
        gcs_port=int(deps.Params.gcs_api_port),
        git_auto_push=bool(deps.Params.GIT_AUTO_PUSH),
        acceptable_deviation=float(deps.Params.acceptable_deviation),
    )


def create_management_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/system/gcs-config", response_model=GCSConfigResponse, tags=["GCS Management"])
    async def get_gcs_config():
        """Get the current GCS runtime configuration surface exposed to the UI."""
        try:
            return _build_gcs_config_response(deps)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/system/gcs-config", response_model=GCSConfigSaveResponse, tags=["GCS Management"])
    async def save_gcs_config(payload: GCSConfigUpdateRequest | None = None):
        """Stub acknowledgement for GCS config updates.

        The current UI expects an ACK surface here, but the FastAPI runtime does not
        persist Params mutations yet. Return an explicit compatibility response
        instead of pretending a durable save occurred.
        """
        try:
            del payload

            return GCSConfigSaveResponse(
                success=True,
                status="success",
                message="GCS configuration received, but persistence is not implemented in this runtime",
                persisted=False,
                warnings=[
                    "No server-side config file was changed. This endpoint remains a non-persisted stub until dedicated GCS config persistence is implemented.",
                ],
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/fleet/network-details", tags=["Network"])
    async def get_network_info():
        """Get per-drone network metadata gathered from heartbeats."""
        try:
            return JSONResponse(content=deps.get_network_info_from_heartbeats())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
