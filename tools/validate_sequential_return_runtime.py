#!/usr/bin/env python3
"""SITL-only takeoff → Smart Swarm → timed RTL rehearsal with CSV/plot evidence."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.runtime_validation_support import ValidationApiClient, fetch_and_require_sitl_runtime, require


def run(args):
    client = ValidationApiClient(args.base_url)
    fetch_and_require_sitl_runtime(args.base_url, client=client)
    ids = args.drone_ids
    require(len(ids) == len(set(ids)), "Drone IDs must be unique")
    initial_swarm = client.get_json("/api/v1/config/swarm")
    samples = []
    started = time.time()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "base_url": args.base_url, "drone_ids": ids,
              "delay_sec": args.delay_sec, "started_at": started}

    def telemetry():
        data = client.get_json("/api/v1/fleet/telemetry")["telemetry"]
        for hw_id in ids:
            state = data.get(hw_id, {})
            samples.append({"time_s": time.time() - started, "hw_id": hw_id,
                            "altitude_m": state.get("relative_altitude_m"),
                            "flight_mode": state.get("flight_mode"), "is_armed": state.get("is_armed"),
                            "latitude": state.get("position_lat"), "longitude": state.get("position_long")})
        return data

    def wait(predicate, label, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = telemetry()
            value = predicate(state)
            if value:
                print(label, flush=True)
                return value
            time.sleep(0.5)
        raise RuntimeError(f"Timed out: {label}")

    def submit(mission, **extra):
        return client.post_json("/api/v1/commands", {
            "mission_type": mission, "trigger_time": 0, "target_drone_ids": ids,
            "idempotency_key": f"return-validation-{uuid.uuid4()}", **extra,
        })["command_id"]

    def command_complete(command_id):
        status = client.get_json(f"/api/v1/commands/{command_id}")
        if status["phase"] == "terminal":
            require(status["status"] == "completed", f"Command failed: {status.get('error_summary')}")
            return status
        return False

    return_job = None
    airborne = False
    try:
        wait(lambda states: all(states.get(i, {}).get("is_ready_to_arm") is True for i in ids), "Both ready")
        airborne = True
        report["takeoff_command_id"] = submit(10, takeoff_altitude=5)
        wait(lambda _: command_complete(report["takeoff_command_id"]), "Takeoff completed")
        wait(lambda states: all(states.get(i, {}).get("is_armed") is True
                               and float(states[i].get("relative_altitude_m") or 0) > 3 for i in ids), "Both airborne")
        report["swarm_command_id"] = submit(2)

        def roles_started(_):
            status = client.get_json(f"/api/v1/commands/{report['swarm_command_id']}")
            require(status.get("phase") != "terminal", f"Swarm start failed: {status.get('error_summary')}")
            return len((status.get("swarm_runtime") or {}).get("active_hw_ids", [])) == len(ids)

        wait(roles_started, "Both Smart Swarm roles reporting")
        # Record a brief stable interval before exercising the recovery control.
        for _ in range(10):
            telemetry()
            time.sleep(0.5)
        return_job = client.post_json("/api/v1/swarm/runtime/sequential-return", {
            "target_drone_ids": ids, "delay_sec": args.delay_sec,
            "idempotency_key": f"return-validation-{uuid.uuid4()}",
        })
        route = f"/api/v1/swarm/runtime/sequential-return/{return_job['return_id']}"

        def all_dispatched(_):
            job = client.get_json(route)
            require(job["state"] not in {"failed", "cancelled", "interrupted"}, job["message"])
            return job if job["state"] == "dispatched" else False

        report["return"] = wait(all_dispatched, "All RTL commands confirmed", timeout=120 + len(ids) * args.delay_sec)
        issued = report["return"]["commands"]
        require([c["hw_id"] for c in issued] == ids, "RTL order differs from reviewed order")
        gaps = [(b["dispatched_at_ms"] - a["dispatched_at_ms"]) / 1000 for a, b in zip(issued, issued[1:])]
        require(all(gap >= args.delay_sec - 0.01 for gap in gaps), "RTL interval was shorter than requested")
        report["dispatch_intervals_sec"] = gaps
        wait(lambda states: all(states.get(i, {}).get("is_armed") is False for i in ids), "Both landed and disarmed", timeout=180)
        airborne = False
        for command in issued:
            wait(lambda _, key=command["command_id"]: command_complete(key),
                 f"RTL completed for drone {command['hw_id']}", timeout=20)
        require(client.get_json("/api/v1/config/swarm") == initial_swarm, "Saved formation changed")
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        if airborne:
            try:
                if return_job:
                    client.post_json(f"/api/v1/swarm/runtime/sequential-return/{return_job['return_id']}/cancel", {})
                report["cleanup_land_command_id"] = submit(101)
                wait(lambda states: all(states.get(i, {}).get("is_armed") is False for i in ids), "Cleanup landed", timeout=120)
            except Exception as exc:
                report["cleanup_error"] = str(exc)
        report["finished_at"] = time.time()
        (output / "summary.json").write_text(json.dumps(report, indent=2))
        if samples:
            with (output / "telemetry.csv").open("w") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(samples[0]))
                writer.writeheader()
                writer.writerows(samples)
            plot(samples, report, output)
    return report


def plot(samples, report, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axis = plt.subplots(figsize=(11, 4.5), constrained_layout=True)
    for hw_id in report["drone_ids"]:
        values = [s for s in samples if s["hw_id"] == hw_id and s["altitude_m"] is not None]
        axis.plot([s["time_s"] for s in values], [s["altitude_m"] for s in values], label=f"Drone {hw_id}")
    for command in report.get("return", {}).get("commands", []):
        elapsed = command["dispatched_at_ms"] / 1000 - report["started_at"]
        axis.axvline(elapsed, linestyle="--", alpha=0.6)
        axis.text(elapsed + 0.3, 0.96, f"RTL {command['hw_id']}", transform=axis.get_xaxis_transform(), va="top")
    axis.set(xlabel="Rehearsal time (s)", ylabel="Height above own home (m)",
             title=f"SITL sequential return · {report['delay_sec']:g} s interval · {'PASS' if report['passed'] else 'FAILED'}")
    axis.grid(alpha=0.2)
    axis.legend()
    figure.savefig(output / "sequential-return.png", dpi=160)
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--drone-ids", nargs="+", required=True)
    parser.add_argument("--delay-sec", type=float, default=10)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require(1 <= args.delay_sec <= 300, "Interval must be 1–300 seconds")
    run(args)
