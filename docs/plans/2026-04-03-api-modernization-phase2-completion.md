# API Modernization Phase 2 Completion

Date: 2026-04-03
Branch baseline: `8c0467c2` before this slice
Scope: remaining active frontend caller migration, dead legacy cleanup, and Hetzner validation hardening

## Completed In This Slice

- migrated the remaining active Drone Show pages/components onto shared GCS helpers:
  - `src/components/ImportSection.js`
  - `src/components/VisualizationSection.js`
  - `src/components/ExportSection.js`
  - `src/pages/CustomShowPage.js`
- migrated `src/pages/QuickScoutPage.js` off raw telemetry/config URL assembly onto shared fleet config/telemetry helpers
- migrated `src/components/MissionDetails.js` onto route keys for origin, deviation, show, custom-show, and swarm-leader reads
- completed the remaining Swarm Trajectory page migration in `src/pages/SwarmTrajectory.js`, including upload/remove/clear/commit/download/static-plot flows
- extended `src/services/gcsApiService.js` with the remaining show-management/static-asset helpers plus a root fix for absolute-URL passthrough
- centralized error normalization for API mutation flows via `src/services/apiError.js`
- added focused regression coverage for the newly centralized surfaces:
  - `src/services/logService.test.js`
  - `src/services/sarApiService.test.js`
  - refreshed `src/pages/SwarmTrajectory.test.js`
  - refreshed `src/services/gcsApiService.test.js`
  - refreshed `src/services/droneApiService.test.js`
- removed dead legacy frontend surfaces that were no longer routed or valid:
  - `src/pages/ImportShow.js`
  - `src/components/FileUpload.js`
  - `src/styles/ImportShow.css`
- hardened the dashboard build script for Hetzner/CI by setting:
  - `GENERATE_SOURCEMAP=false`
  - `NODE_OPTIONS=--max-old-space-size=4096`

## Why These Changes Matter

- frontend API consumption now has one current path per active domain instead of mixed page-owned URL assembly
- stale frontend compatibility code no longer obscures which Drone Show surfaces are actually live
- future auth, MCP, and automation work can target one shared contract layer instead of reverse-engineering per-page fetch logic
- Hetzner validation is now repeatable on Node 22 without ad hoc environment tweaking

## Validation

Validated on Hetzner scratch checkout `/root/mavsdk_drone_show_validation` after syncing the exact worktree and refreshing dependencies.

Focused regression suite:

- `CI=true npm test -- --runInBand --watch=false src/App.test.js src/components/MissionDetails.test.js src/components/CommandSender.test.js src/pages/SwarmTrajectory.test.js src/services/gcsApiService.test.js src/services/droneApiService.test.js src/services/logService.test.js src/services/sarApiService.test.js`
- result: `8` suites passed, `40` tests passed

Production build:

- `npm run build`
- result: compiled successfully on Hetzner after the build-script hardening

## Findings and Decisions

- the first build attempt exposed a real root issue: the Hetzner Node 22 runtime exhausted the default V8 heap during `react-scripts build`
- the correct fix for this repository was to harden the build script itself instead of relying on operators to remember manual `NODE_OPTIONS`
- the old `ImportShow` page was not just stylistically old; it was unrouted, referenced obsolete endpoints, and depended on missing style assets. Removing it was safer than migrating a dead surface
- external geocoding/elevation fetches remain intentionally external because they target third-party services rather than GCS route domains

## Next Recommended Slice

1. start backend route-domain extraction on the GCS side, using the now-centralized frontend callers as the single migration target
2. start defining canonical v1 contracts for config, origin, show-management, and swarm domains
3. add auth-ready route metadata and operator/action audit semantics while keeping auth disabled in dev/demo
4. build repeatable API-plus-SITL regression scripts on top of the centralized contract layer
