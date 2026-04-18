# Phase 1 Tester Feedback Response

Date: 2026-04-18

## Scope

This checkpoint responds to the first Phase 1 tester feedback pass after the
`v5.1.2-dashboard-command-flow` handoff. The goal was to remove ambiguity from
the command workflow, fix concrete map/globe issues, and clarify custom/private
repo credential handling without mixing customer-specific data into official
MDS.

## Findings

- The observed `CUSTOM_CSV_DRONE_SHOW` rejection was a real drone-side `E203`
  state guard. A drone already executing Smart Swarm rejects Custom CSV until
  Smart Swarm is explicitly stopped or overridden on that same drone.
- Mixed leader/follower demos should start Smart Swarm on followers only. The
  leader can then fly Custom CSV, jog, manual, or another mission while followers
  track its telemetry.
- The 3D globe was mapping valid state `0` to `UNKNOWN` because the view model
  used `||` instead of nullish handling.
- Globe motion looked jumpy because drone mesh smoothing and camera target
  updates were competing with hard target resets.
- Mobile toasts were anchored at the same top area as the hamburger menu.
- The Leaflet launch-map icon builders returned `undefined`; they built icons
  but did not return them.
- The current repo has no managed asset-library workflow for custom 2D/3D drone
  marker uploads. A lightweight `marker_color` override is safe now; full file
  uploads need a dedicated validation and asset-management slice.

## Changes Made

- Moved Dispatch Scope directly under the Command Control header when expanded.
- Kept Preflight and Fleet Overview separate because they answer different
  questions: Preflight is command-scope readiness, Fleet Overview is global
  fleet health.
- Added Smart Swarm warnings when the selected scope includes a top leader.
- Added a regression test proving Custom CSV is rejected while Smart Swarm is
  active on the same drone.
- Fixed globe state labels and map popups to show readable mission state names.
- Added smoothed globe camera target updates and kept drone position lerp.
- Added `marker_color` as a supported lightweight config override for globe and
  map markers.
- Added Mapbox setup docs, `.env.example`, and a setup link in the fallback
  banner.
- Moved mobile toasts to the lower viewport so they do not block navigation.
- Fixed launch-map Leaflet icon return values.
- Documented private repo credential best practice:
  GCS may have write credentials; drones/SITL should use least-privilege
  read-only access where possible.

## Deferred By Design

Full custom marker asset uploads are not included in this checkpoint. The safe
design is a managed asset library with type validation, size limits, preview,
reuse, and delete/revert controls. Recommended first formats:

- 2D: SVG or PNG, with SVG sanitization before serving
- 3D: GLB only, with size limits and server-side validation

This avoids arbitrary file paths in fleet config and keeps future Mapbox,
Leaflet, 3D Globe, QGC-style web dashboard, and Auterion-style operator views
compatible.

## Verification

- Official command regression: `58 passed, 1 skipped`
- Official dashboard focused regression: `15 passed`
- Official globe/map related regression: `4 passed`
- Private command regression after sync: `58 passed, 1 skipped`
- Private dashboard focused regression after sync: `15 passed`
- Private globe/map related regression after sync: `4 passed`

The local CRA production build check remained inconclusive in the sandbox: it
stayed at `Creating an optimized production build...` for several minutes
without an error. The deploy gate remains the live server rebuild/restart check.
