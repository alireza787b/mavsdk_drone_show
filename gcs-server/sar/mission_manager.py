# gcs-server/sar/mission_manager.py
"""
Compatibility adapter for legacy QuickScout mission-manager callers.

The old implementation kept mission state in-memory. The active storage now
flows through the durable QuickScout service/store, but some tests and older
call sites still import `get_mission_manager()`. Keep this adapter until the
subsystem is fully migrated.
"""

from __future__ import annotations

from typing import List, Optional

from sar.service import get_quickscout_service

_manager_instance: "MissionManager | None" = None


def get_mission_manager() -> "MissionManager":
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MissionManager()
    return _manager_instance


class MissionManager:
    """Compatibility wrapper over the durable QuickScout service."""

    def __init__(self):
        self._service = get_quickscout_service()

    def create_mission(self, mission_id, plans, config):
        raise NotImplementedError("Legacy create_mission direct calls are no longer supported")

    def get_status(self, mission_id: str):
        return self._service.get_status(mission_id)

    def get_plans(self, mission_id: str):
        return self._service.get_plans(mission_id)

    def get_config(self, mission_id: str):
        return self._service.get_config(mission_id)

    def start_mission(self, mission_id: str):
        return self._service.start_mission(mission_id)

    def update_drone_progress(
        self,
        mission_id: str,
        hw_id: str,
        current_waypoint_index: int,
        total_waypoints: int,
        distance_covered_m: float = 0,
        state=None,
    ) -> bool:
        return self._service.update_drone_progress(
            mission_id=mission_id,
            hw_id=hw_id,
            current_waypoint_index=current_waypoint_index,
            total_waypoints=total_waypoints,
            distance_covered_m=distance_covered_m,
            state=state,
        )

    def pause_mission(self, mission_id: str, hw_ids: Optional[List[str]] = None) -> bool:
        return self._service.pause_mission(mission_id, hw_ids)

    def resume_mission(self, mission_id: str, hw_ids: Optional[List[str]] = None) -> bool:
        return self._service.resume_mission(mission_id, hw_ids)

    def abort_mission(
        self,
        mission_id: str,
        hw_ids: Optional[List[str]] = None,
        return_behavior: str = "return_home",
    ) -> bool:
        return self._service.abort_mission(mission_id, hw_ids, return_behavior)
