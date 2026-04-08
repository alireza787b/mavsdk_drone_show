# QuickScout Findings Cleanup And Follow-Up - Phase 15

Date: 2026-04-08
Branch target: `main-candidate`
Status: implemented, validated, pushed

## Goal

Finish the active QuickScout findings cleanup by removing the remaining public
POI terminology and add the first operator-facing follow-up search workflow
seeded directly from a reviewed finding.

## What Changed

- removed the public `/api/sar/poi*` route family; QuickScout findings now use
  `/api/sar/findings*` only
- removed the active `pois` / `poi_count` mirrors from QuickScout mission
  status and mission summary contracts
- renamed the remaining schema enums to `FindingType` and `FindingPriority`
  instead of keeping `POI*` names inside the canonical model
- removed the older QuickScout POI compatibility wrappers from the active
  backend/frontend service surfaces
- deleted the unused `gcs-server/sar/poi_manager.py` compatibility facade
- added monitor-mode review actions so operators can:
  - center the map on the selected finding
  - seed a new `last_known_point` follow-up plan directly from that finding
- fixed the page-level map focus flow so monitor actions and follow-up planning
  use one shared `focusMap(...)` helper instead of inconsistent viewport-only
  updates
- updated the active QuickScout docs and deferred backlog to reflect the new
  findings-only terminology and the delivered follow-up search seeding flow

## Validation

### Local backend / route inventory

- `python3 -m pytest tests/test_sar_schemas.py tests/test_sar_store.py tests/test_sar_api.py tests/test_gcs_sar_routes.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py --no-cov -q`
- result: `152 passed`

### Hetzner frontend

- `CI=true npm test -- --runInBand --watch=false src/services/sarApiService.test.js src/components/sar/MissionMonitorSidebar.test.js src/components/sar/FindingReviewPanel.test.js src/pages/QuickScoutPage.test.js`
- result: `4 suites passed`, `17 tests passed`

### Hetzner production build

- `CI=true npm run build`
- result: passed

## Validation Notes

- The first paired Hetzner frontend run exposed a real regression in the new
  follow-up workflow: when monitor mode had a single visible mission in the
  catalog but no explicit `currentMissionId`, the seeded follow-up plan fell
  back to the generic `QuickScout follow-up` label instead of preserving the
  mission label.
- The follow-up seed handler now falls back to the singleton catalog mission
  label or mission ID when an explicit current mission context is not yet
  attached.
- The clean Hetzner validation tree needed a fresh `npm ci` before the frontend
  pass because it was created as a new detached worktree with no preinstalled
  dashboard dependencies.

## Remaining QuickScout Product Work

Still deferred after this checkpoint:

- richer evidence/media linkage on findings
- operator handoff/export workflow for reviewed findings
- add-drone/remove-drone retasking during active QuickScout missions
- deeper follow-up package generation from current airborne state beyond the
  new finding-seeded plan handoff
- richer findings-aware SITL drills
