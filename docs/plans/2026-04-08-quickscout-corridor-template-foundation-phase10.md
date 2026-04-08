# QuickScout Corridor Template Foundation Phase 10

Date: 2026-04-08
Repo baseline: `a45c3a25`
Status: complete, local plus Hetzner validation green

## Goal

Introduce the next real QuickScout mission family after `last_known_point`: a route-centered `corridor_search` workflow.

This slice needed to do more than add one extra request field. QuickScout now has to support:

- a third mission template in the operator workflow
- line-based authored search input instead of only polygon or point
- a buffered corridor footprint for preview and planning
- durable recovery of authored route plus corridor width
- clean validation across backend contracts, frontend planning state, and production build

## What Changed

- extended [sar/schemas.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py) with corridor-aware search geometry:
  - `search_area.type = line`
  - `search_area.path`
  - `search_area.corridor_width_m`
- updated [sar/service.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/service.py) so QuickScout planning now:
  - resolves `corridor_search` authored line input into a buffered polygon before calling the existing planner
  - persists both the authored route and the derived polygon footprint for workspace recovery
  - removes the duplicate corridor resolver branch that had started to drift the contract
- updated [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so QuickScout planning now:
  - tracks `searchPath` and `corridorWidthM`
  - restores corridor route state from recovered workspaces
  - sends a `type=line` search-area payload for `corridor_search`
  - renders corridor footprint plus route previews on both Mapbox and Leaflet
  - routes corridor editing through the same page-level planning signature and stale-plan detection rules
- updated [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js) so operators now have:
  - a `Corridor Search` mission template card
  - route-point count, corridor width, and derived footprint readouts
  - route authoring helpers for `Add Map Center`, `Undo Last`, and `Clear Route`
  - clearer route-centered search guidance instead of polygon-only copy
- rewrote the shared map authoring components into geometry-aware QuickScout editors:
  - [SearchAreaDrawer.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/SearchAreaDrawer.js)
  - [LeafletDrawControl.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/map/LeafletDrawControl.js)
  - both now support `polygon` and `line` authoring instead of corridor trying to masquerade as polygon-only code
- expanded geometry helpers in [quickScoutSearchGeometry.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutSearchGeometry.js) with:
  - corridor path normalization
  - corridor buffered preview generation
  - derived corridor footprint area
- updated [quickScoutPlanningSignature.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutPlanningSignature.js) so corridor route and width changes invalidate stale launch packages cleanly
- expanded focused coverage in:
  - [test_sar_schemas.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_schemas.py)
  - [test_sar_api.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_api.py)
  - [test_gcs_sar_routes.py](/tmp/mavsdk_drone_show_resume/tests/test_gcs_sar_routes.py)
  - [QuickScoutPage.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js)
  - [quickScoutPlanningSignature.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutPlanningSignature.test.js)
  - [quickScoutSearchGeometry.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutSearchGeometry.test.js)
- replaced the dashboard’s umbrella Turf import with explicit subpackage imports and updated:
  - [package.json](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/package.json)
  - [package-lock.json](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/package-lock.json)
  - this fixed the CRA/Jest ESM breakage caused by `@turf/turf` while keeping the geometry helpers clean and explicit

## Why This Slice Matters

After Phase 9, QuickScout could handle:

- polygon area sweep
- point-centered last-known-point search

That was still not enough for the actual search-operations direction. Real operators also need route-centered packages for:

- shoreline sweeps
- trail or road search
- trackline or corridor reassessment
- constrained route search around a moving or last-reported contact path

This slice changes QuickScout from “polygon plus one special point mode” into a genuinely template-aware planning surface.

The planner contract stays disciplined:

- authored operator geometry can vary by mission template
- the planner still receives one canonical polygon footprint
- workspace recovery retains both authored inputs and derived planning geometry

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

- `57` passed

Hetzner backend validation:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync
/root/mavsdk_drone_show_phase5_live/.venv/bin/python -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_api.py \
  tests/test_sar_store.py \
  tests/test_gcs_sar_routes.py
```

Result:

- `57` passed

Hetzner frontend validation:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/pages/QuickScoutPage.test.js \
  src/utilities/quickScoutPlanningSignature.test.js \
  src/utilities/quickScoutSearchGeometry.test.js
```

Result:

- `3` suites passed
- `15` tests passed

Hetzner production build:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
npm run build
```

Result:

- build passed

## Important Behavior Changes

- QuickScout now supports `corridor_search` as a real mission template
- corridor planning stores and reopens:
  - the authored route
  - the corridor width
  - the derived buffered search footprint
- corridor geometry no longer depends on polygon-only authoring assumptions
- route and width changes now invalidate stale plans cleanly
- the dashboard geometry utilities no longer rely on the Jest-hostile `@turf/turf` umbrella import

## Remaining Debt After This Slice

- corridor search still needs deeper mission-doctrine work around launch review, monitor semantics, and future search-template selection logic
- QuickScout still does not have SITL validation coverage yet
- standoff-observation / sector-search style templates are still ahead
- monitor-mode workflow is still lighter than the planned full search-operations workspace

## Recommended Next Slice

QuickScout Phase 11 should build on this corridor foundation instead of jumping to SITL too early:

- improve template-aware launch review and execution doctrine
- deepen corridor-specific operator review before launch
- prepare the subsystem for future sector/standoff templates without reworking the template contract again
