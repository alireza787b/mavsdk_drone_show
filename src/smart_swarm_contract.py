"""Shared Smart Swarm topology/session contract, independent of UI and flight I/O."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SwarmMember(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    hw_id: str
    follow: str
    offset_x: float = 0
    offset_y: float = 0
    offset_z: float = 0
    frame: Literal["ned", "body"] = "ned"


def normalize_topology(assignments: list[dict]) -> list[dict]:
    members = [SwarmMember(**{
        "hw_id": str(int(a["hw_id"])), "follow": str(int(a.get("follow", 0))),
        **{k: a.get(k, default) for k, default in (
            ("offset_x", 0), ("offset_y", 0), ("offset_z", 0), ("frame", "ned"))},
    }).model_dump() for a in assignments]
    by_id = {a["hw_id"]: a for a in members}
    if len(by_id) != len(members) or any(int(k) <= 0 for k in by_id):
        raise ValueError("Swarm hardware IDs must be unique and positive")
    for member in members:
        visited = set()
        current = member["hw_id"]
        while current != "0":
            if current in visited or current not in by_id:
                raise ValueError("Swarm follow chain contains a loop or missing leader")
            visited.add(current)
            current = by_id[current]["follow"]
    return sorted(members, key=lambda a: int(a["hw_id"]))


def topology_revision(assignments: list[dict]) -> str:
    data = json.dumps(normalize_topology(assignments), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def resolve_clusters(assignments: list[dict]) -> list[dict]:
    members = normalize_topology(assignments)
    by_id = {a["hw_id"]: a for a in members}
    groups = {}
    for member in members:
        root = member["hw_id"]
        while by_id[root]["follow"] != "0":
            root = by_id[root]["follow"]
        groups.setdefault(root, []).append(member)
    return [{"cluster_id": root, "members": group} for root, group in groups.items()]


def dependency_closed_targets(members: list[dict], excluded: list[str]) -> list[str]:
    """Never start a descendant without its saved upstream dependencies."""
    omitted = set(excluded)
    changed = True
    while changed:
        before = set(omitted)
        omitted.update(m["hw_id"] for m in members if m["follow"] in omitted)
        changed = omitted != before
    return [m["hw_id"] for m in members if m["hw_id"] not in omitted]


class SmartSwarmSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    assignments: list[SwarmMember]
    expected_hw_ids: list[str] = Field(min_length=1)
    excluded_hw_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_snapshot(self):
        assignments = [m.model_dump() for m in self.assignments]
        if topology_revision(assignments) != self.revision:
            raise ValueError("Smart Swarm configuration revision does not match snapshot")
        ids = {m.hw_id for m in self.assignments}
        expected = set(self.expected_hw_ids)
        if len(expected) != len(self.expected_hw_ids) or not expected <= ids:
            raise ValueError("Invalid Smart Swarm session targets")
        if expected & set(self.excluded_hw_ids):
            raise ValueError("Included and excluded Smart Swarm targets overlap")
        for m in self.assignments:
            if m.hw_id in expected and m.follow != "0" and m.follow not in expected:
                raise ValueError(f"Follower {m.hw_id} requires leader {m.follow}")
        return self


class SwarmStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cluster_id: str | None = None
    revision: str
    excluded_hw_ids: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)


class SwarmRuntimeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    hw_id: str
    sequence: int = Field(ge=0)
    role: Literal["leader", "follower"]
    follow: str
    revision: str
    phase: Literal["ready", "active", "holding", "takeover", "stopped", "failed"]
    detail: str = Field(default="", max_length=500)


class SwarmRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    hw_id: str = Field(pattern=r"^[1-9][0-9]*$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    follow: int = Field(ge=0)
