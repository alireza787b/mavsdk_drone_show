"""Actor-bound ULog create receipts and lookup-only recovery for the GCS."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from mds_logging.api_schemas import (
    OnboardUlogDownloadJob, OnboardUlogDownloadJobResponse, OnboardUlogDownloadRequest,
)
from src.ulog_request_receipts import UlogRequestReceiptStore, native_download_job_id, request_fingerprint
from ulog_job_handles import (
    create_ulog_job_capability, issue_ulog_job_handle, protect_ulog_job_payload,
    restore_ulog_job_capability,
)


class UlogDownloadCreateResponse(OnboardUlogDownloadJobResponse):
    request_id: str


class UlogDownloadRequestReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: Literal["accepted", "unknown"]
    job: OnboardUlogDownloadJob | None = None
    error: str | None = None
    timestamp: int


class UlogDownloadRequests:
    def __init__(self, state_dir: str, runtime_binding: str):
        self.binding = runtime_binding
        self.store = UlogRequestReceiptStore(Path(state_dir) / "ulog-download-requests.sqlite3")

    def _scope(self, owner: str, drone_id: int) -> str:
        # The immutable request fingerprint below binds the aircraft. Keeping
        # one actor/runtime key also rejects accidentally retrying its UUID
        # against a newly selected aircraft rather than creating a second job.
        return request_fingerprint({"runtime": self.binding, "owner": owner})

    @staticmethod
    def _public(stored: dict) -> UlogDownloadRequestReceipt:
        return UlogDownloadRequestReceipt(
            request_id=stored["request_id"], status=stored["status"],
            job=stored.get("job"), error=stored.get("error"), timestamp=int(time.time() * 1000),
        )

    @staticmethod
    def _creation_unknown(request_id: str, message: str, status_code: int = 409, native_detail=None):
        detail = dict(native_detail) if isinstance(native_detail, dict) else {}
        detail.setdefault("message", message)
        detail.update(request_id=request_id, creation_status="unknown")
        return HTTPException(status_code=status_code, detail=detail)

    async def _accept(self, stored: dict, payload: dict, owner: str, drone_id: int) -> dict:
        response = OnboardUlogDownloadJobResponse.model_validate(payload)
        job = response.job
        if job.hw_id != str(drone_id) or job.log_id != stored["log_id"] or not job.job_id:
            raise ValueError("Node ULog job identity does not match the selected aircraft and file")
        handle = issue_ulog_job_handle(
            drone_id=drone_id, node_job_id=job.job_id, owner_fingerprint=owner,
            expires_at_ms=job.expires_at, capability_nonce=stored["capability_nonce"],
        )
        protected = protect_ulog_job_payload(response.model_dump(mode="json"), handle=handle)
        updated = {**stored, "status": "accepted", "job": protected["job"],
                   "node_job_id": job.job_id, "error": None}
        await asyncio.to_thread(self.store.update, self._scope(owner, drone_id), stored["request_id"], updated)
        return updated

    async def create(self, owner: str, drone_id: int, log_id: int, ip: str,
                     request: OnboardUlogDownloadRequest) -> UlogDownloadCreateResponse:
        from log_proxy import (
            DroneProxyResponseError, DroneProxyUnavailableError, create_drone_ulog_download_job,
        )
        capability = create_ulog_job_capability(drone_id=drone_id, owner_fingerprint=owner)
        request_id = request.request_id
        initial = {
            "request_id": request_id, "status": "unknown", "job": None,
            "error": "Download creation is in progress; acceptance has not been confirmed",
            "drone_id": drone_id, "log_id": log_id, "ip": ip, "capability_nonce": capability.nonce,
            "node_job_id": native_download_job_id(str(drone_id), request_id, capability.access_token),
        }
        fingerprint = request_fingerprint({"drone_id": drone_id, "log_id": log_id, "pos_id": request.pos_id})
        stored, created = await asyncio.to_thread(
            self.store.claim, self._scope(owner, drone_id), request_id, fingerprint, initial,
        )
        if not created:
            if stored["status"] == "accepted":
                return UlogDownloadCreateResponse(job=stored["job"], request_id=request_id,
                                                  timestamp=int(time.time() * 1000))
            raise self._creation_unknown(request_id, stored["error"])
        try:
            payload = await create_drone_ulog_download_job(
                ip, log_id, pos_id=request.pos_id, access_token=capability.access_token, request_id=request_id,
            )
            stored = await self._accept(stored, payload, owner, drone_id)
        except (DroneProxyUnavailableError, DroneProxyResponseError, ValueError) as exc:
            detail = getattr(exc, "detail", str(exc))
            stored["error"] = str(detail)[:2048] or "Native acceptance could not be confirmed; recover this request, do not resubmit"
            await asyncio.to_thread(self.store.update, self._scope(owner, drone_id), request_id, stored)
            status = getattr(exc, "status_code", 502)
            raise self._creation_unknown(request_id, stored["error"], status, detail) from exc
        return UlogDownloadCreateResponse(job=stored["job"], request_id=request_id,
                                          timestamp=int(time.time() * 1000))

    async def lookup(self, owner: str, drone_id: int, request_id: str, ip: str | None) -> UlogDownloadRequestReceipt | None:
        from log_proxy import DroneProxyResponseError, DroneProxyUnavailableError, fetch_drone_ulog_download_job

        stored = await asyncio.to_thread(self.store.get, self._scope(owner, drone_id), request_id)
        if stored is None or stored["drone_id"] != drone_id:
            return None
        if stored["status"] == "accepted":
            return self._public(stored)
        if ip is None or stored["ip"] != ip:
            return self._public({**stored, "error": "Aircraft endpoint is unavailable or changed; creation has not been replayed"})
        capability = restore_ulog_job_capability(
            nonce=stored["capability_nonce"], drone_id=drone_id, owner_fingerprint=owner,
        )
        try:
            payload = await fetch_drone_ulog_download_job(ip, stored["node_job_id"], access_token=capability.access_token)
            raw_job = payload.get("job") if isinstance(payload, dict) else None
            if not isinstance(raw_job, dict) or raw_job.get("job_id") != stored["node_job_id"]:
                raise ValueError("Node lookup returned a different ULog job identity")
            stored = await self._accept(stored, payload, owner, drone_id)
        except (DroneProxyUnavailableError, DroneProxyResponseError, ValueError) as exc:
            stored["error"] = (
                "Native job is unavailable or creation remains unconfirmed; no new download was submitted: " + str(getattr(exc, "detail", exc))
            )[:2048]
        return self._public(stored)


def get_ulog_download_requests() -> UlogDownloadRequests:
    from src.params import Params

    binding = request_fingerprint({
        "mode": str(Params.runtime_mode), "gcs_port": Params.gcs_api_port,
        "repository": str(Path(__file__).resolve().parents[1]),
    })
    return UlogDownloadRequests(Params.GCS_COMMAND_STATE_DIR, binding)
