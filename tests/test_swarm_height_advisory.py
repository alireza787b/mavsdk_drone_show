from swarm_height_advisory import build_height_advisory, update_observed_rtk_fix

NOW = 1_900_000_000_000


def test_height_difference_is_scoped_to_datum_and_planned_offsets():
    members = [
        {"hw_id": "3", "follow": "2", "offset_z": 1, "available": True},
        {"hw_id": "1", "follow": "0", "offset_z": 0, "available": True},
        {"hw_id": "2", "follow": "1", "offset_z": 3, "available": True},
    ]
    states = {hw: {"position_alt": alt, "global_position_valid": True,
                   "global_position_timestamp_ms": NOW, "landed_state": 2, "landed_state_timestamp_ms": NOW}
              for hw, alt in [("1", 200), ("2", 203), ("3", 204)]}
    matched = build_height_advisory(members, states, NOW)
    assert (matched["comparison"], matched["spread_m"], matched["comparison_spread_m"], matched["active"]) == ("planned", 4, 0, False)
    states["2"]["landed_state"] = 1
    grounded = build_height_advisory(members, states, NOW)
    assert grounded["comparison"] == "readings" and grounded["active"]
    states["2"]["global_position_timestamp_ms"] = NOW + 100
    states["3"]["global_position_timestamp_ms"] = NOW - 3001
    missing = build_height_advisory(members, states, NOW)
    assert missing["valid_count"] == 1 and missing["expected_count"] == 3
    assert missing["comparison_spread_m"] is None and not missing["active"]


def test_rtk_duration_requires_advancing_source_time_and_breaks_after_gap():
    def sample(stamp, previous, *, fix=6, available=True, endpoint="peer"):
        row = {"gps_raw_timestamp_ms": stamp, "gps_fix_type": fix, "telemetry_available": available, "ip": endpoint}
        update_observed_rtk_fix(row, previous, stamp)
        return row
    first = sample(NOW, {})
    assert first["rtk_fixed_observed_since_ms"] is None
    assert sample(NOW, first)["rtk_fixed_observed_since_ms"] is None
    fixed = sample(NOW + 200, first)
    assert fixed["rtk_fixed_observed_since_ms"] == NOW
    for broken in [sample(NOW + 200, fixed, fix=4), sample(NOW + 200, fixed, available=False)]:
        assert sample(NOW + 300, broken)["rtk_fixed_observed_since_ms"] is None
    assert sample(NOW + 5000, fixed)["rtk_fixed_observed_since_ms"] is None
    assert sample(NOW + 300, fixed, endpoint="replacement")["rtk_fixed_observed_since_ms"] is None
    assert sample(NOW - 100, fixed)["rtk_fixed_observed_since_ms"] is None
