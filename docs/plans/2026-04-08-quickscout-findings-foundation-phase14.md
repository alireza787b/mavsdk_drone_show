# QuickScout Findings Foundation Phase 14

Status: Completed checkpoint

Commit target: post-`99db9361`

## Goal

Finish the half-complete QuickScout POI-to-findings pivot so the subsystem has:

- canonical typed finding routes
- a durable store that no longer depends on the legacy POI table name
- a monitor workflow that treats findings as first-class operator objects
- one container-owned mutation path instead of leaf UI components making ad hoc writes

## What Changed

- added typed finding payload models in [schemas.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py):
  - `QuickScoutFindingCreate`
  - `QuickScoutFindingUpdate`
- tightened [routes.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/routes.py) so canonical `/api/sar/findings` create/update now use typed request bodies instead of raw dicts
- updated [service.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/service.py) so finding create/update accept the typed models cleanly while older POI compatibility wrappers still resolve through the same service logic
- migrated [store.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/store.py) to a real `quickscout_findings` table with automatic one-way import from legacy `quickscout_pois`
- removed the redundant QuickScout findings poll in [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js); monitor mode now rehydrates findings directly from mission status instead of making a second request every poll cycle
- moved save/delete ownership for finding edits back into [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so the page container remains the single mutation path
- kept the richer findings UI flow active through:
  - [FindingMarkerSystem.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/FindingMarkerSystem.js)
  - [LeafletFindingMarkers.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/map/LeafletFindingMarkers.js)
  - [FindingReviewPanel.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/FindingReviewPanel.js)
  - [MissionMonitorSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionMonitorSidebar.js)
- kept the obsolete POI-only marker components retired from the active UI path

## Why This Slice Matters

Before this checkpoint QuickScout findings were in an awkward middle state:

- the backend already exposed findings semantics in places, but route inputs were still weakly typed
- persistence still wrote to `quickscout_pois`
- the page still burned extra polling bandwidth on a second findings request
- the review panel still performed its own API writes instead of feeding one page-owned data flow

That was enough to keep the subsystem functional, but not clean enough for the production-level QuickScout direction we are aiming at.

## Validation

Local backend:

- `python3 -m pytest tests/test_sar_api.py tests/test_gcs_sar_routes.py tests/test_sar_schemas.py tests/test_sar_store.py --no-cov -q`
- result: `65 passed`

Hetzner frontend/build validation from a clean temp checkout:

- `CI=true npm test -- --runInBand --watch=false src/services/sarApiService.test.js src/components/sar/MissionMonitorSidebar.test.js src/components/sar/FindingReviewPanel.test.js src/pages/QuickScoutPage.test.js`
- result: `4` suites passed, `16` tests passed
- `npm run build`
- result: compiled successfully

## Remaining QuickScout Work After This Checkpoint

This slice closes the findings foundation, not the whole QuickScout program.

The highest-value remaining product slices are:

1. evidence workflow
   - operator evidence references
   - later image/media linkage
   - export/handoff posture
2. richer mission control
   - add/remove drones mid-mission
   - follow-up package generation from hold/current state
3. broader SITL scenarios
   - corridor live validator
   - findings-in-the-loop drills
   - add/remove-drone and override drills

## Notes

- legacy `/api/sar/poi*` compatibility remains mounted deliberately, but canonical caller and doc direction is now `/api/sar/findings*`
- this checkpoint keeps QuickScout aligned with the earlier API/MCP discipline: typed mission objects, durable identifiers, low hidden state, and operator-facing status instead of log scraping
