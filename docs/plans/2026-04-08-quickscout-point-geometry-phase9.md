# QuickScout Point Geometry Phase 9

Date: 2026-04-08
Repo baseline: `eb92150b`
Status: complete, focused Hetzner frontend validation green

## Goal

Deepen the new `last_known_point` workflow so it is not just a backend/template contract. The operator map and planning surface now need to show the actual point-centered search footprint and explain what the package means operationally.

## What Changed

- added [quickScoutSearchGeometry.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutSearchGeometry.js) with reusable helpers for:
  - validating point-centered search coordinates cleanly
  - computing circular search footprint area
  - generating preview GeoJSON for point-centered search envelopes
- added focused utility coverage in [quickScoutSearchGeometry.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutSearchGeometry.test.js)
- updated [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so `last_known_point` planning now:
  - renders a real search-radius preview on Mapbox via `Source` / `Layer`
  - renders a real search-radius preview on Leaflet via `Circle`
  - reuses the geometry utility instead of duplicating area math inline
- updated [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js) so point-centered planning now shows:
  - derived search footprint size in hectares
  - a clearer operator note explaining that QuickScout expands the report into a search envelope before partitioning aircraft plans
- expanded [QuickScoutPage.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js) so the point-template request assertion now verifies the derived footprint area too
- updated [QuickScout.css](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/styles/QuickScout.css) with the new operator-note treatment for point-search setup

## Why This Slice Matters

After Phase 8, QuickScout could accept and persist a `last_known_point` mission, but the operator workspace still under-explained the geometry:

- the map only showed a center marker
- the sidebar showed raw inputs without enough doctrine
- the point-search footprint existed mostly as invisible backend math

That was still too close to a developer-facing demo.

This slice makes the point-centered template operationally legible:

- the map shows what the point search actually covers
- the sidebar shows the footprint scale in operator terms
- the geometry rules now live in one reusable utility instead of being split across ad hoc UI code

## Validation

Focused Hetzner frontend validation:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/pages/QuickScoutPage.test.js \
  src/services/sarApiService.test.js \
  src/utilities/quickScoutProfiles.test.js \
  src/utilities/quickScoutPlanningSignature.test.js \
  src/utilities/quickScoutLaunchReadiness.test.js \
  src/utilities/quickScoutSearchGeometry.test.js
```

Result:

- `6` suites passed
- `24` tests passed

Focused Hetzner production build:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
npm run build
```

Result:

- build passed

## Important Behavior Changes

- point-centered QuickScout planning now shows a real search footprint on the map instead of only a center marker
- the point-centered request payload still uses `type=point`, but the UI now exposes the derived footprint area explicitly
- the search-geometry math used for request area and preview visualization now comes from one shared utility

## Remaining Debt After This Slice

- corridor-search geometry and authoring are still ahead
- point-centered search still needs richer operator review once live mission execution/POI flows mature further
- QuickScout SITL validator/template is still deferred until the operator workflow stabilizes more fully

## Recommended Next Slice

QuickScout Phase 10 should introduce the next mission family instead of over-polishing the current two:

- corridor-search template foundation
- route-centered geometry input and preview
- template-aware operator setup that can expand beyond polygon versus point
