# SITL Validation Platform

Use the SITL validation platform when you want repeatable end-to-end runtime
checks against a live GCS plus PX4/Gazebo fleet instead of ad hoc one-off test
runs.

It is designed for three use cases:

- manual operator or maintainer validation
- AI-agent execution with stable artifacts and machine-readable reports
- future CI/CD promotion gates on a dedicated Ubuntu/SITL host

The platform is intentionally host-agnostic:

- same-host local validation where the validator tools and live runtime share one repo path
- split-root validation where a temporary validator checkout targets a different live runtime repo
- remote VPS validation where `--base-url` points at another host while the validator runs locally or from a second checkout on that host

## What It Covers Today

The current reusable validators cover:

- `configuration`
  - fleet config validation-only collision checks, metadata-preserving config round-trip, swarm assignment round-trip, origin compute/save/bootstrap/global-origin checks, and exact cleanup restore
- `drone_show`
  - SkyBrush import, metadata, launch readiness, global/manual/local/custom flows, and override drill
- `actions`
  - TAKEOFF, HOLD, completed `PRECISION_MOVE`, interrupted `PRECISION_MOVE -> HOLD`, targeted RTL override, remaining-drone LAND, and idle cleanup
- `smart_swarm`
  - takeoff, cluster start, settle, reassignment, leader RTL, follower hold, and assignment restore
- `swarm_trajectory`
  - deterministic short-profile generation, processing, launch, formation validation, and cleanup
- `integrated_runtime`
  - Smart Swarm cluster start, in-flight reassignment, leader-only Swarm Trajectory override, HOLD supersession, leader Precision Move, and clean restore/land
- `quickscout`
  - deterministic `last_known_point` plan, targeted launch acceptance, airborne confirmation for targeted drones, non-target idle confirmation when applicable, HOLD, honest `replan_required` resume behavior, abort/end behavior, and clean fleet reset

## Built-In Templates

List the built-in templates:

```bash
python3 tools/run_sitl_validation_suite.py --list-templates
```

Current templates:

- `operator_regression`
  - reset, Mission Config/origin validation, reset-before-Drone-Show, Drone Show, standalone actions, Smart Swarm, Swarm Trajectory, QuickScout
- `mission_regression`
  - reset, Drone Show, Smart Swarm, Swarm Trajectory, QuickScout
- `actions_only`
  - reset plus the standalone action drill only
  - covers TAKEOFF, HOLD, Precision Move completion, Precision Move interrupt via HOLD, targeted RTL override, and LAND cleanup
- `config_only`
  - reset plus the Mission Config / swarm / origin validator only
- `quickscout_only`
  - reset plus the dedicated QuickScout runtime validator only

## Bundled Plan Library

The suite also ships with checked-in JSON plans under:

- `tools/sitl_plans/`

List them:

```bash
python3 tools/run_sitl_validation_suite.py --list-bundled-plans
```

Run one by name:

```bash
python3 tools/run_sitl_validation_suite.py \
  --plan-name operator_regression \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Current checked-in stable plans:

- `config_roundtrip`
- `config_then_drone_show`
- `drone_show_matrix`
- `actions_core`
- `smart_swarm_runtime`
- `swarm_trajectory_short_profile`
- `quickscout_runtime`
- `mission_regression`
- `operator_regression`

Current validated advanced plans:

- `integrated_mixed_mode`
- `quickscout_multi_runtime`
- `advanced_operator_regression`

These plans are meant to be edited, copied, or used as the starting point for
new scenario files. They are intentionally stored in git so operators, CI, and
AI agents all use the same scenario definitions.

## Common Commands

Run the default operator-grade regression suite on a same-host stack where the
validator tools and the live runtime share one repo checkout:

```bash
python3 tools/run_sitl_validation_suite.py \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run only the configuration/origin gate:

