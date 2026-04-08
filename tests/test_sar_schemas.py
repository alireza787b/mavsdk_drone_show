"""
Tests for QuickScout SAR Pydantic schemas.
Validates all constraints (min/max, patterns, required fields).
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gcs-server'))

from sar.schemas import (
    SearchAreaPoint, SearchArea, SurveyConfig, QuickScoutMissionRequest,
    CoverageWaypoint, DroneCoveragePlan, CoveragePlanResponse,
    POI, DroneSurveyState, MissionStatus, DroneProgressReport,
    ReturnBehavior, SurveyState, POIType, POIPriority, QuickScoutMissionTemplate,
)
from pydantic import ValidationError


class TestSearchAreaPoint:
    def test_valid_point(self):
        p = SearchAreaPoint(lat=40.0, lng=-74.0)
        assert p.lat == 40.0
        assert p.lng == -74.0

    def test_invalid_lat(self):
        with pytest.raises(ValidationError):
            SearchAreaPoint(lat=91.0, lng=0)

    def test_invalid_lng(self):
        with pytest.raises(ValidationError):
            SearchAreaPoint(lat=0, lng=181.0)


class TestSearchArea:
    def test_valid_polygon(self):
        points = [
            SearchAreaPoint(lat=0, lng=0),
            SearchAreaPoint(lat=1, lng=0),
            SearchAreaPoint(lat=1, lng=1),
        ]
        area = SearchArea(points=points)
        assert len(area.points) == 3
        assert area.type == "polygon"

    def test_too_few_points(self):
        with pytest.raises(ValidationError):
            SearchArea(points=[
                SearchAreaPoint(lat=0, lng=0),
                SearchAreaPoint(lat=1, lng=0),
            ])

    def test_valid_point_search_area(self):
        area = SearchArea(
            type="point",
            center=SearchAreaPoint(lat=47.0, lng=8.0),
            radius_m=120,
        )

        assert area.type == "point"
        assert area.center.lat == 47.0
        assert area.radius_m == 120

    def test_valid_line_search_area(self):
        area = SearchArea(
            type="line",
            path=[
                SearchAreaPoint(lat=47.0, lng=8.0),
                SearchAreaPoint(lat=47.001, lng=8.002),
            ],
            corridor_width_m=80,
        )

        assert area.type == "line"
        assert len(area.path) == 2
        assert area.corridor_width_m == 80

    def test_valid_line_search_area(self):
        area = SearchArea(
            type="line",
            path=[
                SearchAreaPoint(lat=47.0, lng=8.0),
                SearchAreaPoint(lat=47.002, lng=8.004),
            ],
            corridor_width_m=90,
        )

        assert area.type == "line"
        assert len(area.path) == 2
        assert area.corridor_width_m == 90


class TestSurveyConfig:
    def test_defaults(self):
        cfg = SurveyConfig()
        assert cfg.sweep_width_m == 30.0
        assert cfg.overlap_percent == 10.0
        assert cfg.cruise_altitude_msl == 50.0
        assert cfg.survey_altitude_agl == 40.0
        assert cfg.use_terrain_following is True

    def test_invalid_sweep_width(self):
        with pytest.raises(ValidationError):
            SurveyConfig(sweep_width_m=-1)

    def test_invalid_overlap(self):
        with pytest.raises(ValidationError):
            SurveyConfig(overlap_percent=60)  # max is 50

    def test_invalid_speed(self):
        with pytest.raises(ValidationError):
            SurveyConfig(survey_speed_ms=0)  # must be > 0


class TestQuickScoutMissionRequest:
    def test_valid_request(self):
        req = QuickScoutMissionRequest(
            search_area=SearchArea(points=[
                SearchAreaPoint(lat=0, lng=0),
                SearchAreaPoint(lat=1, lng=0),
                SearchAreaPoint(lat=1, lng=1),
            ]),
            pos_ids=[0, 1],
            mission_label="Harbor sweep",
            mission_profile="rapid_search",
            mission_brief="Search quay perimeter",
        )
        assert req.return_behavior == ReturnBehavior.RETURN_HOME
        assert len(req.pos_ids) == 2
        assert req.mission_label == "Harbor sweep"

    def test_default_config(self):
        req = QuickScoutMissionRequest(
            search_area=SearchArea(points=[
                SearchAreaPoint(lat=0, lng=0),
                SearchAreaPoint(lat=1, lng=0),
                SearchAreaPoint(lat=1, lng=1),
            ]),
        )
        assert req.survey_config.algorithm == "boustrophedon"

    def test_last_known_point_template(self):
        req = QuickScoutMissionRequest(
            mission_template=QuickScoutMissionTemplate.LAST_KNOWN_POINT,
            search_area=SearchArea(
                type="point",
                center=SearchAreaPoint(lat=47.0, lng=8.0),
                radius_m=120,
            ),
        )
        assert req.mission_template == QuickScoutMissionTemplate.LAST_KNOWN_POINT

    def test_corridor_search_template(self):
        req = QuickScoutMissionRequest(
            mission_template=QuickScoutMissionTemplate.CORRIDOR_SEARCH,
            search_area=SearchArea(
                type="line",
                path=[
                    SearchAreaPoint(lat=47.0, lng=8.0),
                    SearchAreaPoint(lat=47.001, lng=8.002),
                ],
                corridor_width_m=80,
            ),
        )
        assert req.mission_template == QuickScoutMissionTemplate.CORRIDOR_SEARCH

    def test_corridor_search_template(self):
        req = QuickScoutMissionRequest(
            mission_template=QuickScoutMissionTemplate.CORRIDOR_SEARCH,
            search_area=SearchArea(
                type="line",
                path=[
                    SearchAreaPoint(lat=47.0, lng=8.0),
                    SearchAreaPoint(lat=47.002, lng=8.004),
                ],
                corridor_width_m=90,
            ),
        )
        assert req.mission_template == QuickScoutMissionTemplate.CORRIDOR_SEARCH


class TestCoverageWaypoint:
    def test_valid_waypoint(self):
        wp = CoverageWaypoint(
            lat=40.0, lng=-74.0, alt_msl=50.0,
            is_survey_leg=True, speed_ms=5.0, sequence=0,
        )
        assert wp.lat == 40.0
        assert wp.is_survey_leg is True

    def test_invalid_speed(self):
        with pytest.raises(ValidationError):
            CoverageWaypoint(
                lat=40.0, lng=-74.0, alt_msl=50.0,
                speed_ms=0, sequence=0,
            )


class TestDroneCoveragePlan:
    def test_valid_plan(self):
        wp = CoverageWaypoint(
            lat=40.0, lng=-74.0, alt_msl=50.0,
            speed_ms=5.0, sequence=0,
        )
        plan = DroneCoveragePlan(
            hw_id="1", pos_id=0, waypoints=[wp],
            assigned_area_sq_m=1000, estimated_duration_s=60, total_distance_m=500,
        )
        assert plan.hw_id == "1"
        assert len(plan.waypoints) == 1


class TestPOI:
    def test_valid_poi(self):
        poi = POI(lat=40.0, lng=-74.0, type=POIType.PERSON, priority=POIPriority.HIGH)
        assert poi.type == POIType.PERSON
        assert poi.status == "new"

    def test_default_values(self):
        poi = POI(lat=0, lng=0)
        assert poi.type == POIType.OTHER
        assert poi.priority == POIPriority.MEDIUM


class TestDroneSurveyState:
    def test_valid_state(self):
        ds = DroneSurveyState(hw_id="1", state=SurveyState.EXECUTING, total_waypoints=100)
        assert ds.coverage_percent == 0.0

    def test_invalid_coverage(self):
        with pytest.raises(ValidationError):
            DroneSurveyState(hw_id="1", coverage_percent=101)


class TestMissionStatus:
    def test_empty_mission(self):
        ms = MissionStatus(mission_id="test-123")
        assert ms.state == SurveyState.PLANNING
        assert ms.total_coverage_percent == 0.0
        assert ms.drone_states == {}


class TestDroneProgressReport:
    def test_valid_report(self):
        rpt = DroneProgressReport(
            hw_id="1", current_waypoint_index=5, total_waypoints=20,
        )
        assert rpt.distance_covered_m == 0.0


class TestEnums:
    def test_return_behavior(self):
        assert ReturnBehavior.RETURN_HOME.value == "return_home"

    def test_survey_state(self):
        assert SurveyState.EXECUTING.value == "executing"

    def test_poi_type(self):
        assert POIType.PERSON.value == "person"
