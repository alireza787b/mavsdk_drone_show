"""Node session context and bounded role acknowledgements; no flight policy."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import aiohttp

from src.gcs_auth_client import gcs_auth_headers
from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER
from src.smart_swarm_contract import SmartSwarmSession


class SwarmSessionRuntime:
    def __init__(self, params, logger):
        self.params, self.logger = params, logger
        raw_fd = os.environ.pop("MDS_SWARM_CONTEXT_FD", None)
        context = {}
        if raw_fd is not None:
            with os.fdopen(int(raw_fd), "r") as stream:
                context = json.load(stream)
        self.command_id = context.get("command_id") or str(uuid.uuid4())
        self.capability = context.get("capability")
        snapshot = context.get("session")
        self.snapshot = SmartSwarmSession.model_validate(snapshot) if snapshot else None
        self.sequence = 0
        self.phase = "ready"
        self.detail = ""
        self.last_report_error = None

    async def report(self, hw_id, follow, revision):
        if self.snapshot is None:
            return {"engage": True, "abort": False}  # legacy/manual diagnostic runner
        self.sequence += 1
        payload = {"command_id": self.command_id, "hw_id": str(hw_id),
                   "sequence": self.sequence, "role": "leader" if int(follow) == 0 else "follower",
                   "follow": str(follow), "revision": revision,
                   "phase": self.phase, "detail": self.detail[:500]}
        url = f"http://{self.params.GCS_IP}:{self.params.gcs_api_port}/api/v1/command-reports/swarm-runtime"
        headers = gcs_auth_headers({GCS_COMMAND_REPORT_CAPABILITY_HEADER: self.capability or ""})
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as client:
                async with client.post(url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    result = await response.json()
            if self.last_report_error:
                self.logger.info("Swarm session reporting recovered")
            self.last_report_error = None
            return result
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            name = type(exc).__name__
            if name != self.last_report_error:
                self.logger.warning("Swarm session reporting unavailable (%s); local flight policy unchanged", name)
            self.last_report_error = name
            return {"engage": False, "abort": False}

    async def wait_for_cluster(self, hw_id, follow, revision):
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            result = await self.report(hw_id, follow, revision)
            if result.get("abort"):
                raise RuntimeError(result.get("reason", "Smart Swarm startup cancelled"))
            if result.get("engage"):
                return
            await asyncio.sleep(0.5)
        raise TimeoutError("Required swarm role did not acknowledge startup; no follower control engaged")
