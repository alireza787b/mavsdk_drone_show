# API Modernization Phase 2 Checkpoint

Date: 2026-04-03
Branch baseline: `60409af7` before this slice
Scope: core frontend caller centralization and validation

Follow-up: this checkpoint was completed later the same day by `2026-04-03-api-modernization-phase2-completion.md`, which closes the remaining active caller migrations, removes dead legacy frontend surfaces, and hardens the Hetzner build path.

## Completed In This Phase

- introduced `app/dashboard/drone-dashboard/src/services/gcsApiService.js` as the shared semantic route map and HTTP helper layer for the active GCS dashboard flows
- extended the shared service with core helpers for fleet telemetry, config, swarm config, git status, repo sync, origin, deviations, GCS config, command status/history, and the first swarm-trajectory service wrappers
- migrated the highest-traffic dashboard consumers off ad hoc path strings:
  - `pages/Overview.js`
  - `pages/MissionConfig.js`
  - `pages/SwarmDesign.js`
  - `pages/GlobeView.js`
  - `components/DroneDetail.js`
  - `components/GitInfo.js`
  - `components/SyncWarningBanner.js`
  - `hooks/useSyncDrones.js`
  - `hooks/useComputeOrigin.js`
  - `utilities/missionConfigUtilities.js`
  - `services/droneApiService.js`
- kept legacy backend compatibility intact by routing those callers through one service layer instead of renaming backend contracts mid-slice
- added focused service tests:
  - `src/services/gcsApiService.test.js`
  - `src/services/droneApiService.test.js`
- fixed a real mixed-response bug in `getSwarmClusterStatus()` so it now accepts either raw axios responses or already-unwrapped payloads consistently

## Validation

Frontend validation in this slice was run on Hetzner, not the local scratch checkout, because the local recovery checkout does not have an installed `react-scripts` toolchain.

Validated on Hetzner:

- `CI=true npm test -- --runInBand --watch=false src/App.test.js src/components/MissionDetails.test.js src/components/CommandSender.test.js src/services/gcsApiService.test.js src/services/droneApiService.test.js`
- result: `5` suites passed, `24` tests passed
- `npm run build`
- result: production dashboard bundle compiled successfully

## Why This Phase Matters

- phase 1 defined the canonical `/api/v1/...` target and froze the live route inventory
- phase 2 removes the main frontend obstacle to later route cleanup: active callers are now concentrated behind a shared service layer instead of being scattered across pages, hooks, and utilities
- this is the prerequisite for safe canonical-route rollout, MCP-oriented metadata cleanup, and repeatable API regression testing

## Remaining Phase 2 Follow-Up

- migrate the remaining dynamic swarm-trajectory page routes in `pages/SwarmTrajectory.js`
- centralize `services/logService.js` and `services/sarApiService.js`
- centralize show-management/import/download/static-plot URL builders in the Drone Show pages/components
- classify stale frontend route consumers and remove dead compatibility code where safe

## Planned Next Slices

1. finish the remaining frontend caller migration domains listed above
2. move configuration/origin/swarm/git/show-management backend domains toward canonical `/api/v1/...` routes while preserving compatibility aliases
3. add repeatable API/SITL regression flows on top of the centralized service contract
