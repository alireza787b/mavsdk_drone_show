# gcs-server/sar/poi_manager.py
"""
Compatibility adapter for legacy QuickScout POI-manager callers.

The active persistence path now lives in the durable QuickScout service/store.
Keep this facade while the subsystem is still migrating.
"""

from __future__ import annotations

from sar.service import get_quickscout_service

_poi_instance: "POIManager | None" = None


def get_poi_manager() -> "POIManager":
    global _poi_instance
    if _poi_instance is None:
        _poi_instance = POIManager()
    return _poi_instance


class POIManager:
    def __init__(self):
        self._service = get_quickscout_service()

    def add_poi(self, mission_id, poi):
        return self._service.add_poi(mission_id, poi)

    def get_pois(self, mission_id):
        return self._service.get_pois(mission_id)

    def update_poi(self, poi_id, updates):
        return self._service.update_poi(poi_id, updates)

    def delete_poi(self, poi_id):
        return self._service.delete_poi(poi_id)
