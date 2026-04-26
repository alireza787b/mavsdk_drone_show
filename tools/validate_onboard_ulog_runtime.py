#!/usr/bin/env python3
"""Validate onboard PX4 ULog listing, download, and erase-all against live SITL."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.runtime_validation_support import normalize_drone_ids, parse_csv_drone_ids, write_json_report
    from tools.validate_actions_runtime import (
        ApiClient,
        LAND,
        TAKEOFF,
        command_summary,
        require,
        require_full_acceptance,
        require_full_execution,
        wait_altitude_gain,
        wait_api_ready,
        wait_fleet_ready,
        wait_for,
        wait_for_command,
        wait_idle_subset,
    )
except Exception:  # pragma: no cover
    raise


GCS_ULOG_POLICY_ROUTE_TEMPLATE = "/api/logs/drone/{drone_id}/ulog/policy"
GCS_ULOG_FILES_ROUTE_TEMPLATE = "/api/logs/drone/{drone_id}/ulog/files"
GCS_ULOG_DOWNLOAD_ROUTE_TEMPLATE = "/api/logs/drone/{drone_id}/ulog/files/{log_id}/download"
GCS_ULOG_JOB_ROUTE_TEMPLATE = "/api/logs/drone/{drone_id}/ulog/downloads/{job_id}"
GCS_ULOG_CONTENT_ROUTE_TEMPLATE = "/api/logs/drone/{drone_id}/ulog/downloads/{job_id}/content"
GCS_ULOG_ERASE_ALL_ROUTE_TEMPLATE = "/api/logs/drone/{drone_id}/ulog/erase-all"


def log(message: str) -> None:
    print(message, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5030")
    parser.add_argument("--drone-ids", nargs="+", type=int)
    parser.add_argument("--drones")
    parser.add_argument("--takeoff-min-gain", type=float, default=4.0)
    parser.add_argument("--list-timeout-sec", type=int, default=60)
    parser.add_argument("--job-timeout-sec", type=int, default=120)
    parser.add_argument("--json-output")
    return parser.parse_args()


def resolve_selected_ids(args: argparse.Namespace) -> list[int]:
    if args.drone_ids:
        return normalize_drone_ids(args.drone_ids)
    if args.drones:
        return parse_csv_drone_ids(args.drones)
    return [1]


def get_json(client: ApiClient, path: str) -> dict[str, Any]:
    return client.get_json(path)


def post_json(client: ApiClient, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return client.post_json(path, payload or {})


def download_binary(base_url: str, path: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.read(), headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body or exc.reason}") from exc


def wait_for_ulogs(client: ApiClient, drone_id: int, *, timeout: int) -> dict[str, Any]:
    return wait_for(
        lambda: _list_if_nonempty(client, drone_id),
        label=f"onboard ULogs available for H{drone_id}",
        timeout=timeout,
        interval=2.0,
    )


def _list_if_nonempty(client: ApiClient, drone_id: int) -> dict[str, Any] | bool:
    payload = get_json(client, GCS_ULOG_FILES_ROUTE_TEMPLATE.format(drone_id=drone_id))
    return payload if (payload.get("count") or 0) > 0 else False


def wait_for_empty_ulogs(client: ApiClient, drone_id: int, *, timeout: int) -> dict[str, Any]:
    return wait_for(
        lambda: _list_if_empty(client, drone_id),
        label=f"onboard ULogs erased for H{drone_id}",
        timeout=timeout,
        interval=2.0,
    )


def _list_if_empty(client: ApiClient, drone_id: int) -> dict[str, Any] | bool:
    payload = get_json(client, GCS_ULOG_FILES_ROUTE_TEMPLATE.format(drone_id=drone_id))
    return payload if int(payload.get("count") or 0) == 0 else False


def wait_for_download_job(client: ApiClient, drone_id: int, job_id: str, *, timeout: int) -> dict[str, Any]:
    return wait_for(
        lambda: _job_if_terminal(client, drone_id, job_id),
        label=f"ULog download job {job_id} ready",
        timeout=timeout,
        interval=1.0,
    )


def _job_if_terminal(client: ApiClient, drone_id: int, job_id: str) -> dict[str, Any] | bool:
    payload = get_json(client, GCS_ULOG_JOB_ROUTE_TEMPLATE.format(drone_id=drone_id, job_id=job_id))
    status = str((payload.get("job") or {}).get("status") or "").lower()
    if status in {"ready", "failed"}:
        return payload
    return False


def extract_filename(headers: dict[str, str], fallback: str) -> str:
    content_disposition = headers.get("content-disposition", "")
    match = re.search(r'filename="?([^";]+)"?', content_disposition)
    if match:
        return match.group(1)
    return fallback


def main() -> None:
    args = parse_args()
    selected_ids = resolve_selected_ids(args)
    target_id = selected_ids[0]
    client = ApiClient(args.base_url)
    results: dict[str, Any] = {
        "validator": "onboard_ulog_runtime",
        "base_url": args.base_url,
        "selected_ids": selected_ids,
        "target_id": target_id,
        "takeoff_min_gain": float(args.takeoff_min_gain),
        "list_timeout_sec": int(args.list_timeout_sec),
        "job_timeout_sec": int(args.job_timeout_sec),
    }

    wait_api_ready(client, timeout=60)
    baseline_rows = wait_fleet_ready(client, [target_id], timeout=120)
    baseline_altitudes = {
        str(target_id): float(baseline_rows[str(target_id)].get("position_alt", 0.0) or 0.0)
    }
    results["baseline_row"] = baseline_rows[str(target_id)]

    policy = get_json(client, GCS_ULOG_POLICY_ROUTE_TEMPLATE.format(drone_id=target_id))
    require(policy.get("policy", {}).get("download_supported") is True, f"Unexpected ULog policy: {policy}")
    results["policy"] = policy

    takeoff = client.submit_command(TAKEOFF, [target_id], "SITL ULog Validation Takeoff")
    takeoff_status = wait_for_command(client, takeoff["command_id"], terminal=True, timeout=150)
    require(takeoff_status["status"] == "completed", f"Takeoff failed: {command_summary(takeoff_status)}")
    require_full_acceptance(takeoff_status, 1, "ULog takeoff")
    require_full_execution(takeoff_status, 1, "ULog takeoff")
    results["takeoff"] = command_summary(takeoff_status)

    airborne = wait_altitude_gain(
        client,
        [target_id],
        baseline_altitudes,
        float(args.takeoff_min_gain),
        timeout=120,
    )
    results["airborne_row"] = airborne[str(target_id)]

    land = client.submit_command(LAND, [target_id], "SITL ULog Validation Land")
    land_status = wait_for_command(client, land["command_id"], terminal=True, timeout=180)
    require(land_status["status"] == "completed", f"Land failed: {command_summary(land_status)}")
    require_full_acceptance(land_status, 1, "ULog land")
    require_full_execution(land_status, 1, "ULog land")
    results["land"] = command_summary(land_status)

    wait_idle_subset(client, [target_id], timeout=180)
    time.sleep(3.0)

    listed = wait_for_ulogs(client, target_id, timeout=int(args.list_timeout_sec))
    require(int(listed.get("count") or 0) > 0, f"No onboard ULogs listed after flight: {listed}")
    entry = listed["files"][0]
    results["listed"] = listed
    results["selected_entry"] = entry

    job_response = post_json(
        client,
        GCS_ULOG_DOWNLOAD_ROUTE_TEMPLATE.format(drone_id=target_id, log_id=int(entry["id"])),
        {},
    )
    job_id = str(job_response["job"]["job_id"])
    results["download_job_created"] = job_response

    final_job = wait_for_download_job(client, target_id, job_id, timeout=int(args.job_timeout_sec))
    require(final_job["job"]["status"] == "ready", f"ULog job failed: {final_job}")
    results["download_job_final"] = final_job

    binary, headers = download_binary(
        args.base_url,
        GCS_ULOG_CONTENT_ROUTE_TEMPLATE.format(drone_id=target_id, job_id=job_id),
    )
    require(binary, "Downloaded ULog content was empty.")
    filename = extract_filename(headers, final_job["job"].get("download_filename") or f"H{target_id}.ulg")
    require(f"_H{target_id}_" in filename or f"_H{target_id}." in filename, f"Download filename missing hw id: {filename}")
    require(filename.endswith(".ulg"), f"Unexpected ULog filename: {filename}")
    results["download"] = {
        "filename": filename,
        "bytes": len(binary),
        "headers": headers,
    }

    erase_response = post_json(client, GCS_ULOG_ERASE_ALL_ROUTE_TEMPLATE.format(drone_id=target_id), {})
    require(erase_response.get("status") == "accepted", f"Unexpected erase-all response: {erase_response}")
    results["erase_all"] = erase_response

    after_erase = wait_for_empty_ulogs(client, target_id, timeout=60)
    results["after_erase"] = after_erase

    write_json_report(args.json_output, results)
    log("Onboard ULog runtime validation passed.")


if __name__ == "__main__":
    main()
