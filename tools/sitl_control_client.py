#!/usr/bin/env python3
"""Headless SITL Control API client with shell fallback for validation tooling."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.gcs_api_routes import (  # noqa: E402
    GCS_SITL_CONTROL_OPERATION_ROUTE_TEMPLATE,
    GCS_SITL_CONTROL_POLICY_ROUTE,
    GCS_SITL_CONTROL_RECONCILE_ROUTE,
)
from tools.runtime_validation_support import (  # noqa: E402
    build_sitl_reset_command,
    contiguous_fleet_reset_parameters,
    normalize_drone_ids,
    write_json_report,
)


class SitlControlClientError(RuntimeError):
    """Raised when the SITL Control API or shell fallback cannot complete."""


def log(message: str) -> None:
    print(message, flush=True)


def _normalize_base_url(base_url: str) -> str:
    return str(base_url).rstrip("/")


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _request_json(
    method: str,
    url: str,
    *,
    timeout_sec: float,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = requests.request(method, url, json=json_body, timeout=timeout_sec)
    except requests.RequestException as exc:
        raise SitlControlClientError(f"{method} {url} failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if response.status_code >= 400:
        detail = payload if payload is not None else response.text
        raise SitlControlClientError(f"{method} {url} returned {response.status_code}: {detail}")

    if not isinstance(payload, dict):
        raise SitlControlClientError(f"{method} {url} returned a non-object JSON payload")
    return payload


def build_reconcile_request(drone_ids: list[int]) -> dict[str, Any]:
    params = contiguous_fleet_reset_parameters(drone_ids)
    payload: dict[str, Any] = {
        "target_count": params["target_count"],
        "start_id": params["start_id"],
        "start_ip": params["start_ip"],
        "git_sync_enabled": _env_flag("MDS_SITL_GIT_SYNC", True),
        "requirements_sync_enabled": _env_flag("MDS_SITL_REQUIREMENTS_SYNC", True),
    }

    optional_fields = {
        "image_ref": _optional_env("MDS_DOCKER_IMAGE"),
        "subnet": _optional_env("MDS_SITL_SUBNET"),
        "docker_network_name": _optional_env("MDS_SITL_DOCKER_NETWORK"),
    }
    payload.update({key: value for key, value in optional_fields.items() if value is not None})
    return payload


def get_policy(base_url: str, *, timeout_sec: float = 5.0) -> dict[str, Any]:
    return _request_json("GET", f"{_normalize_base_url(base_url)}{GCS_SITL_CONTROL_POLICY_ROUTE}", timeout_sec=timeout_sec)


def start_reconcile(base_url: str, drone_ids: list[int], *, timeout_sec: float = 10.0) -> dict[str, Any]:
    payload = build_reconcile_request(drone_ids)
    return _request_json(
        "POST",
        f"{_normalize_base_url(base_url)}{GCS_SITL_CONTROL_RECONCILE_ROUTE}",
        timeout_sec=timeout_sec,
        json_body=payload,
    )


def get_operation(base_url: str, operation_id: str, *, timeout_sec: float = 10.0) -> dict[str, Any]:
    route = GCS_SITL_CONTROL_OPERATION_ROUTE_TEMPLATE.format(operation_id=operation_id)
    return _request_json("GET", f"{_normalize_base_url(base_url)}{route}", timeout_sec=timeout_sec)


def is_api_usable(base_url: str, *, timeout_sec: float = 5.0) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        policy = get_policy(base_url, timeout_sec=timeout_sec)
    except SitlControlClientError as exc:
        return False, None, str(exc)

    docker = policy.get("docker") or {}
    if not bool(policy.get("sim_mode")):
        return False, policy, "SITL Control API is not in simulation mode"
    if bool(policy.get("read_only")):
        return False, policy, "SITL Control API is read-only"
    if not bool(docker.get("daemon_reachable")):
        return False, policy, str(docker.get("error") or "Docker daemon is not reachable")
    return True, policy, None


def wait_for_operation(
    base_url: str,
    operation_id: str,
    *,
    timeout_sec: float,
    poll_interval_sec: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    printed_logs: set[str] = set()

    while True:
        operation = get_operation(base_url, operation_id)
        for line in operation.get("log_lines") or []:
            if line not in printed_logs:
                printed_logs.add(line)
                log(line)

        status = str(operation.get("status") or "")
        if status == "succeeded":
            return operation
        if status == "failed":
            detail = operation.get("detail") or operation.get("summary") or "SITL reconcile failed"
            raise SitlControlClientError(str(detail))
        if time.monotonic() >= deadline:
            raise SitlControlClientError(f"SITL operation {operation_id} timed out after {timeout_sec}s")
        time.sleep(poll_interval_sec)


def run_api_reconcile(
    *,
    base_url: str,
    drone_ids: list[int],
    timeout_sec: float,
    poll_interval_sec: float,
) -> dict[str, Any]:
    started = time.monotonic()
    operation = start_reconcile(base_url, drone_ids)
    operation_id = str(operation.get("operation_id") or "").strip()
    if not operation_id:
        raise SitlControlClientError("SITL reconcile did not return an operation_id")
    log(f"Started SITL reconcile via API: {operation_id}")
    final_operation = wait_for_operation(
        base_url,
        operation_id,
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
    )
    return {
        "status": "passed",
        "execution_mode": "api",
        "operation": final_operation,
        "elapsed_sec": round(time.monotonic() - started, 2),
    }


def run_shell_reconcile(
    *,
    repo_root: Path,
    drone_ids: list[int],
) -> dict[str, Any]:
    command = build_sitl_reset_command(drone_ids)
    env = os.environ.copy()
    started = time.monotonic()
    log(f"Falling back to shell reset: {' '.join(command)} (cwd={repo_root})")
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return_code = process.wait()
    if return_code != 0:
        raise SitlControlClientError(f"Shell SITL reset exited with code {return_code}")
    return {
        "status": "passed",
        "execution_mode": "shell",
        "command": command,
        "elapsed_sec": round(time.monotonic() - started, 2),
    }


def run_reconcile(
    *,
    base_url: str,
    repo_root: Path,
    drone_ids: list[int],
    mode: str,
    timeout_sec: float,
    poll_interval_sec: float,
) -> dict[str, Any]:
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in {"auto", "api", "shell"}:
        raise SitlControlClientError(f"Unsupported reconcile mode: {mode}")

    if normalized_mode == "shell":
        return run_shell_reconcile(repo_root=repo_root, drone_ids=drone_ids)

    api_usable, policy, reason = is_api_usable(base_url)
    if api_usable:
        report = run_api_reconcile(
            base_url=base_url,
            drone_ids=drone_ids,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
        )
        report["policy"] = policy
        return report

    if normalized_mode == "api":
        raise SitlControlClientError(reason or "SITL Control API is unavailable")

    log(f"SITL Control API unavailable, using shell fallback: {reason or 'unknown reason'}")
    report = run_shell_reconcile(repo_root=repo_root, drone_ids=drone_ids)
    report["api_fallback_reason"] = reason
    report["policy"] = policy
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Headless SITL Control API client with shell fallback.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    policy_parser = subparsers.add_parser("policy", help="Fetch the SITL Control policy envelope.")
    policy_parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    policy_parser.add_argument("--timeout-sec", type=float, default=5.0)
    policy_parser.add_argument("--json-output", type=Path, default=None)

    reconcile_parser = subparsers.add_parser("reconcile", help="Reset/reconcile a contiguous SITL fleet.")
    reconcile_parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    reconcile_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    reconcile_parser.add_argument("--drone-ids", nargs="+", type=int, required=True)
    reconcile_parser.add_argument("--mode", choices=("auto", "api", "shell"), default="auto")
    reconcile_parser.add_argument("--timeout-sec", type=float, default=180.0)
    reconcile_parser.add_argument("--poll-interval-sec", type=float, default=1.0)
    reconcile_parser.add_argument("--json-output", type=Path, default=None)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "policy":
            payload = get_policy(args.base_url, timeout_sec=args.timeout_sec)
            write_json_report(args.json_output, payload)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if args.command == "reconcile":
            payload = run_reconcile(
                base_url=args.base_url,
                repo_root=args.repo_root.resolve(),
                drone_ids=normalize_drone_ids(args.drone_ids),
                mode=args.mode,
                timeout_sec=args.timeout_sec,
                poll_interval_sec=args.poll_interval_sec,
            )
            write_json_report(args.json_output, payload)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
    except SitlControlClientError as exc:
        error_payload = {"status": "failed", "error": str(exc)}
        write_json_report(getattr(args, "json_output", None), error_payload)
        print(json.dumps(error_payload, indent=2, sort_keys=True))
        return 1

    raise SitlControlClientError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
