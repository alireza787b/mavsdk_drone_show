"""Read-only comparison of native PX4 height samples on the same MSL datum."""
import math

from src.telemetry_display import ALTITUDE_STALE_AFTER_MS

HEIGHT_REVIEW_THRESHOLD_M = 1.0


def _timestamp(record, key):
    value = record.get(key)
    return int(value) if type(value) in (int, float) and math.isfinite(value) and value > 0 else None


def _current(timestamp, now_ms):
    return timestamp is not None and 0 <= now_ms - timestamp <= ALTITUDE_STALE_AFTER_MS


def update_observed_rtk_fix(record, previous, now_ms):
    """Count only an uninterrupted series of advancing, observed fixed samples."""
    stamp = _timestamp(record, "gps_raw_timestamp_ms")
    record["rtk_fixed_observed_since_ms"] = None
    record.pop("_rtk_first_observed_ms", None)
    if (not record.get("telemetry_available") or record.get("gps_fix_type") != 6
            or not _current(stamp, now_ms)):
        return
    prior = _timestamp(previous, "gps_raw_timestamp_ms")
    first = _timestamp(previous, "_rtk_first_observed_ms")
    if (first and prior and first <= prior and previous.get("ip") == record.get("ip")
            and 0 <= stamp - prior <= ALTITUDE_STALE_AFTER_MS):
        record["_rtk_first_observed_ms"] = first
        if stamp > first:
            record["rtk_fixed_observed_since_ms"] = first
    else:
        record["_rtk_first_observed_ms"] = stamp


def build_height_advisory(members, telemetry, now_ms):
    """Use saved relative heights only when every compared aircraft reports in-air."""
    by_id = {row["hw_id"]: row for row in members}
    planned = {"0": 0.0}
    samples = []
    valid = []
    for hw_id, member in by_id.items():
        # Memoize ancestors, including those listed after their followers.
        path = []
        parent = hw_id
        while parent not in planned:
            path.append(parent)
            parent = by_id[parent]["follow"]
        for child in reversed(path):
            link = by_id[child]
            planned[child] = planned[link["follow"]] + (link["offset_z"] if link["follow"] != "0" else 0.0)

        row = telemetry.get(hw_id, {})
        height = row.get("position_alt")
        if (row.get("global_position_valid") is not True or type(height) not in (int, float)
                or not math.isfinite(height) or not member["available"]):
            height = None
        gps_fix = row.get("gps_fix_type") if member["available"] else None
        sample = {
            "hw_id": hw_id, "planned_height_m": planned[hw_id],
            "altitude_m": height, "altitude_timestamp_ms": _timestamp(row, "global_position_timestamp_ms"),
            "gps_fix_type": gps_fix, "gps_timestamp_ms": _timestamp(row, "gps_raw_timestamp_ms"),
            "rtk_fixed_observed_since_ms": row.get("rtk_fixed_observed_since_ms") if gps_fix == 6 else None,
            "landed_state": row.get("landed_state") if member["available"] else None,
            "landed_timestamp_ms": _timestamp(row, "landed_state_timestamp_ms"),
        }
        samples.append(sample)
        if height is not None and _current(sample["altitude_timestamp_ms"], now_ms):
            valid.append(sample)

    airborne = len(valid) == len(samples) and bool(samples) and all(s["landed_state"] == 2 and _current(s["landed_timestamp_ms"], now_ms)
                                     for s in samples)
    heights = [s["altitude_m"] for s in valid]
    compared = [s["altitude_m"] - s["planned_height_m"] for s in valid] if airborne else heights
    spread = max(compared) - min(compared) if len(compared) >= 2 else None
    return {
        "active": spread is not None and spread > HEIGHT_REVIEW_THRESHOLD_M,
        "comparison": "planned" if airborne else "readings",
        "comparison_spread_m": round(spread, 2) if spread is not None else None,
        "spread_m": round(max(heights) - min(heights), 2) if len(heights) >= 2 else None,
        "threshold_m": HEIGHT_REVIEW_THRESHOLD_M, "max_age_ms": ALTITUDE_STALE_AFTER_MS,
        "reference": "fused_global_msl", "observed_at_ms": now_ms,
        "valid_count": len(valid), "expected_count": len(samples), "samples": samples,
        "members": [{"hw_id": s["hw_id"], "altitude_m": round(s["altitude_m"], 2)} for s in valid],
    }
