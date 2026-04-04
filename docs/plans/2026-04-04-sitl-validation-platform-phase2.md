# 2026-04-04 SITL Validation Platform Phase 2

## Summary

This checkpoint extends the reusable SITL validation platform with a dedicated
Mission Config / swarm / origin runtime validator and proves the updated default
operator regression end to end on Hetzner.

The main acceptance result is:

- local focused tool/backend batch: `19 passed`
- live Hetzner operator regression suite: `passed`
- Hetzner post-suite runtime state: `/health=ok`, `commands/active=0`, drones `1/2/3` idle, disarmed, and `readiness=ready`

## What Changed

- added `tools/validate_configuration_runtime.py`
  - validates fleet collision warnings through the validation-only route
  - validates metadata-preserving fleet config save/load round-trip
  - validates full swarm config save plus assignment patch round-trip
  - validates origin compute/save/bootstrap/global-origin/deviations
  - restores original fleet config, swarm config, and exact `data/origin.json` state
- extended `tools/run_sitl_validation_suite.py`
  - new validator mode: `configuration`
  - new template: `config_only`
  - default `operator_regression` is now:
    - `reset_before_suite`
    - `configuration`
    - `reset_before_drone_show`
    - `drone_show`
    - `actions`
    - `smart_swarm`
    - `swarm_trajectory`
    - `reset_after_suite`
- hardened suite provenance collection so non-git validator roots no longer emit noisy git stderr
- added shared route constants for the canonical fleet/origin/GCS-config routes used by the new validator
- updated the fleet-config write path so `PUT /api/v1/config/fleet?commit=false` cleanly bypasses git auto-push on writable hosts

## Why It Matters

This closes a real gap in the reusable acceptance gate. Before this slice, the
suite covered mission execution well but did not prove that the operator-facing
configuration workflows stayed safe and reversible under live GCS conditions.

The new validator makes the default suite closer to the real operator flow:

1. validate configuration/origin changes
2. reset back to clean launch geometry
3. validate Drone Show
4. validate standalone action controls
5. validate Smart Swarm
6. validate Swarm Trajectory

## Host Layout Policy

The validation platform is intentionally host-agnostic.

Supported layouts:

- same-host: `validator_root == repo_root`
- split-root: validator tools run from a temporary checkout while live runtime
  state comes from another repo path
- remote-host: `base_url` points at another GCS host while the validator runs
  from a local or secondary checkout

The suite contract is:

- `--base-url`
- `--validator-root`
- `--repo-root`
- relevant `MDS_*` runtime env

It is not tied to one VPS or one repo path pattern.

## Deferred Follow-Ups

- QuickScout validator/template remains intentionally deferred until the mission
  subsystem itself is mature enough for deterministic acceptance
- advanced mixed-mode / fault-injection SITL plans remain deferred until the
  stable core operator regression is used across more checkpoints

## Key Artifacts

- live suite artifact dir:
  - `/tmp/mds_sitl_suite_validation/operator-regression-config`
- live suite summary:
  - `/tmp/mds_sitl_suite_validation/operator-regression-config/suite-summary.json`
- validator docs:
  - `docs/guides/sitl-validation-platform.md`
  - `docs/guides/sitl-comprehensive.md`
  - `docs/superpowers/specs/2026-03-26-ai-agent-sitl-audit-loop.md`