```bash
python3 tools/run_sitl_validation_suite.py \
  --template config_only \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

For deterministic promotion-style validation on a long-lived VPS, pin the
runtime to a freshly rebuilt image and disable mutable boot-time sync:

```bash
export MDS_DOCKER_IMAGE=mavsdk-drone-show-sitl:debug-<commit>
export MDS_SITL_GIT_SYNC=false
export MDS_SITL_REQUIREMENTS_SYNC=false
bash multiple_sitl/create_dockers.sh 3
python3 tools/run_sitl_validation_suite.py \
  --template operator_regression \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run only the mission-family validators:

```bash
python3 tools/run_sitl_validation_suite.py \
  --template mission_regression \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run only the standalone action/control drill:

```bash
python3 tools/run_sitl_validation_suite.py \
  --template actions_only \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run the dedicated QuickScout runtime gate:

```bash
python3 tools/run_sitl_validation_suite.py \
  --template quickscout_only \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run the validated mixed-mode operator drill directly:

```bash
python3 tools/run_sitl_validation_suite.py \
  --plan-name integrated_mixed_mode \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run the broader advanced promotion-style regression:

```bash
python3 tools/run_sitl_validation_suite.py \
  --plan-name advanced_operator_regression \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run the checked-in QuickScout runtime plan directly:

```bash
python3 tools/run_sitl_validation_suite.py \
  --plan-name quickscout_runtime \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

Run the validated multi-drone QuickScout runtime plan directly:

```bash
python3 tools/run_sitl_validation_suite.py \
  --plan-name quickscout_multi_runtime \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

If the validator tooling is being executed from a temporary checkout but the
live GCS/SITL runtime uses a different repo path, pass both roots explicitly:

```bash
python3 tools/run_sitl_validation_suite.py \
  --base-url http://127.0.0.1:5000 \
  --validator-root /root/mavsdk_drone_show_validator_sync \
  --repo-root /root/mavsdk_drone_show_main_candidate_runtime_live \
  --drone-ids 1 2 3
```

If the validator is not running on the same host as the GCS, point `--base-url`
at the reachable remote API instead of hardcoding localhost:

```bash
python3 tools/run_sitl_validation_suite.py \
  --base-url http://GCS_HOST_OR_IP:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

`--validator-root` tells the suite where to execute the Python tooling from.
`--repo-root` tells the suite which runtime repo owns the live mission files,
shared Swarm Trajectory workspace, and reset scripts. They may be the same path
or different paths.

`--plan-name` resolves one of the checked-in JSON plans from `tools/sitl_plans`.
Use `--plan-file` only when you intentionally want an external or temporary
scenario file.

## Declarative JSON Plans

Use `--plan-file` when you want a reusable custom sequence with step-local drone
selection or validator overrides.

Example:

```json
{
  "steps": [
    {
      "validator": "actions",
      "options": {
        "actions_takeoff_min_gain": 5.0
      }
    },
    {
      "kind": "reset",
      "name": "mid_suite_reset",
      "drone_ids": [1, 2, 3]
    },
    {
      "validator": "swarm_trajectory",
      "name": "trajectory_short_profile",
      "drone_ids": [1, 2, 3],
      "options": {
        "prepare_short_profile": false,
        "trajectory_formation_timeout": 180
      }
    }
  ]
}
```

Run it:

```bash
python3 tools/run_sitl_validation_suite.py \
  --base-url http://127.0.0.1:5000 \
  --validator-root /tmp/mavsdk_drone_show_resume \
  --repo-root ~/mavsdk_drone_show \
  --plan-file /tmp/mds-sitl-plan.json
```

Plan rules:

- each step must be a JSON object
- validator steps use `"validator": "configuration" | "drone_show" | "actions" | "smart_swarm" | "swarm_trajectory" | "integrated_runtime" | "quickscout"`
- reset steps use `"kind": "reset"`
- `drone_ids` is optional per step and defaults to the global `--drone-ids`
- `options` is optional and overrides the corresponding suite CLI defaults for that step only

The plan loader ignores extra top-level metadata fields such as `title`,
`description`, or `tags`, so checked-in library plans can stay documented
without affecting execution.

