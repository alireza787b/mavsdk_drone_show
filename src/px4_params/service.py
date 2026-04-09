"""Drone-local PX4 parameter access helpers."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Iterable, Optional

from mavsdk.component_information import ComponentInformationError
from mavsdk.param import ParamError

from src.px4_param_models import (
    Px4ParamMetadataSource,
    Px4ParamPatchApplyRequest,
    Px4ParamPatchApplyResponse,
    Px4ParamPatchResult,
    Px4ParamPolicyDocs,
    Px4ParamPolicyMetadata,
    Px4ParamPolicyMutations,
    Px4ParamPolicyResponse,
    Px4ParamRow,
    Px4ParamSetRequest,
    Px4ParamSetResponse,
    Px4ParamSnapshotResponse,
    Px4ParamSnapshotSummary,
    Px4ParamValueResponse,
    Px4ParamValueType,
)


class Px4ParamService:
    """Thin service for snapshot/read/write operations against local PX4 parameters."""

    def __init__(self, params: Any, *, hw_id: str) -> None:
        self.params = params
        self.hw_id = str(hw_id)

    def build_policy(self) -> Px4ParamPolicyResponse:
        docs_version = self._safe_docs_version()
        docs_base = self._build_docs_base_url(docs_version)
        return Px4ParamPolicyResponse(
            docs=Px4ParamPolicyDocs(
                provider="px4_parameter_reference",
                version=docs_version,
                base_url=docs_base,
            ),
            metadata=Px4ParamPolicyMetadata(
                runtime_values="mavsdk_param",
                float_metadata="mavsdk_component_information_float_only",
                docs_links="px4_parameter_reference",
                reboot_required="unknown_until_catalog",
            ),
            mutations=Px4ParamPolicyMutations(
                require_disarmed=self._safe_bool("PX4_PARAMETER_MUTATION_REQUIRE_DISARMED", True),
                supported_component_ids=[self._safe_int("PX4_PARAMETER_DEFAULT_COMPONENT_ID", 1)],
            ),
        )

    async def build_snapshot(self, drone: Any, *, component_id: int = 1) -> Px4ParamSnapshotResponse:
        all_params = await drone.param.get_all_params()
        float_metadata = await self._load_float_metadata(drone)

        rows = []
        rows.extend(
            self._build_rows(
                params=all_params.int_params,
                component_id=component_id,
                value_type=Px4ParamValueType.INT,
                float_metadata=float_metadata,
            )
        )
        rows.extend(
            self._build_rows(
                params=all_params.float_params,
                component_id=component_id,
                value_type=Px4ParamValueType.FLOAT,
                float_metadata=float_metadata,
            )
        )
        rows.extend(
            self._build_rows(
                params=all_params.custom_params,
                component_id=component_id,
                value_type=Px4ParamValueType.CUSTOM,
                float_metadata=float_metadata,
            )
        )

        rows.sort(key=lambda row: row.name)

        now_ms = int(time.time() * 1000)
        stale_after_ms = int(self._safe_float("PX4_PARAMETER_SNAPSHOT_MAX_AGE_SEC", 60.0) * 1000)
        snapshot = Px4ParamSnapshotSummary(
            snapshot_id=f"px4-{self.hw_id}-{uuid.uuid4().hex[:12]}",
            hw_id=self.hw_id,
            component_id=component_id,
            px4_docs_version=self._safe_docs_version(),
            total_params=len(rows),
            created_at=now_ms,
            stale_after_ms=stale_after_ms,
        )
        return Px4ParamSnapshotResponse(snapshot=snapshot, rows=rows)

    async def get_param_value(
        self,
        drone: Any,
        name: str,
        *,
        component_id: int = 1,
    ) -> Px4ParamValueResponse:
        normalized_name = self._normalize_name(name)
        value, value_type = await self._read_param_auto(drone, normalized_name)
        metadata_sources = [Px4ParamMetadataSource.VEHICLE, Px4ParamMetadataSource.PX4_DOCS]
        row = Px4ParamRow(
            component_id=component_id,
            name=normalized_name,
            value_type=value_type,
            value=value,
            docs_url=self._build_docs_url(normalized_name),
            metadata_sources=metadata_sources,
        )
        return Px4ParamValueResponse(row=row, timestamp=int(time.time() * 1000))

    async def set_param_value(
        self,
        drone: Any,
        name: str,
        request: Px4ParamSetRequest,
    ) -> Px4ParamSetResponse:
        normalized_name = self._normalize_name(name)
        await self._write_param(drone, normalized_name, request.value_type, request.value)

        actual_value: Optional[int | float | str] = None
        verified = False
        if request.verify_readback:
            actual_value = await self._read_param_exact(drone, normalized_name, request.value_type)
            verified = self._values_match(request.value_type, request.value, actual_value)

        return Px4ParamSetResponse(
            applied=True,
            verified=verified if request.verify_readback else False,
            component_id=request.component_id,
            name=normalized_name,
            value_type=request.value_type,
            requested_value=request.value,
            actual_value=actual_value,
            timestamp=int(time.time() * 1000),
        )

    async def apply_patch(
        self,
        drone: Any,
        request: Px4ParamPatchApplyRequest,
    ) -> Px4ParamPatchApplyResponse:
        results = []
        applied_count = 0
        failed_count = 0
        verified_count = 0

        for entry in request.entries:
            try:
                response = await self.set_param_value(
                    drone,
                    entry.name,
                    Px4ParamSetRequest(
                        component_id=entry.component_id,
                        value_type=entry.value_type,
                        value=entry.value,
                        verify_readback=request.verify_readback,
                    ),
                )
                applied_count += 1
                if response.verified:
                    verified_count += 1
                results.append(
                    Px4ParamPatchResult(
                        name=response.name,
                        value_type=response.value_type,
                        requested_value=response.requested_value,
                        applied=True,
                        verified=response.verified,
                        actual_value=response.actual_value,
                    )
                )
            except Exception as exc:
                failed_count += 1
                results.append(
                    Px4ParamPatchResult(
                        name=entry.name,
                        value_type=entry.value_type,
                        requested_value=entry.value,
                        applied=False,
                        verified=False,
                        error=str(exc),
                    )
                )

        return Px4ParamPatchApplyResponse(
            source=request.source,
            applied_count=applied_count,
            failed_count=failed_count,
            verified_count=verified_count,
            results=results,
            timestamp=int(time.time() * 1000),
        )

    async def _read_param_auto(self, drone: Any, name: str) -> tuple[int | float | str, Px4ParamValueType]:
        for value_type in (Px4ParamValueType.INT, Px4ParamValueType.FLOAT, Px4ParamValueType.CUSTOM):
            try:
                value = await self._read_param_exact(drone, name, value_type)
                return value, value_type
            except Exception:
                continue
        raise ValueError(f"Unable to read PX4 parameter {name}")

    async def _read_param_exact(
        self,
        drone: Any,
        name: str,
        value_type: Px4ParamValueType,
    ) -> int | float | str:
        if value_type == Px4ParamValueType.INT:
            return int(await drone.param.get_param_int(name))
        if value_type == Px4ParamValueType.FLOAT:
            return float(await drone.param.get_param_float(name))
        return str(await drone.param.get_param_custom(name))

    async def _write_param(
        self,
        drone: Any,
        name: str,
        value_type: Px4ParamValueType,
        value: int | float | str,
    ) -> None:
        if value_type == Px4ParamValueType.INT:
            await drone.param.set_param_int(name, int(value))
            return
        if value_type == Px4ParamValueType.FLOAT:
            await drone.param.set_param_float(name, float(value))
            return
        await drone.param.set_param_custom(name, str(value))

    async def _load_float_metadata(self, drone: Any) -> Dict[str, Any]:
        component_information = getattr(drone, "component_information", None)
        if component_information is None:
            return {}

        try:
            float_params = await component_information.access_float_params()
        except (AttributeError, ComponentInformationError, RuntimeError):
            return {}

        return {
            self._normalize_name(item.name): item
            for item in float_params
            if getattr(item, "name", None)
        }

    def _build_rows(
        self,
        *,
        params: Iterable[Any],
        component_id: int,
        value_type: Px4ParamValueType,
        float_metadata: Dict[str, Any],
    ) -> list[Px4ParamRow]:
        rows = []
        for item in params:
            name = self._normalize_name(getattr(item, "name", ""))
            value = getattr(item, "value", None)
            metadata_sources = [Px4ParamMetadataSource.VEHICLE, Px4ParamMetadataSource.PX4_DOCS]
            float_meta = float_metadata.get(name) if value_type == Px4ParamValueType.FLOAT else None
            if float_meta is not None:
                metadata_sources.insert(1, Px4ParamMetadataSource.COMPONENT_INFORMATION)

            rows.append(
                Px4ParamRow(
                    component_id=component_id,
                    name=name,
                    value_type=value_type,
                    value=value,
                    docs_url=self._build_docs_url(name),
                    short_description=getattr(float_meta, "short_description", None),
                    long_description=getattr(float_meta, "long_description", None),
                    unit=getattr(float_meta, "unit", None),
                    decimal_places=getattr(float_meta, "decimal_places", None),
                    default_value=getattr(float_meta, "default_value", None),
                    min_value=getattr(float_meta, "min_value", None),
                    max_value=getattr(float_meta, "max_value", None),
                    metadata_sources=metadata_sources,
                )
            )
        return rows

    @staticmethod
    def _normalize_name(name: Any) -> str:
        normalized = str(name).strip().upper()
        if not normalized:
            raise ValueError("parameter name must not be blank")
        return normalized

    def _build_docs_base_url(self, version: str) -> str:
        raw_template = getattr(
            self.params,
            "PX4_PARAMETER_DOCS_BASE_TEMPLATE",
            "https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html",
        )
        if isinstance(raw_template, str) and "{version}" in raw_template and raw_template.startswith("http"):
            template = raw_template
        else:
            template = "https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html"
        return template.format(version=version)

    def _build_docs_url(self, name: str) -> str:
        version = self._safe_docs_version()
        return f"{self._build_docs_base_url(version)}#{self._normalize_name(name)}"

    def _values_match(
        self,
        value_type: Px4ParamValueType,
        requested_value: int | float | str,
        actual_value: int | float | str,
    ) -> bool:
        if value_type == Px4ParamValueType.FLOAT:
            tolerance = self._safe_float("PX4_PARAMETER_FLOAT_VERIFY_TOLERANCE", 1e-6)
            return abs(float(requested_value) - float(actual_value)) <= tolerance
        return requested_value == actual_value

    def _safe_docs_version(self) -> str:
        raw_value = getattr(self.params, "PX4_PARAMETER_DOCS_VERSION", "main")
        if isinstance(raw_value, str):
            normalized = raw_value.strip()
            if normalized:
                return normalized
        return "main"

    def _safe_float(self, attribute: str, default: float) -> float:
        raw_value = getattr(self.params, attribute, default)
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return float(default)

    def _safe_int(self, attribute: str, default: int) -> int:
        raw_value = getattr(self.params, attribute, default)
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return int(default)

    def _safe_bool(self, attribute: str, default: bool) -> bool:
        raw_value = getattr(self.params, attribute, default)
        if isinstance(raw_value, bool):
            return raw_value
        return bool(default)
