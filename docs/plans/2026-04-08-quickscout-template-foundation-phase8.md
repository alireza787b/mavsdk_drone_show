# QuickScout Template Foundation Phase 8

Date: 2026-04-08
Repo baseline: `30eb78d6`
Status: complete, local plus Hetzner validation green

## Goal

Introduce the first real mission-template expansion for QuickScout so the subsystem is no longer hard-wired to polygon area sweeps.

This slice establishes the foundation for template-first search planning by adding:

- explicit mission template selection in the operator workflow
- the first non-polygon search template: `last_known_point`
- durable template metadata in persisted QuickScout operations
- template-aware planning signatures, recovery, and plan recompute behavior

## What Changed

- extended [sar/schemas.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py) with:
  - `QuickScoutMissionTemplate`
  - point-search support on `SearchArea` via `center` and `radius_m`
  - durable `mission_template` fields on request, operation, and mission-summary models
- updated [sar/service.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/service.py) so QuickScout planning now:
  - resolves template-specific planning geometry before calling the planner
  - converts `last_known_point` inputs into a generated polygon search envelope for the existing planner
  - persists the operator-selected mission template and resolved search geometry for recovery
- updated [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so the workspace now:
  - tracks `missionTemplate`, `searchCenter`, and `searchRadiusM`
  - restores template-specific state from recovered workspaces
  - sends a point-centered request payload for `last_known_point`
  - suppresses polygon drawing when the active mission template is not area sweep
  - renders a dedicated search-center marker for point-centered search planning
  - handles zero-coordinate telemetry and search points correctly instead of relying on truthiness checks
- updated [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js) so planning is now template-aware:
  - template cards for `Area Sweep` and `Last Known Point`
  - point-centered search controls for center latitude/longitude and radius
  - `Use Map Center` utility for rapid operator setup
  - template-aware compute gating
- updated [quickScoutPlanningSignature.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutPlanningSignature.js) so plan freshness now includes:
  - mission template
  - search center
  - search radius
- expanded test coverage in:
  - [test_sar_schemas.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_schemas.py)
  - [test_sar_api.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_api.py)
  - [test_sar_store.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_store.py)
  - [test_gcs_sar_routes.py](/tmp/mavsdk_drone_show_resume/tests/test_gcs_sar_routes.py)
  - [QuickScoutPage.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js)
  - [quickScoutPlanningSignature.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutPlanningSignature.test.js)
- updated [QuickScout.css](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/styles/QuickScout.css) for:
  - mission-template cards
  - wide coordinate inputs
  - point-search center marker styling
- synced the clean Hetzner validation tree with the current [DronePositionMap.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/DronePositionMap.js) so the production build reflects the actual branch state instead of an older validation-tree warning

## Why This Slice Matters

Before this change, QuickScout still behaved like one planner family with extra operator chrome around it.

That was not enough for the redesigned mission-system direction because:

- operators could not choose a search doctrine explicitly
- the backend contract could not persist template identity cleanly
- the UI recovery path still assumed polygon planning as the only real geometry model
- plan freshness could not detect drift in point-centered search setup

This slice changes the shape of the subsystem:

- QuickScout is now template-first at the schema, service, and workspace level
- `last_known_point` becomes a real supported search-planning contract, not a future note in docs
- the existing coverage planner stays reusable because the service resolves template-specific geometry before planning

## Validation

Local backend validation:

```bash
python3 -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_api.py \
  tests/test_sar_store.py \
  tests/test_gcs_sar_routes.py
```

Result:

- `53` passed

Hetzner backend validation:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync
PYTHONPATH=/root/mavsdk_drone_show_main_candidate_clean_sync:/root/mavsdk_drone_show_main_candidate_clean_sync/gcs-server \
  /root/mavsdk_drone_show/venv/bin/python -m pytest -o addopts="" -q \
  tests/test_sar_schemas.py \
  tests/test_sar_api.py \
  tests/test_sar_store.py \
  tests/test_gcs_sar_routes.py
```

Result:

- `53` passed
- `1` warning from the Hetzner validation venv about unknown pytest `timeout` config

Hetzner frontend validation:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/pages/QuickScoutPage.test.js \
  src/services/sarApiService.test.js \
  src/utilities/quickScoutProfiles.test.js \
  src/utilities/quickScoutPlanningSignature.test.js \
  src/utilities/quickScoutLaunchReadiness.test.js
```

Result:

- `5` suites passed
- `21` tests passed

Hetzner production build:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
npm run build
```

Result:

- build passed

## Important Behavior Changes

- QuickScout planning is no longer implicitly polygon-only
- `last_known_point` is now a real operator-visible mission type with:
  - dedicated center/radius inputs
  - search-bar seeding
  - map-center seeding
  - persisted recovery state
- the stored workspace can now reopen the correct template and geometry model instead of coercing everything back into polygon planning
- plan staleness detection now includes point-template inputs, so changing radius or center invalidates the old package cleanly

## Remaining Debt After This Slice

- QuickScout still needs richer template-specific map visualization beyond a center marker, especially for search radius and future corridor geometry
- corridor search and standoff-observation templates are still ahead
- monitor/status doctrine is still shallower than the planned full search-operations workspace
- QuickScout SITL validator/template is still deferred until the operator workflow stabilizes further

## Recommended Next Slice

QuickScout Phase 9 should deepen the template-aware operator workflow instead of jumping straight into SITL:

- add richer map visualization for point-centered search geometry
- improve template-specific setup doctrine and operator guidance
- prepare the subsystem for corridor-search introduction without reworking the current template contract again
