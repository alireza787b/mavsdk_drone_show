"""Bounded, source-labelled PX4 observations for an operator's retained flight log."""

from __future__ import annotations

import math

import numpy as np

from src.px4_flight_modes import describe_px4_custom_mode

TOPICS = ("action_request", "failsafe_flags", "telemetry_status")
# PX4 VehicleStatus.nav_state and ActionRequest.source enums, independent of MAVLink custom_mode.
_NAV_NAMES = {0: "Manual", 1: "Altitude", 2: "Position", 3: "Mission", 4: "Hold", 5: "Return",
              10: "Acro", 12: "Descend", 13: "Termination", 14: "Offboard", 15: "Stabilized",
              17: "Takeoff", 18: "Land", 19: "Follow target", 20: "Precision land", 21: "Orbit"}
_RC_SOURCES = {0: "Stick gesture", 1: "RC switch", 2: "RC button", 3: "RC mode slot"}
_COMMANDS = {20: "Return", 21: "Land", 22: "Takeoff", 176: "Set mode", 400: "Arm/disarm"}
_ACK_RESULTS = {0: "accepted", 1: "temporarily rejected", 2: "denied", 3: "unsupported",
                4: "failed", 5: "in progress", 6: "cancelled"}
_MAX_INSTANCES = 8


def _number(data, field, i):
    column = data.get(field)
    if column is None or i >= len(column):
        return None
    try:
        value = float(column[i])
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return int(value) if value.is_integer() else round(value, 3)


def _indices(data, topic, start):
    times = np.asarray(data.get("timestamp", []))
    indices = np.flatnonzero(times >= start)
    if not len(indices):
        return indices
    if topic == "telemetry_status":
        # Equally spaced sample windows span the recording, including the last sample.
        buckets = (times[indices] - start) // 5_000_000
        return indices[np.unique(np.r_[0, np.flatnonzero(buckets[1:] != buckets[:-1]), len(indices) - 1])]
    changed = {"vehicle_status": "nav_state", "failsafe_flags": "offboard_control_signal_lost"}.get(topic)
    if changed:
        column = np.asarray(data.get(changed, []))
        indices = indices[indices < len(column)]
        values = column[indices]
        return indices[np.r_[True, values[1:] != values[:-1]]] if len(indices) else indices
    if topic == "action_request":
        field, wanted = "action", (5,)
    else:
        field, wanted = "command", tuple(_COMMANDS)
    values = np.asarray(data.get(field, []))
    indices = indices[indices < len(values)]
    return indices[np.isin(values[indices], wanted)]


def _telemetry(data, i, previous):
    metrics = {}
    for field, name in (("rx_rate_avg", "rx_bytes_per_s"), ("tx_rate_avg", "tx_bytes_per_s")):
        value = _number(data, field, i)
        if value is not None:
            metrics[name] = value
    if previous is not None:
        metrics["interval_ms"] = (int(data["timestamp"][i]) - int(data["timestamp"][previous])) // 1000
        for field in ("rx_message_count", "rx_message_lost_count", "rx_parse_errors",
                      "rx_buffer_overruns", "rx_packet_drop_count", "tx_buffer_overruns"):
            if field not in data or len(data[field]) <= i:
                continue
            window = np.asarray(data[field][previous:i + 1])
            if np.any(window[1:] < window[:-1]):
                metrics["counter_reset"] = True
                continue
            metrics[field + "_delta"] = int(window[-1]) - int(window[0])
    return "MAVLink", "Link sample", metrics


def _event(topic, data, i, previous):
    def value(field):
        return _number(data, field, i)

    if topic == "telemetry_status":
        return _telemetry(data, i, previous)
    if topic == "vehicle_status":
        nav = value("nav_state")
        return "PX4 mode", _NAV_NAMES.get(nav, f"Mode {nav}"), {"nav_state": nav}
    if topic == "failsafe_flags":
        lost = bool(value("offboard_control_signal_lost"))
        return "PX4 Offboard signal", "Unavailable" if lost else "Available", {"signal_lost": lost}
    if topic == "action_request":
        mode, source = value("mode"), value("source")
        label = f"{_RC_SOURCES.get(source, f'Source {source}')} requested {_NAV_NAMES.get(mode, f'mode {mode}')}"
        return "PX4 action", label, {"nav_state": mode, "action_source": source}
    command = value("command")
    name = _COMMANDS[command]
    if topic == "vehicle_command_ack":
        result = value("result")
        return "PX4 command ACK", f"{name} · {_ACK_RESULTS.get(result, f'result {result}')}", {
            "command": command, "result": result,
            "target_system": value("target_system"), "target_component": value("target_component"),
        }
    if command == 176:
        main, sub = value("param2"), value("param3")
        if isinstance(main, int) and isinstance(sub, int) and 0 < main <= 255 and 0 <= sub <= 255:
            name = describe_px4_custom_mode(main << 16 | sub << 24)
    return "PX4 command", f"{name} requested", {
        "command": command, "source_system": value("source_system"), "source_component": value("source_component"),
        "from_external": value("from_external"),
    }


def build_ulog_timeline(ulog, envelope):
    start = int(ulog.start_timestamp)
    boot = (getattr(ulog, "msg_info_dict", {}) or {}).get("boot_time_utc_us")
    # Without a plausible onboard UTC anchor retain only boot-relative timing.
    anchored = isinstance(boot, int) and 946684800000000 <= boot < 4102444800000000
    end = envelope.last_data_timestamp_us
    rows, truncated = [], False
    topics = {"vehicle_status", "vehicle_command", "vehicle_command_ack", *TOPICS}
    for dataset in ulog.data_list:
        if dataset.name not in topics:
            continue
        instance = int(getattr(dataset, "multi_id", 0))
        if not 0 <= instance < _MAX_INSTANCES:
            truncated = True
            continue
        indices = _indices(dataset.data, dataset.name, start)
        limit = 40 if dataset.name == "telemetry_status" else 96
        if len(indices) > limit:
            indices = indices[np.linspace(0, len(indices) - 1, limit, dtype=int)]
            truncated = True
        previous = None
        for index in indices:
            i = int(index)
            ts = int(dataset.data["timestamp"][i])
            source, label, metrics = _event(dataset.name, dataset.data, i, previous)
            if dataset.name == "vehicle_status":
                # Row time is the report time. Commander may have activated the mode earlier.
                entered = _number(dataset.data, "nav_state_timestamp", i)
                if isinstance(entered, int) and 0 < entered <= ts:
                    metrics["mode_activated_boot_us"] = entered
                    if anchored:
                        metrics["mode_activated_utc_ms"] = (boot + entered) // 1000
            rows.append({"kind": "sample" if dataset.name == "telemetry_status" else "event",
                         "elapsed_ms": (ts - start) // 1000, "utc_ms": (boot + ts) // 1000 if anchored else None,
                         "instance": instance, "source": source, "label": label,
                         "metrics": {k: v for k, v in metrics.items() if v is not None}})
            previous = i
    rows.sort(key=lambda event: event["elapsed_ms"])
    if len(rows) > 256:
        indices = np.linspace(0, len(rows) - 1, 256, dtype=int)
        rows = [rows[i] for i in indices]
        truncated = True
    return {"start_utc_ms": (boot + start) // 1000 if anchored else None,
            "end_utc_ms": (boot + end) // 1000 if anchored and envelope.complete and end is not None and end >= start else None,
            "events": rows, "truncated": truncated}
