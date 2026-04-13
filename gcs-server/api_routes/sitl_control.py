"""SITL Control read-only supervisor routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path as PathParam, Query

from src.gcs_api_routes import (
    GCS_SITL_CONTROL_HOST_ROUTE,
    GCS_SITL_CONTROL_IMAGES_ROUTE,
    GCS_SITL_CONTROL_INSTANCE_CREATE_ROUTE,
    GCS_SITL_CONTROL_INSTANCE_LOGS_ROUTE_TEMPLATE,
    GCS_SITL_CONTROL_INSTANCE_REMOVE_ROUTE_TEMPLATE,
    GCS_SITL_CONTROL_INSTANCE_RESTART_ROUTE_TEMPLATE,
    GCS_SITL_CONTROL_INSTANCES_ROUTE,
    GCS_SITL_CONTROL_OPERATION_ROUTE_TEMPLATE,
    GCS_SITL_CONTROL_OPERATIONS_ROUTE,
    GCS_SITL_CONTROL_POLICY_ROUTE,
    GCS_SITL_CONTROL_RECONCILE_ROUTE,
)
from src.sitl_control_models import (
    SitlControlHostResponse,
    SitlControlImageListResponse,
    SitlControlCreateInstanceRequest,
    SitlControlInstanceListResponse,
    SitlControlInstanceLogResponse,
    SitlControlOperationListResponse,
    SitlControlOperationResponse,
    SitlControlPolicyResponse,
    SitlControlReconcileRequest,
)
from src.sitl_control_service import SitlControlService


def _get_service(deps: Any) -> SitlControlService:
    service = getattr(deps, "sitl_control_service", None)
    if service is not None:
        return service
    return SitlControlService(deps.Params)


def create_sitl_control_router(deps: Any) -> APIRouter:
    router = APIRouter()
    service = _get_service(deps)

    @router.get(GCS_SITL_CONTROL_POLICY_ROUTE, response_model=SitlControlPolicyResponse, tags=["SITL Control"])
    async def get_sitl_control_policy():
        try:
            return service.build_policy()
        except Exception as exc:
            deps.log_system_error(f"SITL control policy failed: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(GCS_SITL_CONTROL_HOST_ROUTE, response_model=SitlControlHostResponse, tags=["SITL Control"])
    async def get_sitl_control_host():
        try:
            return service.build_host_summary()
        except Exception as exc:
            deps.log_system_error(f"SITL control host summary failed: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(GCS_SITL_CONTROL_IMAGES_ROUTE, response_model=SitlControlImageListResponse, tags=["SITL Control"])
    async def get_sitl_control_images():
        try:
            return service.list_images()
        except Exception as exc:
            deps.log_system_error(f"SITL control image listing failed: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(GCS_SITL_CONTROL_INSTANCES_ROUTE, response_model=SitlControlInstanceListResponse, tags=["SITL Control"])
    async def get_sitl_control_instances():
        try:
            return service.list_instances()
        except Exception as exc:
            deps.log_system_error(f"SITL control instance listing failed: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post(
        GCS_SITL_CONTROL_INSTANCE_CREATE_ROUTE,
        response_model=SitlControlOperationResponse,
        tags=["SITL Control"],
    )
    async def create_sitl_control_instance(request: SitlControlCreateInstanceRequest):
        try:
            return service.create_instance(request)
        except Exception as exc:
            deps.log_system_error(f"SITL instance create failed: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(
        GCS_SITL_CONTROL_INSTANCE_LOGS_ROUTE_TEMPLATE,
        response_model=SitlControlInstanceLogResponse,
        tags=["SITL Control"],
    )
    async def get_sitl_control_instance_logs(
        instance_name: str = PathParam(..., description="Docker container name"),
        tail: int = Query(200, ge=1, le=1000, description="Number of log lines to tail"),
    ):
        try:
            return service.get_instance_logs(instance_name, tail_lines=tail)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            deps.log_system_error(f"SITL control log fetch failed for {instance_name}: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(GCS_SITL_CONTROL_OPERATIONS_ROUTE, response_model=SitlControlOperationListResponse, tags=["SITL Control"])
    async def list_sitl_control_operations(limit: int = Query(20, ge=1, le=50)):
        try:
            return service.list_operations(limit=limit)
        except Exception as exc:
            deps.log_system_error(f"SITL control operation listing failed: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(
        GCS_SITL_CONTROL_OPERATION_ROUTE_TEMPLATE,
        response_model=SitlControlOperationResponse,
        tags=["SITL Control"],
    )
    async def get_sitl_control_operation(operation_id: str = PathParam(..., description="SITL operation identifier")):
        operation = service.get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"SITL operation {operation_id} not found")
        return operation

    @router.post(
        GCS_SITL_CONTROL_RECONCILE_ROUTE,
        response_model=SitlControlOperationResponse,
        tags=["SITL Control"],
    )
    async def create_sitl_control_reconcile(request: SitlControlReconcileRequest):
        try:
            return service.start_reconcile(request)
        except Exception as exc:
            deps.log_system_error(f"SITL reconcile request failed: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post(
        GCS_SITL_CONTROL_INSTANCE_RESTART_ROUTE_TEMPLATE,
        response_model=SitlControlOperationResponse,
        tags=["SITL Control"],
    )
    async def restart_sitl_control_instance(instance_name: str = PathParam(..., description="Docker container name")):
        try:
            return service.restart_instance(instance_name)
        except Exception as exc:
            deps.log_system_error(f"SITL instance restart failed for {instance_name}: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.delete(
        GCS_SITL_CONTROL_INSTANCE_REMOVE_ROUTE_TEMPLATE,
        response_model=SitlControlOperationResponse,
        tags=["SITL Control"],
    )
    async def remove_sitl_control_instance(instance_name: str = PathParam(..., description="Docker container name")):
        try:
            return service.remove_instance(instance_name)
        except Exception as exc:
            deps.log_system_error(f"SITL instance removal failed for {instance_name}: {exc}", "sitl_control")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