## Configuration Gate Behavior

The `configuration` validator is intentionally mutation-safe for live systems:

- fleet-config and swarm-config round-trip saves use `commit=false`, so a live GCS with `git_auto_push=true` does not create accidental commits during validation
- the validator snapshots and restores the exact local `data/origin.json` presence/content, so a host that normally relies on the packaged SITL default origin does not get left with an unintended runtime override file
- the operator regression template inserts a protective `reset_before_drone_show` after the configuration gate, so any temporary config/origin writes cannot contaminate later Drone Show launch geometry

## Dry-Run and Provenance

Use `--dry-run` when you want the resolved plan, commands, and plan hash without
changing the runtime host:

```bash
python3 tools/run_sitl_validation_suite.py --dry-run
```

Dry-run is side-effect free:

- no artifact directory is created
- no validator JSON report is written
- no SITL reset or mission command is dispatched

Real runs record provenance in `suite-summary.json`, including:

- `plan_hash`
- validator repo path/head/branch/dirty state when available
- runtime repo path/head/branch/dirty state when available
- Python executable/version
- selected `MDS_*` environment variables relevant to SITL/runtime sync

Plain synced validator copies are supported. In that case the validator git
metadata is simply `null` instead of emitting noisy git errors. For the best
provenance on remote hosts, still prefer actual git checkouts for both the
validator tree and the live runtime tree when that is practical.

## Artifacts

Each suite run writes one artifact directory containing:

- per-step logs
- per-validator JSON reports
- `suite-summary.json`

Default location:

- `<validator_root>/artifacts/sitl-validation/<timestamp>`

Default cleanup policy:

- reset before the suite starts
- protective reset before any late Drone Show step
- final reset after the suite ends
- failure cleanup reset if a step aborts before the final reset

## Container Lifecycle Policy

For routine deterministic regression runs, the clean policy is:

- recreate the selected SITL fleet at the start of the suite
- recreate again before any late Drone Show step after another mission family
- recreate again at the end of the suite

This is the default suite behavior and it is the recommended promotion-grade
path.

Why:

- Drone Show is launch-geometry sensitive
- Smart Swarm and Swarm Trajectory intentionally leave drones in valid but
  different post-mission geometry
- long-lived mutable containers can accumulate runtime state that is irrelevant
  to the code under test

For fast local inner-loop debugging, reusing an already running fleet is still
acceptable when you are deliberately testing one narrow validator and you
understand the state you are inheriting. That is a development convenience, not
the acceptance-grade default.

## Recommended Workflow

1. Keep a clean validation checkout for tooling changes.
2. Keep the live runtime checkout separate when the host service is serving from a different repo path.
3. Use the built-in templates for routine gates.
4. Use JSON plans only for intentional scenario experiments or regression additions.
5. Keep generated runtime artifacts outside git-tracked paths unless you are deliberately curating a fixture.
6. Keep the live GCS checkout on the same API contract generation as the SITL containers; stale pre-modernization GCS trees will reject the new canonical heartbeat/bootstrap routes.
7. For promotion-grade runs on a persistent host, prefer a freshly rebuilt image plus `MDS_SITL_GIT_SYNC=false` and `MDS_SITL_REQUIREMENTS_SYNC=false`; mixed baked-image content and mutable boot sync can hide or create false runtime failures.
8. Do not hardcode a specific VPS or hostname into plans, docs, or wrappers; the reusable contract is `base_url + validator_root + repo_root + MDS_*` env, whether the runtime is localhost, a second repo on the same host, or a remote validation server.

## Stable Vs Advanced Scenarios

The current bundled library contains only stable deterministic scenarios. More
aggressive combined-mode and fault-injection drills are intentionally tracked as
deferred work until they stay repeatable enough for routine acceptance use.

That boundary matters:

- stable plans should be safe to run after normal code changes
- advanced combined tests should challenge the system harder, but they should
  not create flaky routine gates until their acceptance contract is proven
