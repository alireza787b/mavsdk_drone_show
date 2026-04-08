# QuickScout Handoff And Evidence Workflow - Phase 16

Date: 2026-04-08
Branch target: `main-candidate`
Status: implemented, validated, pending checkpoint commit

## Goal

Add the next operator-ready QuickScout layer on top of the findings workflow:

- canonical mission handoff/export data from the backend
- evidence-reference editing on findings
- compact monitor-mode handoff tooling for real operators

## What Changed

- added a canonical backend handoff bundle at
  `GET /api/sar/mission/{mission_id}/handoff`
- added typed handoff models in `gcs-server/sar/schemas.py` instead of
  generating ad hoc export payloads in the browser
- added `QuickScoutService.get_mission_handoff(...)` so handoff/export uses the
  same durable mission/findings state as the rest of QuickScout
- extended the route inventory and SAR API coverage to include the new handoff
  surface
- added a new monitor-mode `MissionHandoffPanel` for:
  - operator brief review
  - reviewed/unresolved/evidence counts
  - compact top-finding handoff rows
  - `Copy Brief`
  - `Export JSON`
- extended `FindingReviewPanel` with folded evidence-reference editing instead
  of always-visible extra form clutter
- added the canonical handoff fetch path to `sarApiService`
- updated QuickScout docs and deferred backlog so evidence refs and handoff are
  no longer tracked as missing work

## Validation

### Local backend

- `python3 -m pytest tests/test_sar_schemas.py tests/test_sar_api.py tests/test_gcs_sar_routes.py tests/test_api_route_inventory.py tests/test_gcs_api_http.py --no-cov -q`
- result: `153 passed`

### Hetzner frontend

- `CI=true npm test -- --runInBand --watch=false src/services/sarApiService.test.js src/components/sar/MissionHandoffPanel.test.js src/components/sar/MissionMonitorSidebar.test.js src/components/sar/FindingReviewPanel.test.js src/pages/QuickScoutPage.test.js`
- result: `5 suites passed`, `19 tests passed`

### Hetzner production build

- `CI=true npm run build`
- result: passed

## Remaining QuickScout Product Work

Still intentionally deferred after this checkpoint:

- mid-mission add-drone/remove-drone retasking
- deeper follow-up package generation from current airborne state
- richer findings-in-the-loop SITL drills
- later media attachment/upload on top of the now-stable evidence reference model
