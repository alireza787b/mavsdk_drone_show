# Repo Asset Layout

This guide defines where repo-managed assets live in MDS so operators,
maintainers, and AI agents do not scatter profiles, config presets, or runtime
artifacts across unrelated folders.

## Authoritative Layout

### Active Fleet Config

These are the live fleet files used by the running system:

- `config.json`
- `swarm.json`
- `config_sitl.json`
- `swarm_sitl.json`

These files are the active source of truth for the current real-mode or SITL
fleet. Do not treat sample files under `resources/` as live runtime config.

### Repo-Managed Reference Assets

`resources/` is the home for reusable reference assets that are meant to be
reviewed, committed, and reused across operators or environments.

Current asset classes:

- `resources/px4_param_profiles/`
  - approved PX4 parameter profiles for the dashboard `PX4 Parameters` page
- `resources/common_params.csv`
  - legacy compatibility bundle for the older `APPLY_COMMON_PARAMS` action path
- `resources/config_*.json` / `resources/swarm_*.json`
  - sample or preset fleet layouts for setup workflows

If a new reusable asset class is added later, it should get its own named
subdirectory under `resources/`.

### Generated Mission Artifacts

Mission-generated files live under the mode-specific shape trees:

- `shapes/`
- `shapes_sitl/`

Examples:

- Drone Show processed outputs
- Swarm Trajectory raw uploads, processed trajectories, and plots
- other mode-specific generated mission data

These are not profile libraries or long-term preset stores.

### Durable Runtime State

Runtime-owned durable state belongs under `runtime_data/`.

Examples:

- QuickScout mission database
- future subsystem-owned local stores

Use this for runtime persistence, not for checked-in presets.

### Validation Artifacts

Validation and audit runs should write to temporary artifact roots, not into the
core repo layout by default.

Examples:

- `artifacts/`
- `/tmp/...`

Keep these ephemeral or gitignored unless a workflow explicitly promotes them.

## PX4 Parameters Specific Rules

- approved fleet baselines belong in `resources/px4_param_profiles/`
- the operator-facing browser workflow is:
  - review profile
  - compare against a selected drone snapshot
  - apply in `Batch`
- the older `APPLY_COMMON_PARAMS` action remains compatibility-only and reads
  `resources/common_params.csv` by default

## Quick Rule Of Thumb

- live current fleet? root `config*.json` / `swarm*.json`
- reviewed reusable asset? `resources/`
- generated mission output? `shapes*/`
- runtime database/state? `runtime_data/`
- temporary test evidence? `artifacts/` or `/tmp`
