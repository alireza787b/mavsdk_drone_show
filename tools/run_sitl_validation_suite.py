#!/usr/bin/env python3
"""Run the reusable declarative SITL validation suite.

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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.runtime_validation_support import build_sitl_reset_command, normalize_drone_ids, write_json_report

BUNDLED_PLAN_DIR = REPO_ROOT / "tools" / "sitl_plans"


MODE_DRONE_SHOW = "drone_show"
MODE_CONFIGURATION = "configuration"
MODE_ACTIONS = "actions"
MODE_SMART_SWARM = "smart_swarm"
MODE_SWARM_TRAJECTORY = "swarm_trajectory"
VALIDATION_MODES = (
    MODE_CONFIGURATION,
    MODE_DRONE_SHOW,
    MODE_ACTIONS,
    MODE_SMART_SWARM,
    MODE_SWARM_TRAJECTORY,
)

TEMPLATE_OPERATOR_REGRESSION = "operator_regression"
TEMPLATE_MISSION_REGRESSION = "mission_regression"
TEMPLATE_ACTIONS_ONLY = "actions_only"
TEMPLATE_CONFIG_ONLY = "config_only"

TEMPLATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    TEMPLATE_OPERATOR_REGRESSION: {
        "description": "Reset, Mission Config/origin, Drone Show, standalone action controls, Smart Swarm, and Swarm Trajectory.",
        "steps": [
            {"validator": MODE_CONFIGURATION},
            {"validator": MODE_DRONE_SHOW},
            {"validator": MODE_ACTIONS},
            {"validator": MODE_SMART_SWARM},
            {"validator": MODE_SWARM_TRAJECTORY},
        ],
    },
    TEMPLATE_MISSION_REGRESSION: {
        "description": "Reset plus the three mission-family validators without the standalone actions drill.",
        "steps": [
            {"validator": MODE_DRONE_SHOW},
            {"validator": MODE_SMART_SWARM},
            {"validator": MODE_SWARM_TRAJECTORY},
        ],
    },
    TEMPLATE_ACTIONS_ONLY: {
        "description": "Reset plus the standalone action-control validator only.",
        "steps": [
            {"validator": MODE_ACTIONS},
        ],
    },
    TEMPLATE_CONFIG_ONLY: {
        "description": "Reset plus the Mission Config / swarm / origin runtime validator only.",
        "steps": [
            {"validator": MODE_CONFIGURATION},
        ],
    },
}

# TODO(deferred): Add a QuickScout SITL validator/template after the QuickScout
# mission behavior and operator workflow are mature enough to support a stable
# deterministic acceptance contract.


@dataclass(frozen=True)
class SuitePlanStep:
    name: str
    kind: str
    validator: str | None = None
    drone_ids: tuple[int, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SuiteStep:
    name: str
    kind: str
    command: list[str]
    cwd: Path
    log_path: Path
    json_path: Path | None = None
    validator: str | None = None
    drone_ids: tuple[int, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


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


def sanitize_step_name(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(raw).strip().lower())
    return cleaned.strip("_") or "step"


def option_value(args: argparse.Namespace, options: dict[str, Any], key: str) -> Any:
    return options.get(key, getattr(args, key))


def normalize_step_drone_ids(drone_ids: list[int] | tuple[int, ...] | None, default_ids: list[int]) -> tuple[int, ...]:
    selected = list(drone_ids) if drone_ids else list(default_ids)
    return tuple(normalize_drone_ids(selected))


def build_drone_show_command(
    args: argparse.Namespace,
    json_path: Path,
    *,
    drone_ids: tuple[int, ...],
    options: dict[str, Any],
) -> list[str]:
    command = [
        args.python,
        "tools/validate_drone_show_runtime.py",
        "--base-url",
        args.base_url,
        "--repo-root",
        str(args.repo_root),
        "--expected-show-count",
        str(option_value(args, options, "expected_show_count")),
        "--json-output",
        str(json_path),
        "--drone-ids",
        *[str(drone_id) for drone_id in drone_ids],
    ]
    import_source_dir = option_value(args, options, "import_source_dir")
    if import_source_dir is not None:
        command.extend(["--import-source-dir", str(import_source_dir)])
    if bool(option_value(args, options, "skip_drone_show_internal_reset")):
        command.append("--skip-sitl-reset")
    return command


def build_configuration_command(
    args: argparse.Namespace,
    json_path: Path,
    *,
    drone_ids: tuple[int, ...],
    options: dict[str, Any],
) -> list[str]:
    command = [
        args.python,
        "tools/validate_configuration_runtime.py",
        "--base-url",
        args.base_url,
        "--repo-root",
        str(args.repo_root),
        "--json-output",
        str(json_path),
        "--drone-ids",
        *[str(drone_id) for drone_id in drone_ids],
        f"--metadata-suffix={option_value(args, options, 'config_metadata_suffix')}",
        "--origin-altitude-delta",
        str(option_value(args, options, "config_origin_altitude_delta")),
        "--swarm-put-offset-delta",
        str(option_value(args, options, "config_swarm_put_offset_delta")),
        "--swarm-patch-offset-delta",
        str(option_value(args, options, "config_swarm_patch_offset_delta")),
    ]
    return command


def build_actions_command(
    args: argparse.Namespace,
    json_path: Path,
    *,
    drone_ids: tuple[int, ...],
    options: dict[str, Any],
) -> list[str]:
    return [
        args.python,
        "tools/validate_actions_runtime.py",
        "--base-url",
        args.base_url,
        "--json-output",
        str(json_path),
        "--drone-ids",
        *[str(drone_id) for drone_id in drone_ids],
        "--takeoff-min-gain",
        str(option_value(args, options, "actions_takeoff_min_gain")),
        "--post-rtl-airborne-gain",
        str(option_value(args, options, "actions_post_rtl_airborne_gain")),
    ]


def build_smart_swarm_command(
    args: argparse.Namespace,
    json_path: Path,
    *,
    drone_ids: tuple[int, ...],
    options: dict[str, Any],
) -> list[str]:
    command = [
        args.python,
        "tools/validate_smart_swarm_runtime.py",
        "--base-url",
        args.base_url,
        "--json-output",
        str(json_path),
        "--drone-ids",
        *[str(drone_id) for drone_id in drone_ids],
        "--takeoff-min-gain",
        str(option_value(args, options, "smart_swarm_takeoff_min_gain")),
        "--horizontal-tolerance",
        str(option_value(args, options, "smart_swarm_horizontal_tolerance")),
        "--altitude-tolerance",
        str(option_value(args, options, "smart_swarm_altitude_tolerance")),
        "--formation-min-timeout",
        str(option_value(args, options, "smart_swarm_formation_min_timeout")),
        "--max-smart-swarm-velocity",
        str(option_value(args, options, "smart_swarm_max_velocity")),
        "--stability-samples",
        str(option_value(args, options, "smart_swarm_stability_samples")),
    ]
    if bool(option_value(args, options, "smart_swarm_skip_reassign")):
        command.append("--skip-reassign")
    return command


def build_swarm_trajectory_command(
    args: argparse.Namespace,
    json_path: Path,
    *,
    drone_ids: tuple[int, ...],
    options: dict[str, Any],
) -> list[str]:
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
        *[str(drone_id) for drone_id in drone_ids],
        "--horiz-tolerance",
        str(option_value(args, options, "trajectory_horiz_tolerance")),
        "--vert-tolerance",
        str(option_value(args, options, "trajectory_vert_tolerance")),
        "--min-altitude-gain",
        str(option_value(args, options, "trajectory_min_altitude_gain")),
        "--formation-timeout",
        str(option_value(args, options, "trajectory_formation_timeout")),
        "--short-profile-altitude-gain",
        str(option_value(args, options, "short_profile_altitude_gain")),
        "--short-profile-entry-delay",
        str(option_value(args, options, "short_profile_entry_delay")),
        "--short-profile-leg-duration",
        str(option_value(args, options, "short_profile_leg_duration")),
    ]
    if bool(option_value(args, options, "prepare_short_profile")):
        command.append("--prepare-short-profile")
    return command


VALIDATOR_BUILDERS = {
    MODE_CONFIGURATION: build_configuration_command,
    MODE_DRONE_SHOW: build_drone_show_command,
    MODE_ACTIONS: build_actions_command,
    MODE_SMART_SWARM: build_smart_swarm_command,
    MODE_SWARM_TRAJECTORY: build_swarm_trajectory_command,
}


def list_templates() -> str:
    lines = []
    for template_name, definition in TEMPLATE_DEFINITIONS.items():
        validators = [step["validator"] for step in definition["steps"]]
        lines.append(f"{template_name}: {definition['description']} [{', '.join(validators)}]")
    return "\n".join(lines)


def canonical_plan_payload(plan_steps: list[SuitePlanStep]) -> list[dict[str, Any]]:
    return [
        {
            "name": step.name,
            "kind": step.kind,
            "validator": step.validator,
            "drone_ids": list(step.drone_ids),
            "options": step.options,
        }
        for step in plan_steps
    ]


def compute_plan_hash(plan_steps: list[SuitePlanStep]) -> str:
    payload = json.dumps(canonical_plan_payload(plan_steps), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json_object_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON: {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must contain a JSON object: {path}")
    return payload


def bundled_plan_catalog() -> dict[str, dict[str, Any]]:
    if not BUNDLED_PLAN_DIR.exists():
        return {}

    catalog: dict[str, dict[str, Any]] = {}
    for plan_path in sorted(BUNDLED_PLAN_DIR.glob("*.json")):
        payload = load_json_object_file(plan_path, label="Bundled SITL plan")
        catalog[plan_path.stem] = {
            "path": plan_path,
            "title": str(payload.get("title") or plan_path.stem),
            "description": str(payload.get("description") or "").strip(),
            "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
        }
    return catalog


def list_bundled_plans() -> str:
    catalog = bundled_plan_catalog()
    if not catalog:
        return "No bundled SITL plans available."

    lines = ["Bundled SITL plans:"]
    for name in sorted(catalog):
        entry = catalog[name]
        description = f" - {entry['description']}" if entry["description"] else ""
        lines.append(f"- {name}: {entry['title']}{description}")
    return "\n".join(lines)


def resolve_bundled_plan_path(plan_name: str) -> Path:
    catalog = bundled_plan_catalog()
    entry = catalog.get(plan_name)
    if entry is None:
        valid_names = ", ".join(sorted(catalog)) or "(none)"
        raise RuntimeError(f"Unknown bundled SITL plan '{plan_name}'. Available plans: {valid_names}")
    return Path(entry["path"])


def git_metadata(repo_root: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "path": str(repo_root),
        "head": None,
        "branch": None,
        "dirty": None,
    }
    try:
        metadata["head"] = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        metadata["branch"] = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty_output = subprocess.check_output(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        metadata["dirty"] = bool(dirty_output.strip())
    except Exception:
        return metadata
    return metadata


def collect_provenance(args: argparse.Namespace, plan_steps: list[SuitePlanStep]) -> dict[str, Any]:
    tracked_env = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("MDS_")
        and key
        in {
            "MDS_REPO_URL",
            "MDS_BRANCH",
            "MDS_DOCKER_IMAGE",
            "MDS_SITL_GIT_SYNC",
            "MDS_SITL_REQUIREMENTS_SYNC",
        }
    }
    return {
        "validator_repo": git_metadata(args.validator_root),
        "runtime_repo": git_metadata(args.repo_root),
        "python": {
            "executable": args.python,
            "version": sys.version,
        },
        "base_url": args.base_url,
        "plan_hash": compute_plan_hash(plan_steps),
        "tracked_env": tracked_env,
    }


def build_template_plan(template_name: str, default_ids: list[int]) -> list[SuitePlanStep]:
    definition = TEMPLATE_DEFINITIONS.get(template_name)
    if definition is None:
        raise RuntimeError(
            f"Unsupported template '{template_name}'. Valid templates: {', '.join(sorted(TEMPLATE_DEFINITIONS))}"
        )

    steps: list[SuitePlanStep] = []
    for entry in definition["steps"]:
        validator = str(entry["validator"])
        steps.append(
            SuitePlanStep(
                name=str(entry.get("name") or validator),
                kind="validator",
                validator=validator,
                drone_ids=normalize_step_drone_ids(entry.get("drone_ids"), default_ids),
                options=dict(entry.get("options") or {}),
            )
        )
    return steps


def build_modes_plan(modes: list[str], default_ids: list[int]) -> list[SuitePlanStep]:
    return [
        SuitePlanStep(
            name=mode,
            kind="validator",
            validator=mode,
            drone_ids=normalize_step_drone_ids(None, default_ids),
        )
        for mode in modes
    ]


def load_plan_file(plan_file: Path, default_ids: list[int]) -> list[SuitePlanStep]:
    payload = load_json_object_file(plan_file, label="SITL plan file")

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RuntimeError(f"SITL plan file must contain a non-empty 'steps' list: {plan_file}")

    plan_steps: list[SuitePlanStep] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise RuntimeError(f"SITL plan step #{index} must be a JSON object.")

        validator = raw_step.get("validator")
        kind = str(raw_step.get("kind") or ("validator" if validator else "")).strip().lower()
        if kind not in {"validator", "reset"}:
            raise RuntimeError(f"SITL plan step #{index} has unsupported kind '{kind}'.")

        drone_ids = normalize_step_drone_ids(raw_step.get("drone_ids"), default_ids)
        options = raw_step.get("options") or {}
        if not isinstance(options, dict):
            raise RuntimeError(f"SITL plan step #{index} options must be a JSON object.")

        if kind == "validator":
            validator_name = str(validator or "").strip().lower()
            if validator_name not in VALIDATOR_BUILDERS:
                raise RuntimeError(
                    f"SITL plan step #{index} has unsupported validator '{validator_name}'. "
                    f"Valid validators: {', '.join(VALIDATION_MODES)}"
                )
            step_name = str(raw_step.get("name") or validator_name)
            plan_steps.append(
                SuitePlanStep(
                    name=step_name,
                    kind="validator",
                    validator=validator_name,
                    drone_ids=drone_ids,
                    options=dict(options),
                )
            )
            continue

        step_name = str(raw_step.get("name") or f"reset_{index}")
        plan_steps.append(
            SuitePlanStep(
                name=step_name,
                kind="reset",
                drone_ids=drone_ids,
                options=dict(options),
            )
        )

    return plan_steps


def insert_automatic_resets(args: argparse.Namespace, plan_steps: list[SuitePlanStep]) -> list[SuitePlanStep]:
    adjusted = list(plan_steps)
    if not args.skip_initial_reset and (not adjusted or adjusted[0].kind != "reset"):
        adjusted.insert(
            0,
            SuitePlanStep(
                name="reset_before_suite",
                kind="reset",
                drone_ids=tuple(args.drone_ids),
            ),
        )

    protected: list[SuitePlanStep] = []
    seen_non_drone_show_since_reset = False
    for step in adjusted:
        if step.kind == "reset":
            protected.append(step)
            seen_non_drone_show_since_reset = False
            continue

        if (
            step.validator == MODE_DRONE_SHOW
            and seen_non_drone_show_since_reset
            and not args.skip_pre_drone_show_reset
        ):
            protected.append(
                SuitePlanStep(
                    name=f"reset_before_{sanitize_step_name(step.name)}",
                    kind="reset",
                    drone_ids=tuple(step.drone_ids),
                )
            )
            seen_non_drone_show_since_reset = False

        protected.append(step)
        seen_non_drone_show_since_reset = step.validator != MODE_DRONE_SHOW

    if args.final_reset and (not protected or protected[-1].kind != "reset"):
        protected.append(
            SuitePlanStep(
                name="reset_after_suite",
                kind="reset",
                drone_ids=tuple(args.drone_ids),
            )
        )

    return protected


def resolve_plan_steps(args: argparse.Namespace) -> list[SuitePlanStep]:
    if args.plan_file is not None:
        base_plan = load_plan_file(args.plan_file, args.drone_ids)
    elif args.modes is not None:
        base_plan = build_modes_plan(args.modes, args.drone_ids)
    else:
        base_plan = build_template_plan(args.template, args.drone_ids)
    return insert_automatic_resets(args, base_plan)


def build_suite_steps(args: argparse.Namespace, artifact_dir: Path) -> list[SuiteStep]:
    plan_steps = resolve_plan_steps(args)

    steps: list[SuiteStep] = []
    for index, plan_step in enumerate(plan_steps, start=1):
        step_slug = sanitize_step_name(plan_step.name)
        log_path = artifact_dir / f"{index:02d}_{step_slug}.log"

        if plan_step.kind == "reset":
            steps.append(
                SuiteStep(
                    name=plan_step.name,
                    kind="reset",
                    command=build_sitl_reset_command(plan_step.drone_ids),
                    cwd=args.repo_root,
                    log_path=log_path,
                    drone_ids=tuple(plan_step.drone_ids),
                    options=dict(plan_step.options),
                )
            )
            continue

        json_path = artifact_dir / f"{step_slug}.json"
        command_builder = VALIDATOR_BUILDERS[plan_step.validator]
        steps.append(
            SuiteStep(
                name=plan_step.name,
                kind="validator",
                command=command_builder(
                    args,
                    json_path,
                    drone_ids=tuple(plan_step.drone_ids),
                    options=dict(plan_step.options),
                ),
                cwd=args.validator_root,
                log_path=log_path,
                json_path=json_path,
                validator=plan_step.validator,
                drone_ids=tuple(plan_step.drone_ids),
                options=dict(plan_step.options),
            )
        )

    return steps


def run_step(step: SuiteStep, *, dry_run: bool = False) -> dict[str, Any]:
    log(f"STEP {step.name}: {' '.join(step.command)} (cwd={step.cwd})")
    if dry_run:
        return {
            "name": step.name,
            "kind": step.kind,
            "validator": step.validator,
            "drone_ids": list(step.drone_ids),
            "options": step.options,
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
        "validator": step.validator,
        "drone_ids": list(step.drone_ids),
        "options": step.options,
        "status": "passed" if return_code == 0 else "failed",
        "command": step.command,
        "cwd": str(step.cwd),
        "log_path": str(step.log_path),
        "json_path": str(step.json_path) if step.json_path else None,
        "elapsed_sec": elapsed,
        "return_code": return_code,
    }


def write_suite_summary(summary_path: Path, summary: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    write_json_report(summary_path, summary)


def run_failure_cleanup(args: argparse.Namespace, artifact_dir: Path) -> dict[str, Any] | None:
    if not args.final_reset:
        return None

    cleanup_step = SuiteStep(
        name="failure_cleanup_reset",
        kind="reset",
        command=build_sitl_reset_command(args.drone_ids),
        cwd=args.repo_root,
        log_path=artifact_dir / "failure_cleanup_reset.log",
        drone_ids=tuple(args.drone_ids),
    )
    return run_step(cleanup_step, dry_run=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the reusable multi-mode SITL validation suite.")
    bundled_plan_names = sorted(bundled_plan_catalog())
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
        "--template",
        choices=sorted(TEMPLATE_DEFINITIONS),
        default=TEMPLATE_OPERATOR_REGRESSION,
        help="Named built-in suite template to run when --plan-file and --modes are not supplied",
    )
    parser.add_argument(
        "--plan-name",
        choices=bundled_plan_names or None,
        default=None,
        help="Named checked-in JSON plan from tools/sitl_plans/",
    )
    parser.add_argument(
        "--plan-file",
        type=Path,
        default=None,
        help="Optional JSON plan file overriding the built-in template/mode planning",
    )
    parser.add_argument(
        "--modes",
        type=parse_modes,
        default=None,
        help="Compatibility shorthand: comma-separated validation modes to run in order",
    )
    parser.add_argument("--list-templates", action="store_true", help="List built-in suite templates and exit")
    parser.add_argument("--list-bundled-plans", action="store_true", help="List checked-in JSON plans from tools/sitl_plans and exit")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=[1, 2, 3], help="Selected contiguous drone IDs to validate by default")
    parser.add_argument("--config-metadata-suffix", default="-CFG", help="Suffix appended to temporary validator fleet metadata updates")
    parser.add_argument("--config-origin-altitude-delta", type=float, default=0.5, help="Temporary origin altitude delta used while validating origin write/read routes")
    parser.add_argument("--config-swarm-put-offset-delta", type=float, default=1.25, help="Offset delta used for the full swarm-config PUT mutation")
    parser.add_argument("--config-swarm-patch-offset-delta", type=float, default=2.0, help="Offset delta used for the swarm assignment PATCH mutation")
    parser.add_argument("--import-source-dir", type=Path, default=None, help="Optional SkyBrush source directory for Drone Show import")
    parser.add_argument("--expected-show-count", type=int, default=5, help="Expected show metadata count for the Drone Show validator")
    parser.add_argument("--skip-initial-reset", action="store_true", help="Skip the fresh SITL recreate before the suite starts")
    parser.add_argument("--skip-pre-drone-show-reset", action="store_true", help="Skip the protective SITL reset inserted when Drone Show is scheduled after another mission family")
    parser.add_argument("--final-reset", action=argparse.BooleanOptionalAction, default=True, help="Append a final SITL reset after the suite and use the same reset as failure cleanup")
    parser.add_argument("--skip-drone-show-internal-reset", action="store_true", help="Skip Drone Show validator internal resets between its sub-modes")
    parser.add_argument("--actions-takeoff-min-gain", type=float, default=4.0, help="Minimum altitude gain required after TAKEOFF in the standalone action validator")
    parser.add_argument("--actions-post-rtl-airborne-gain", type=float, default=2.0, help="Minimum altitude gain required when confirming non-target drones stayed airborne after RTL override")
    parser.add_argument("--smart-swarm-skip-reassign", action="store_true", help="Skip the Smart Swarm in-flight reassignment check")
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
    parser.add_argument("--artifact-dir", type=Path, default=None, help="Directory for suite logs and per-step JSON reports")
    parser.add_argument("--dry-run", action="store_true", help="Print the suite plan without executing it")
    args = parser.parse_args()
    if args.plan_name and args.plan_file is not None:
        parser.error("--plan-name and --plan-file are mutually exclusive")
    if args.plan_name and args.modes is not None:
        parser.error("--plan-name and --modes are mutually exclusive")
    args.drone_ids = normalize_drone_ids(args.drone_ids)
    args.repo_root = args.repo_root.resolve()
    args.validator_root = args.validator_root.resolve()
    if args.plan_name:
        args.plan_file = resolve_bundled_plan_path(args.plan_name)
    args.plan_file = args.plan_file.resolve() if args.plan_file is not None else None
    args.import_source_dir = args.import_source_dir.resolve() if args.import_source_dir is not None else None
    args.artifact_dir = args.artifact_dir or default_artifact_dir(args.validator_root)
    return args


def main() -> int:
    args = parse_args()
    if args.list_templates:
        print(list_templates())
        return 0
    if args.list_bundled_plans:
        print(list_bundled_plans())
        return 0

    plan_steps = resolve_plan_steps(args)
    steps = build_suite_steps(args, args.artifact_dir)
    if not args.dry_run:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "base_url": args.base_url,
        "repo_root": str(args.repo_root),
        "validator_root": str(args.validator_root),
        "python": args.python,
        "drone_ids": args.drone_ids,
        "template": None if args.modes is not None or args.plan_file is not None else args.template,
        "plan_name": args.plan_name,
        "plan_file": str(args.plan_file) if args.plan_file is not None else None,
        "modes": args.modes,
        "artifact_dir": str(args.artifact_dir),
        "plan": canonical_plan_payload(plan_steps),
        "plan_hash": compute_plan_hash(plan_steps),
        "provenance": collect_provenance(args, plan_steps),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }

    for step in steps:
        result = run_step(step, dry_run=args.dry_run)
        summary["steps"].append(result)
        write_suite_summary(args.artifact_dir / "suite-summary.json", summary, dry_run=args.dry_run)
        if result["status"] == "failed":
            summary["status"] = "failed"
            if not args.dry_run:
                summary["cleanup"] = run_failure_cleanup(args, args.artifact_dir)
            write_suite_summary(args.artifact_dir / "suite-summary.json", summary, dry_run=args.dry_run)
            log(f"SUITE FAILED at step {step.name}; see {step.log_path}")
            return 1

    summary["status"] = "dry_run" if args.dry_run else "passed"
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_suite_summary(args.artifact_dir / "suite-summary.json", summary, dry_run=args.dry_run)
    log(f"SUITE {summary['status'].upper()}: {args.artifact_dir}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
