#!/usr/bin/env python3
"""Remove all local SITL containers through the GCS SITL Control API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _request_json(method: str, url: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcs-api", default="http://localhost:5030", help="Base GCS API URL")
    args = parser.parse_args()

    base_url = args.gcs_api.rstrip("/")
    try:
        inventory = _request_json("GET", f"{base_url}/api/v1/system/sitl/instances", timeout=10.0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Failed to read SITL inventory from {base_url}: {exc}", file=sys.stderr)
        return 1

    names = [item.get("name") for item in inventory.get("instances", []) if item.get("name")]
    if not names:
        print("No local SITL containers found.")
        return 0

    try:
        operation = _request_json(
            "POST",
            f"{base_url}/api/v1/system/sitl/instances/actions",
            {"action": "remove", "instance_names": names},
            timeout=30.0,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Failed to queue SITL removal through {base_url}: {exc}", file=sys.stderr)
        return 1

    summary = operation.get("summary") or f"Queued removal for {len(names)} SITL container(s)."
    operation_id = operation.get("operation_id")
    print(summary)
    if operation_id:
        print(f"Operation: {operation_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
