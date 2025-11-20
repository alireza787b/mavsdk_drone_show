#!/usr/bin/env python3
"""
Mission templates for VTOL Performance Analyzer v4.1

Pre-defined mission profiles for common use cases.
Users can load these as starting points for their own missions.
"""

MISSION_TEMPLATES = {
    "example_delivery": {
        "name": "Example: Delivery Mission",
        "description": "Round-trip delivery mission with hover phases for pickup/dropoff",
        "segments": [
            {"type": "hover", "duration_s": 60, "label": "Takeoff"},
            {"type": "transition_forward", "label": "Enter cruise mode"},
            {"type": "cruise", "duration_s": 600, "speed_ms": 15.0, "label": "Travel to delivery site (9 km)"},
            {"type": "transition_back", "label": "Enter hover mode"},
            {"type": "hover", "duration_s": 120, "label": "Package delivery"},
            {"type": "transition_forward", "label": "Enter cruise mode"},
            {"type": "cruise", "duration_s": 600, "speed_ms": 15.0, "label": "Return trip (9 km)"},
            {"type": "transition_back", "label": "Enter hover mode"},
            {"type": "hover", "duration_s": 60, "label": "Landing"},
        ],
        "estimated_time_min": 25,
        "estimated_distance_km": 18,
    },

    "survey_mission": {
        "name": "Survey/Inspection Mission",
        "description": "Multiple hover points for inspection or surveying",
        "segments": [
            {"type": "hover", "duration_s": 60, "label": "Takeoff"},
            {"type": "transition_forward", "label": "Cruise to site 1"},
            {"type": "cruise", "duration_s": 300, "speed_ms": 12.0, "label": "Travel (3.6 km)"},
            {"type": "transition_back", "label": "Hover at site 1"},
            {"type": "hover", "duration_s": 300, "label": "Survey point 1"},
            {"type": "transition_forward", "label": "Move to site 2"},
            {"type": "cruise", "duration_s": 180, "speed_ms": 12.0, "label": "Travel (2.2 km)"},
            {"type": "transition_back", "label": "Hover at site 2"},
            {"type": "hover", "duration_s": 300, "label": "Survey point 2"},
            {"type": "transition_forward", "label": "Return"},
            {"type": "cruise", "duration_s": 480, "speed_ms": 12.0, "label": "Return (5.8 km)"},
            {"type": "transition_back", "label": "Prepare landing"},
            {"type": "hover", "duration_s": 60, "label": "Landing"},
        ],
        "estimated_time_min": 30,
        "estimated_distance_km": 11.6,
    },

    "endurance_test": {
        "name": "Endurance Test",
        "description": "Maximum flight time test with minimal transitions",
        "segments": [
            {"type": "hover", "duration_s": 60, "label": "Takeoff"},
            {"type": "transition_forward", "label": "Enter cruise"},
            {"type": "cruise", "duration_s": 3000, "speed_ms": 13.5, "label": "Cruise at optimal efficiency"},
            {"type": "transition_back", "label": "Prepare landing"},
            {"type": "hover", "duration_s": 60, "label": "Landing"},
        ],
        "estimated_time_min": 53,
        "estimated_distance_km": 40.5,
    },

    "range_test": {
        "name": "Maximum Range Test",
        "description": "Out-and-back for maximum distance",
        "segments": [
            {"type": "hover", "duration_s": 60, "label": "Takeoff"},
            {"type": "transition_forward", "label": "Enter cruise"},
            {"type": "cruise", "duration_s": 1200, "speed_ms": 13.5, "label": "Outbound leg (16.2 km)"},
            {"type": "transition_back", "label": "Turn around"},
            {"type": "hover", "duration_s": 30, "label": "Waypoint hover"},
            {"type": "transition_forward", "label": "Return cruise"},
            {"type": "cruise", "duration_s": 1200, "speed_ms": 13.5, "label": "Return leg (16.2 km)"},
            {"type": "transition_back", "label": "Prepare landing"},
            {"type": "hover", "duration_s": 60, "label": "Landing"},
        ],
        "estimated_time_min": 42,
        "estimated_distance_km": 32.4,
    },

    "quick_test": {
        "name": "Quick Flight Test",
        "description": "Short flight for testing and validation",
        "segments": [
            {"type": "hover", "duration_s": 30, "label": "Takeoff"},
            {"type": "transition_forward", "label": "Enter cruise"},
            {"type": "cruise", "duration_s": 180, "speed_ms": 15.0, "label": "Short cruise (2.7 km)"},
            {"type": "transition_back", "label": "Return hover"},
            {"type": "hover", "duration_s": 120, "label": "Hover test"},
            {"type": "hover", "duration_s": 30, "label": "Landing"},
        ],
        "estimated_time_min": 6,
        "estimated_distance_km": 2.7,
    },
}

DEFAULT_MISSION = "example_delivery"

def get_mission_template(template_id):
    """Get a mission template by ID"""
    return MISSION_TEMPLATES.get(template_id)

def list_mission_templates():
    """List all available mission templates"""
    return list(MISSION_TEMPLATES.keys())

def get_template_names():
    """Get list of template names for UI display"""
    return [(tid, MISSION_TEMPLATES[tid]["name"]) for tid in MISSION_TEMPLATES]
