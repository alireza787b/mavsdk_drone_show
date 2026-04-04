# 2026-04-04 SITL Validation Platform Phase 1

## Goal

Turn the existing mission-family SITL helpers into a reusable deterministic
validation platform that can be used by operators, maintainers, AI agents, and
future CI gates.

## What Changed

- added `tools/validate_actions_runtime.py`
  - covers standalone TAKEOFF, HOLD, targeted RTL override, remaining-drone LAND, and idle cleanup
- upgraded `tools/run_sitl_validation_suite.py`
  - built-in templates:
    - `operator_regression`
    - `mission_regression`
    - `actions_only`
  - declarative JSON `--plan-file` support
  - side-effect-free `--dry-run`
  - `plan_hash` and runtime/validator provenance capture
  - final reset plus failure-cleanup reset behavior
- aligned the live validators onto shared canonical route constants from `src/gcs_api_routes.py`
- hardened runtime cleanup/finalization:
  - Drone Show now emits structured failure JSON and attempts LAND cleanup
  - Smart Swarm now restores assignments in finalization instead of success path only
  - Swarm Trajectory now snapshots/restores raw leader CSVs when using `--prepare-short-profile`
- documented the platform in:
  - `docs/guides/sitl-validation-platform.md`
  - `docs/guides/sitl-comprehensive.md`
  - `docs/README.md`
- recorded QuickScout as an explicit deferred SITL-platform domain in `docs/TODO_deferred.md`

## Validation

Local:

- `python3 -m pytest tests/test_run_sitl_validation_suite.py tests/test_validate_actions_runtime.py tests/test_validate_drone_show_runtime.py tests/test_validate_smart_swarm_runtime.py tests/test_validate_swarm_trajectory_runtime.py -q`
  - result: `56 passed`
- `python3 -m pytest tests/test_gcs_api_websocket.py -q`
  - result: `4 passed`
- `python3 tools/run_sitl_validation_suite.py --dry-run --artifact-dir /tmp/mds_sitl_dry_run_check`
  - result: passed
  - verified `/tmp/mds_sitl_dry_run_check` was not created

Hetzner:

- focused validator batch via runtime venv and `-c /dev/null`
  - result: `56 passed`
- dry-run suite on the clean synced validator checkout
  - result: passed
  - verified `/tmp/hetzner_mds_sitl_dry_run` was not created

## Important Runtime Finding

The first live Hetzner operator-regression attempt failed at the initial Drone
Show readiness gate, but the suite cleanup behaved correctly and the failure was
useful: the live GCS process was still running an old pre-modernization tree.

After restarting the old GCS process, the logs showed:

- `POST /api/v1/fleet/heartbeats -> 404`
- `GET /api/v1/origin/bootstrap -> 404`

That confirms the current live runtime tree is behind the canonical API
contract already used by the SITL containers and validation tooling. The next
required step is to move Hetzner runtime execution onto a clean current
`main-candidate` checkout before rerunning the live operator-regression suite.

## Deferred / Follow-Up

- QuickScout SITL validator/template after the subsystem itself matures
- final Hetzner live-suite rerun after the live GCS runtime is moved onto the current canonical API tree
