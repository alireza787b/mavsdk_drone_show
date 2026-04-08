# QuickScout Findings Foundation - Phase 14

Date: 2026-04-08
Branch target: `main-candidate`
Status: implemented, validated, pushed

## Goal

Replace the thin QuickScout POI demo flow with a real operator-facing findings workflow foundation while preserving runtime stability and compatibility for older callers.

## What Changed

- promoted `findings` to the canonical QuickScout operator concept in the GCS contract
- added typed finding create/update payloads and canonical `/api/sar/findings` routes
- kept `/api/sar/poi` mounted as a hidden compatibility alias instead of leaving older callers broken
- upgraded the durable QuickScout store so findings live in a dedicated `quickscout_findings` table, with automatic import from legacy `quickscout_pois`
- updated mission status and mission summaries so they expose findings cleanly while still mirroring legacy `pois` / `poi_count` fields for compatibility
- replaced the monitor-mode map marker flow with a real findings workflow:
  - mark finding from map
  - select finding from list/map
  - review/update/delete finding from a dedicated panel
- removed the redundant monitor-mode extra findings poll; the page now trusts the mission status payload as the main source of truth and only falls back to compatibility alias fields when needed
- updated the active QuickScout guide so it reflects the current template-aware, findings-aware subsystem instead of the older polygon-plus-POI PoC

## Validation

Local backend:

- `python3 -m pytest tests/test_sar_schemas.py tests/test_sar_store.py tests/test_sar_api.py tests/test_gcs_sar_routes.py --no-cov -q`
- result: `65 passed`

Hetzner frontend:

- `npm test -- --runInBand --watch=false src/services/sarApiService.test.js src/components/sar/MissionMonitorSidebar.test.js src/components/sar/FindingReviewPanel.test.js src/pages/QuickScoutPage.test.js`
- result: `4 suites passed`, `16 tests passed`

Hetzner production build:

- `CI=true npm run build`
- result: passed

## Important Operational Note

The first Hetzner build attempts looked like a build hang, but the root issue was stale orphaned CRA build workers from earlier retries. After cleaning the old `react-scripts/scripts/build.js` processes and rerunning once from a clean process set, the build finished normally. This was a host/process-cleanup issue, not a QuickScout code regression.

## Remaining QuickScout Product Work

Not finished by this checkpoint:

- evidence/media linkage on findings
- handoff/export workflow for reviewed findings
- mid-mission add/remove-drone retasking
- richer findings-aware SITL scenarios

Those remain tracked in `docs/TODO_deferred.md` and should be revisited as the next QuickScout slices rather than being hidden as accidental debt.
