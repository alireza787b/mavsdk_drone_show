#!/usr/bin/env python3
"""Run the reusable multi-mode SITL validation suite.

The suite intentionally separates:

- the validator checkout, where the Python tooling is executed from
- the runtime repo root, where the live GCS/SITL stack reads mission files and
  where host-side reset scripts must run

That distinction matters for remote validation hosts where the clean runtime
checkout serving the live API is not the same path as the temporary validation
checkout containing the latest uncommitted tooling.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.runtime_validation_support import build_sitl_reset_command, normalize_drone_ids, write_json_report


MODE_DRONE_SHOW = "drone_show"
MODE_SMART_SWARM = "smart_swarm"
MODE_SWARM_TRAJECTORY = "swarm_trajectory"
VALIDATION_MODES = (MODE_DRONE_SHOW, MODE_SMART_SWARM, MODE_SWARM_TRAJECTORY)


@dataclass(frozen=True)
class SuiteStep:
    name: str
    kind: str
    command: list[str]
    cwd: Path
    log_path: Path
    json_path: Path | None = None


def log(message: str) -> None:
    print(message, flush=True)


def parse_modes(raw: str) -> list[str]:
    values = [part.strip().lower() for part in str(raw).split(",") if part.strip()]
    modes: list[str] = []
    for value in values:
        if value not in VALIDATION_MODES:
            raise argparse.ArgumentTypeError(
                f"Unsupported validation mode '{value}'. Valid modes: {', '.join(VALIDATION_MODES)}"
            )
        if value not in modes:
            modes.append(value)
    if not modes:
        raise argparse.ArgumentTypeError("At least one validation mode is required.")
    return modes


def default_artifact_dir(validator_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return validator_root / "artifacts" / "sitl-validation" / timestamp


def build_drone_show_command(args: argparse.Namespace, json_path: Path) -> list[str]:
    command = [
        args.python,
        "tools/validate_drone_show_runtime.py",
        "--base-url",
        args.base_url,
        "--repo-root",
        str(args.repo_root),
        "--expected-show-count",
        str(args.expected_show_count),
        "--json-output",
        str(json_path),
        "--drone-ids",
        *[str(drone_id) for drone_id in args.drone_ids],
    ]
    if args.import_source_dir is not None:
        command.extend(["--import-source-dir", str(args.import_source_dir)])
    if args.skip_drone_show_internal_reset:
        command.append("--skip-sitl-reset")
    return command


def build_smart_swarm_command(args: argparse.Namespace, json_path: Path) -> list[str]:
    command = [
        args.python,
        "tools/validate_smart_swarm_runtime.py",
        "--base-url",
        args.base_url,
        "--json-output",
        str(json_path),
        "--drone-ids",
        *[str(drone_id) for drone_id in args.drone_ids],
        "--takeoff-min-gain",
        str(args.smart_swarm_takeoff_min_gain),
        "--horizontal-tolerance",
        str(args.smart_swarm_horizontal_tolerance),
        "--altitude-tolerance",
        str(args.smart_swarm_altitude_tolerance),
        "--formation-min-timeout",
        str(args.smart_swarm_formation_min_timeout),
        "--max-smart-swarm-velocity",
        str(args.smart_swarm_max_velocity),
        "--stability-samples",
        str(args.smart_swarm_stability_samples),
    ]
    if args.smart_swarm_skip_reassign:
        command.append("--skip-reassign")
    return command


def build_swarm_trajectory_command(args: argparse.Namespace, json_path: Path) -> list[str]:
    command = [
        args.python,
        "tools/validate_swarm_trajectory_runtime.py",
        "--base-url",
        args.base_url,
        "--repo-root",
        str(args.repo_root),
        "--json-output",
        str(json_path),
        "--drone-ids",
        *[str(drone_id) for drone_id in args.drone_ids],
        "--horiz-tolerance",
        str(args.trajectory_horiz_tolerance),
        "--vert-tolerance",
        str(args.trajectory_vert_tolerance),
        "--min-altitude-gain",
        str(args.trajectory_min_altitude_gain),
        "--formation-timeout",
        str(args.trajectory_formation_timeout),
        "--short-profile-altitude-gain",
        str(args.short_profile_altitude_gain),
        "--short-profile-entry-delay",
        str(args.short_profile_entry_delay),
        "--short-profile-leg-duration",
        str(args.short_profile_leg_duration),
    ]
    if args.prepare_short_profile:
        command.append("--prepare-short-profile")
    return command


def build_suite_steps(args: argparse.Namespace, artifact_dir: Path) -> list[SuiteStep]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    steps: list[SuiteStep] = []

    if not args.skip_initial_reset:
        steps.append(
            SuiteStep(
                name="reset_before_suite",
                kind="reset",
                command=build_sitl_reset_command(args.drone_ids),
                cwd=args.repo_root,
                log_path=artifact_dir / "01_reset_before_suite.log",
            )
        )

    index = 1 if args.skip_initial_reset else 2
    seen_non_drone_show = False

    for mode in args.modes:
        if mode == MODE_DRONE_SHOW and seen_non_drone_show and not args.skip_pre_drone_show_reset:
            steps.append(
                SuiteStep(
                    name="reset_before_drone_show",
                    kind="reset",
                    command=build_sitl_reset_command(args.drone_ids),
                    cwd=args.repo_root,
                    log_path=artifact_dir / f"{index:02d}_reset_before_drone_show.log",
                )
            )
            index += 1

        if mode == MODE_DRONE_SHOW:
            steps.append(
                SuiteStep(
                    name=MODE_DRONE_SHOW,
                    kind="validator",
                    command=build_drone_show_command(args, artifact_dir / "drone_show.json"),
                    cwd=args.validator_root,
                    log_path=artifact_dir / f"{index:02d}_drone_show.log",
                    json_path=artifact_dir / "drone_show.json",
                )
            )
        elif mode == MODE_SMART_SWARM:
            steps.append(
                SuiteStep(
                    name=MODE_SMART_SWARM,
                    kind="validator",
                    command=build_smart_swarm_command(args, artifact_dir / "smart_swarm.json"),
                    cwd=args.validator_root,
                    log_path=artifact_dir / f"{index:02d}_smart_swarm.log",
                    json_path=artifact_dir / "smart_swarm.json",
                )
            )
        elif mode == MODE_SWARM_TRAJECTORY:
            steps.append(
                SuiteStep(
                    name=MODE_SWARM_TRAJECTORY,
                    kind="validator",
                    command=build_swarm_trajectory_command(args, artifact_dir / "swarm_trajectory.json"),
                    cwd=args.validator_root,
                    log_path=artifact_dir / f"{index:02d}_swarm_trajectory.log",
                    json_path=artifact_dir / "swarm_trajectory.json",
                )
            )
        else:  # pragma: no cover
            raise RuntimeError(f"Unsupported validation mode: {mode}")

        if mode != MODE_DRONE_SHOW:
            seen_non_drone_show = True
        index += 1

    return steps


def run_step(step: SuiteStep, *, dry_run: bool = False) -> dict[str, Any]:
    log(f"STEP {step.name}: {' '.join(step.command)} (cwd={step.cwd})")
    if dry_run:
        return {
            "name": step.name,
            "kind": step.kind,
            "status": "dry_run",
            "command": step.command,
            "cwd": str(step.cwd),
            "log_path": str(step.log_path),
            "json_path": str(step.json_path) if step.json_path else None,
            "elapsed_sec": 0.0,
        }

    step.log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    env = os.environ.copy()

    with step.log_path.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            step.command,
            cwd=step.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log_handle.write(line)
        return_code = process.wait()

    elapsed = round(time.monotonic() - started, 2)
    return {
        "name": step.name,
        "kind": step.kind,
        "status": "passed" if return_code == 0 else "failed",
        "command": step.command,
        "cwd": str(step.cwd),
        "log_path": str(step.log_path),
        "json_path": str(step.json_path) if step.json_path else None,
        "elapsed_sec": elapsed,
        "return_code": return_code,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the reusable multi-mode SITL validation suite.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="GCS API base URL")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Runtime repo root used for SITL resets and validator repo-backed mission data access",
    )
    parser.add_argument(
        "--validator-root",
        type=Path,
        default=REPO_ROOT,
        help="Checkout containing this suite and the validator tools to execute",
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable used to launch the individual validators")
    parser.add_argument(
        "--modes",
        type=parse_modes,
        default=list(VALIDATION_MODES),
        help="Comma-separated validation modes to run in order. Default: drone_show,smart_swarm,swarm_trajectory",
    )
    parser.add_argument("--drone-ids", nargs="+", type=int, default=[1, 2, 3], help="Selected contiguous drone IDs to validate")
    parser.add_argument("--import-source-dir", type=Path, default=None, help="Optional SkyBrush source directory for Drone Show import")
    parser.add_argument("--expected-show-count", type=int, default=5, help="Expected show metadata count for the Drone Show validator")
    parser.add_argument("--skip-initial-reset", action="store_true", help="Skip the fresh SITL recreate before the suite starts")
    parser.add_argument("--skip-pre-drone-show-reset", action="store_true", help="Skip the protective SITL reset inserted when Drone Show is scheduled after another mission family")
    parser.add_argument("--skip-drone-show-internal-reset", action="store_true", help="Skip Drone Show validator internal resets between its sub-modes")
    parser.add_argument("--smart-swarm-skip-reassign", action="store_true", help="Skip the Smart Swarm in-flight reassignment drill")
    parser.add_argument("--smart-swarm-takeoff-min-gain", type=float, default=4.0, help="Minimum Smart Swarm altitude gain after takeoff")
    parser.add_argument("--smart-swarm-horizontal-tolerance", type=float, default=5.0, help="Smart Swarm formation horizontal tolerance in meters")
    parser.add_argument("--smart-swarm-altitude-tolerance", type=float, default=1.5, help="Smart Swarm formation altitude tolerance in meters")
    parser.add_argument("--smart-swarm-formation-min-timeout", type=int, default=45, help="Minimum Smart Swarm formation-settle timeout")
    parser.add_argument("--smart-swarm-max-velocity", type=float, default=3.0, help="Expected Smart Swarm max velocity used for timeout sizing")
    parser.add_argument("--smart-swarm-stability-samples", type=int, default=3, help="Consecutive Smart Swarm in-tolerance samples required")
    parser.add_argument("--prepare-short-profile", action=argparse.BooleanOptionalAction, default=True, help="Generate deterministic short Swarm Trajectory leader profiles before processing")
    parser.add_argument("--short-profile-altitude-gain", type=float, default=12.0, help="Relative altitude for generated short Swarm Trajectory profiles")
    parser.add_argument("--short-profile-entry-delay", type=float, default=8.0, help="Entry delay for generated short Swarm Trajectory profiles")
    parser.add_argument("--short-profile-leg-duration", type=float, default=10.0, help="Per-leg duration for generated short Swarm Trajectory profiles")
    parser.add_argument("--trajectory-horiz-tolerance", type=float, default=18.0, help="Swarm Trajectory horizontal formation tolerance")
    parser.add_argument("--trajectory-vert-tolerance", type=float, default=8.0, help="Swarm Trajectory vertical formation tolerance")
    parser.add_argument("--trajectory-min-altitude-gain", type=float, default=2.0, help="Swarm Trajectory minimum altitude gain before formation sampling")
    parser.add_argument("--trajectory-formation-timeout", type=int, default=120, help="Swarm Trajectory formation timeout in seconds")
    parser.add_argument("--artifact-dir", type=Path, default=None, help="Directory for suite logs and per-mode JSON reports")
    parser.add_argument("--dry-run", action="store_true", help="Print the suite plan without executing it")
    args = parser.parse_args()
    args.drone_ids = normalize_drone_ids(args.drone_ids)
    args.repo_root = args.repo_root.resolve()
    args.validator_root = args.validator_root.resolve()
    args.artifact_dir = args.artifact_dir or default_artifact_dir(args.validator_root)
    return args


def main() -> int:
    args = parse_args()
    steps = build_suite_steps(args, args.artifact_dir)

    summary: dict[str, Any] = {
        "base_url": args.base_url,
        "repo_root": str(args.repo_root),
        "validator_root": str(args.validator_root),
        "python": args.python,
        "drone_ids": args.drone_ids,
        "modes": args.modes,
        "artifact_dir": str(args.artifact_dir),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }

    for step in steps:
        result = run_step(step, dry_run=args.dry_run)
        summary["steps"].append(result)
        write_json_report(args.artifact_dir / "suite-summary.json", summary)
        if result["status"] == "failed":
            summary["status"] = "failed"
            write_json_report(args.artifact_dir / "suite-summary.json", summary)
            log(f"SUITE FAILED at step {step.name}; see {step.log_path}")
            return 1

    summary["status"] = "dry_run" if args.dry_run else "passed"
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json_report(args.artifact_dir / "suite-summary.json", summary)
    log(f"SUITE {summary['status'].upper()}: {args.artifact_dir}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
