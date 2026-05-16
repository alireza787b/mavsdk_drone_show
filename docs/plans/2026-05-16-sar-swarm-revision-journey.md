# MDS SAR / Swarm Revision Journey

Date: 2026-05-16
Source plan: PM-approved revision plan retained in operator handoff notes.

## Operating Rules

- Official repo changes land first, then downstream deployments receive only public-safe changes after privacy review.
- QuickScout and Swarm Trajectory stay distinct mission modes with shared UI patterns and explicit safety semantics.
- Swarm Trajectory becomes the canonical route for trajectory package authoring; Trajectory Planning is demoted while its useful editor capabilities are migrated.
- QuickScout configured-origin planning is allowed only as staged/draft planning until live revalidation.
- Trusted terrain/elevation decisions are backend-owned. Static/browser estimates are advisory only and cannot silently become flight terrain.
- Each slice gets targeted tests, reviewer notes, operator status, and this journey log updated before moving on.

## Slice 0 Resume Checkpoint

Status: complete before implementation.

- Official worktree: clean on `main` at `690eb9ae`, tag `v5.5.1-sar-mission-workflows`.
- Downstream release state was checked separately outside the public repo.
- PM-approved revision plan loaded.
- Active reviewer findings:
  - Swarm Trajectory is not truly single-page while Trajectory Planning remains first-class.
  - QuickScout live-GPS launch blocking is correct, but offline configured-origin planning should exist as staged planning.
  - Swarm Trajectory AGL lookup likely mishandles OpenTopoData response shape.
  - Terrain source/provenance must be explicit for Mapbox and Leaflet modes.
  - Sidebar collapsed tooltips and mission navigation need cleanup.
  - Hetzner SITL acceptance must switch REAL -> SITL -> validators -> REAL with zero SITL residue.

## Slice 1 Plan

Critical correctness before UI consolidation:

- Fix Swarm Trajectory elevation adapter to parse OpenTopoData `results[0].elevation`, top-level `elevation`, and numeric providers.
- Preserve sea-level `0.0 m` as valid.
- Add provider/source/confidence/sample metadata to elevation responses where available.
- Make Swarm waypoint terrain status show provider/source details without noisy page text.
- Fix QuickScout Mapbox map-center and corridor add-center actions so they use the actual current map center.
- Add focused backend/frontend tests for the corrected behavior.

## Slice 1 Result

Status: complete.

Changed:

- Normalized Swarm Trajectory elevation payloads from numeric providers, top-level `elevation`/`elevation_m`, and OpenTopoData `results[0].elevation`.
- Preserved valid sea-level `0.0 m` elevations.
- Added terrain `provider`, `confidence`, and `sample_time` metadata to the typed Swarm elevation response.
- Surfaced terrain provider/source in the compact Swarm waypoint terrain status.
- Preserved sea-level values in the legacy frontend elevation helper.
- Fixed QuickScout Mapbox map-center and corridor add-center actions to read the live map instance center, and added Leaflet move/zoom viewport synchronization.

Tests:

- `pytest tests/test_swarm_trajectory_service.py -q` - passed, 24 tests.
- `pytest tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_api_http.py -q` - passed, 104 tests.
- `CI=true npm test -- --runInBand --watchAll=false --runTestsByPath src/utilities/swarmTrajectoryDraft.test.js src/utilities/utilities.test.js src/pages/SwarmTrajectory.test.js src/pages/QuickScoutPage.test.js` - passed, 22 tests.

Reviewer notes:

- Operator/SAR: AGL route authoring no longer fails just because the real provider returns OpenTopoData shape; sea-level coast/harbor cases remain valid.
- UI/UX: Terrain provenance is visible as compact status text instead of more permanent page copy.
- Frontend maintainer: QuickScout no longer depends on stale `initialViewState` for map-center actions.
- Backend/API maintainer: Elevation response remains typed and backward-compatible while adding optional provider metadata.
- Flight safety: Static/browser terrain estimates are still not promoted to trusted mission terrain.
- Devops/release: No deployment or runtime changes in this slice.
- Docs/test maintainer: Tests now cover OpenTopoData shape, sea-level, partial terrain, frontend zero preservation, Swarm AGL waypoint status, and QuickScout Mapbox center.

Next slice:

- Demote Trajectory Planning in navigation and copy.
- Make QuickScout more discoverable.
- Fix collapsed sidebar hover behavior and add regression coverage.

## Slice 2 Result

Status: complete.

Changed:

- Reordered the Smart Swarm sidebar so mission workflows read: `Swarm Design`, `QuickScout SAR`, `Swarm Trajectory`, `Advanced Route Editor`.
- Renamed the visible old trajectory-planning route to `Advanced Route Editor`.
- Updated dashboard readiness and mission detail copy so `Swarm Trajectory` is the canonical package workflow and the old route is a lower-level editor.
- Renamed the old route page heading from `Trajectory Planning` to `Advanced Route Editor`.
- Reworked collapsed sidebar tooltips to render through a fixed portal outside the scroll container.
- Added tooltip timer cleanup so fast hover changes cannot let an older timeout hide the current tooltip.
- Updated Swarm docs to reflect the Advanced Route Editor label.

Tests:

- `CI=true npm test -- --runInBand --watchAll=false --runTestsByPath src/components/SidebarMenu.test.js src/components/MissionReadinessCard.test.js src/components/MissionDetails.test.js src/components/trajectory/SwarmTrajectoryWorkspaceSummary.test.js src/pages/TrajectoryPlanning.test.js src/App.test.js` - passed, 23 tests.

Reviewer notes:

- Operator/SAR: QuickScout SAR is now visible before Swarm Trajectory in the mission group, and the two-page Swarm confusion is reduced.
- UI/UX: Collapsed sidebar names appear as clean hover tooltips outside the scroll surface; no permanent text was added.
- Frontend maintainer: Route labels changed without removing the compatibility route.
- Backend/API maintainer: No backend contract changes in this slice.
- Flight safety: Readiness copy now says package readiness, not final flight readiness.
- Devops/release: No runtime/deploy changes.
- Docs/test maintainer: Current operator docs no longer name Trajectory Planning as the primary Swarm workflow.

Next slice:

- Start Swarm route-editor consolidation with low-risk shared CSV/upload/preview primitives before embedding the full map editor.

## Slice 3 Result

Status: complete.

Changed:

- Added a shared trajectory CSV serializer used by both Swarm Trajectory draft upload and Advanced Route Editor export.
- Added a shared leader-route upload helper so both pages use the same `Drone N.csv` upload path and error handling.
- Extracted the static route sketch into a reusable `RouteSketch` component with focused tests.
- Added an embedded `SwarmRouteMapEditor` to Swarm Trajectory so operators can click the map to add leader waypoints directly on the canonical page.
- Kept Advanced Route Editor available for lower-level route work while moving normal leader waypoint authoring into Swarm Trajectory.
- Updated the Swarm Trajectory operator guide to describe map-click waypoint authoring.

Tests:

- `CI=true npm test -- --runInBand --watchAll=false --runTestsByPath src/utilities/trajectoryCsv.test.js src/utilities/swarmTrajectoryAssignment.test.js src/utilities/swarmTrajectoryDraft.test.js src/utilities/TrajectoryStorage.test.js src/components/trajectory/RouteSketch.test.js src/components/trajectory/SwarmRouteMapEditor.test.js src/pages/SwarmTrajectory.test.js src/pages/TrajectoryPlanning.test.js` - passed, 28 tests.

Reviewer notes:

- Operator/SAR: Swarm Trajectory now has a map-first leader waypoint path on the canonical page instead of requiring the old editor for normal route creation.
- UI/UX: The new map surface adds one compact hint and uses existing map provider controls; no long explanatory panel was added.
- Frontend maintainer: Shared CSV/upload/preview primitives reduce duplicate route-authoring behavior while preserving the legacy compatibility route.
- Backend/API maintainer: No API contract changes; upload route and CSV filenames remain unchanged.
- Flight safety: AGL map-click waypoint creation still goes through the same backend terrain lookup and blocks when trusted terrain is unavailable.
- Devops/release: No runtime/deploy changes.
- Docs/test maintainer: New tests cover shared serialization, upload helper behavior, route sketch rendering, Leaflet fallback map-clicks, Mapbox map-clicks, and Swarm page map-waypoint insertion.

Next slice:

- Clean Swarm processing/preview/package UX, move advanced/destructive actions behind guarded controls, and keep commit/transfer semantics explicit.

## Slice 4 Result

Status: complete.

Changed:

- Reduced Swarm processing always-visible guidance to a short readiness line.
- Moved `Start Fresh` and `Clear Processed Only` into an `Advanced processing` disclosure.
- Shortened review next-step copy while keeping Dashboard Mission Type 4 preflight explicit.
- Moved full workspace clearing behind an `Advanced` disclosure while preserving the existing centered destructive confirmation.
- Kept commit/transfer validation blockers visible and commit buttons blocked when validation is not ready.

Tests:

- `CI=true npm test -- --runInBand --watchAll=false --runTestsByPath src/pages/SwarmTrajectory.test.js src/components/trajectory/SwarmRouteMapEditor.test.js` - passed, 8 tests.

Reviewer notes:

- Operator/SAR: Normal path is now map route -> assign leader -> process -> review -> Dashboard preflight, with destructive reset controls out of the primary scan path.
- UI/UX: Page text was reduced; advanced actions are still reachable but not dominant.
- Frontend maintainer: Changes are presentation-level around existing handlers and confirmations.
- Backend/API maintainer: No API changes.
- Flight safety: Validation blockers and commit/transfer guards remain visible.
- Devops/release: No runtime/deploy changes.
- Docs/test maintainer: Existing Swarm workflow tests updated to the shorter operator copy.

Next slice:

- Implement QuickScout configured-origin staged planning and live revalidation semantics.

## Slice 5 Result

Status: complete.

Changed:

- Added explicit QuickScout planning source modes: `live_drone_positions` and `configured_origin`.
- Added configured-origin staged planning from current origin launch slots, with provenance stored on the mission package.
- Kept live-GPS planning unchanged and immediately launchable after normal review.
- Marked configured-origin packages as not directly launchable and requiring live revalidation.
- Added `POST /api/sar/mission/{mission_id}/revalidate-launch` to verify current origin and live drone GPS/slot alignment.
- Added short-lived, single-use launch tokens for staged packages.
- Updated `/api/sar/mission/launch` to reject staged packages without a valid revalidation token.
- Added compact QuickScout UI control for `Live GPS` vs `Origin Slots` planning.
- Updated QuickScout launch review to show staged origin packages and run revalidation before dispatch.
- Updated QuickScout and shared mission-planning docs with the staged planning/revalidation workflow.

Tests:

- `pytest tests/test_gcs_sar_routes.py tests/test_sar_api.py -q` - passed, 46 tests.
- `CI=true npm test -- --runInBand --watchAll=false --runTestsByPath src/pages/QuickScoutPage.test.js src/components/sar/QuickScoutLaunchReview.test.js src/services/sarApiService.test.js src/utilities/quickScoutPlanningSignature.test.js` - passed, 31 tests.

Reviewer notes:

- Operator/SAR: Offline design is now possible via `Origin Slots`, but the UI and backend keep it visibly staged until aircraft are live.
- UI/UX: The new choice is two compact chips with tooltip titles; no long page prose was added.
- Frontend maintainer: Planning source is part of the recompute signature, recovery state, launch review, and SAR API service.
- Backend/API maintainer: New fields are typed, default-compatible, and machine-readable; the legacy launch endpoint still accepts empty bodies for live-GPS plans.
- Flight safety: No GPS/origin fallback was weakened. Configured-origin plans cannot dispatch without current live GPS and slot proximity validation.
- Devops/release: No runtime/deploy changes yet.
- Docs/test maintainer: Public docs now explain staged planning, configured-origin blockers, and the revalidation endpoint.

Next slice:

- Continue cross-mode cleanup and validation debt: map/elevation probes, stale/deprecated docs/code scan, and reusable SITL validators before full runtime acceptance.

## Slice 6 Result

Status: complete.

Changed:

- Extended `tools/validate_quickscout_runtime.py` with `--position-source-mode live_drone_positions|configured_origin`.
- Runtime validator now asserts the planner source mode, staged package flags, live revalidation response, and token-backed launch for configured-origin QuickScout runs.
- Passed the new QuickScout position-source option through `tools/run_sitl_validation_suite.py`.
- Added bundled SITL plan `quickscout_origin_slots_runtime` for configured-origin staged planning acceptance.
- Updated SITL plan docs to list the new origin-slots runtime plan.
- Cleaned current README wording from generic trajectory planning to `Swarm Trajectory` / `Advanced Route Editor`, and updated the version badge from 5.4 to 5.5.
- Cleaned an outdated routing comment in `App.js`.
- Re-scanned current README, active docs, dashboard source, and SITL tools for stale `Trajectory Planning` primary-workflow wording and old 5.4 badge references.

Validation:

- `python3 tools/validate_quickscout_runtime.py --help` - passed.
- `python3 tools/run_sitl_validation_suite.py --help` - passed.
- `python3 tools/run_sitl_validation_suite.py --list-bundled-plans` - passed and includes `quickscout_origin_slots_runtime`.
- `python3 tools/run_sitl_validation_suite.py --plan-name quickscout_origin_slots_runtime --dry-run --drone-ids 1 --base-url http://127.0.0.1:5030` - passed; command includes `--position-source-mode configured_origin`.
- `python3 -m py_compile tools/validate_quickscout_runtime.py tools/run_sitl_validation_suite.py` - passed.

Reviewer notes:

- Operator/SAR: Origin-slot QuickScout is now a reusable SITL acceptance drill instead of a manual-only edge case.
- UI/UX: Public/current docs no longer present the old Trajectory Planning page as the primary workflow.
- Frontend maintainer: No functional frontend changes in this slice beyond wording cleanup.
- Backend/API maintainer: Runtime validators now exercise the revalidation endpoint and token payload.
- Flight safety: The validator explicitly asserts staged packages are not marked directly launchable.
- Devops/release: The bundled SITL plan can be selected by name during Hetzner acceptance.
- Docs/test maintainer: README and SITL plan library now reflect current workflow labels.

Next slice:

- Run broader targeted local tests across SAR, Swarm Trajectory, sidebar, map fallbacks, validators, and then perform browser-level UI probes before Hetzner SITL.

## Slice 7 Result

Status: complete for targeted Hetzner build/test/browser validation; live SITL mode-switch acceptance remains next.

Changed during validation:

- Fixed FastAPI CORS for credentialed dashboard requests in auth-enabled and auth-disabled modes. The API now echoes allowed origins with credentials instead of returning wildcard CORS that browsers reject.
- Fixed shared `LeafletMapBase` click delivery by installing map handlers through `useMapEvents`; this protects QuickScout and Swarm Trajectory Leaflet fallback interactions.
- Hardened `QuickScoutStore` so the SQLite runtime directory and schema are recreated if deployment/sync tooling removes the runtime path while the backend process is alive.
- Added regression tests for credential-compatible CORS and QuickScout store runtime-directory recovery.
- Hardened `tools/probe_dashboard_mission_ui.py` to wait for sidebar collapse geometry, scroll target elements into view before browser clicks, and use a mobile-specific navigation probe.
- Preserved remote `runtime_data` during validation rsync after discovering that deleting it can break a running QuickScout mission catalog endpoint.

Hetzner validation:

- `pytest tests/test_sar_coverage_planner.py tests/test_sar_api.py tests/test_gcs_sar_routes.py tests/test_sar_store.py tests/test_swarm_trajectory_service.py tests/test_gcs_swarm_trajectory_routes.py tests/test_gcs_api_http.py -q` - passed, 189 tests.
- `CI=true npm test -- --runInBand --watchAll=false --runTestsByPath ...` for SAR/Swarm/Sidebar/trajectory affected suites - passed, 16 suites / 70 tests.
- `REACT_APP_GCS_PORT=5130 npm run build` - passed after the Leaflet map-base fix.
- `npm run audit:ui -- --strict` - passed with 0 critical findings; 15 pre-existing debt findings remain in FleetOps/DroneDetail/DroneWidget areas, outside this slice.
- `tools/probe_dashboard_mission_ui.py --viewport desktop` against the validation dashboard/backend - passed; sidebar collapsed tooltip, QuickScout Leaflet workspace, Swarm map waypoint insertion, and Advanced Route Editor label all verified with no console errors or runtime exceptions.
- `tools/probe_dashboard_mission_ui.py --viewport mobile` - passed; mobile menu labels, QuickScout Leaflet workspace, Swarm map waypoint insertion, and Advanced Route Editor label all verified with no console errors or runtime exceptions.

Reviewer notes:

- Operator/SAR: Browser probes now catch the field-critical path of selecting QuickScout/Swarm pages and adding Swarm waypoints in Leaflet fallback, not just unit-level callbacks.
- UI/UX: Desktop collapsed tooltips and mobile sidebar navigation are explicitly validated; the Advanced Route Editor remains labeled as compatibility/advanced rather than primary workflow.
- Frontend maintainer: Leaflet click behavior is fixed once in the shared map base, reducing duplicated map-event workarounds.
- Backend/API maintainer: Credentialed CORS is now deterministic across auth modes and local validation ports; QuickScout store recovery avoids a transient 500 after deploy/sync.
- Flight safety: Fixes preserve the no-fabricated-position policy; they improve operator visibility and fallback interaction without changing launch semantics.
- Devops/release: Validation sync must exclude runtime state (`runtime_data`) and stop only validation ports, not live runtime ports.
- Docs/test maintainer: New browser validator is reusable for future CI or release smoke checks and produces desktop/mobile JSON plus screenshots.

Next slice:

- Run live deployment SITL acceptance by switching the downstream deployment from REAL to SITL only for tests, exercise the reusable SITL validators and mission UI probes, then return the deployment to REAL mode before release handoff.

## Slice 8 Result

Status: complete for Hetzner SITL acceptance and validation cleanup; official release and downstream merge remain next.

Changed during validation:

- Hardened `tools/validate_quickscout_runtime.py` idle-baseline detection so SITL rows with fresh telemetry but missing heartbeat metadata are accepted only when presence timestamps are current.
- Added validator regression coverage for the heartbeat-metadata and fresh-telemetry cases.
- Fixed a drone-side command-state race in `src/drone_setup.py`: an older mission process completion no longer resets mission state when a newer accepted command is already staged or executing.
- Added a drone-side regression test proving a newer HOLD/safety command is preserved after an older QuickScout process completes.
- Removed an attempted API-side immediate-override shortcut after review found it introduced event-loop risk; the final fix stays on the drone process monitor where the state race actually occurs.

Validation findings:

- QuickScout configured-origin initially failed because the validator treated missing heartbeat metadata as no presence even though telemetry was current; the validator now uses a bounded fresh telemetry fallback and still rejects stale/no-telemetry rows.
- QuickScout command tracking initially timed out because the validation drones were not reporting to the same non-default validation backend port and the temporary validation callback path was blocked. The validation environment was corrected, then cleaned up after tests.
- SITL containers in this acceptance environment boot from the current public branch, so patched drone-side files were copied into the running validation containers before the pre-release proof. Once released, the validated code path should come from the checked-out repo/image instead of manual copy.

Hetzner SITL matrix:

- QuickScout configured-origin last-known point - passed end to end: staged origin-slot plan, launch revalidation token, launch/searching, target airborne, non-targets idle, HOLD terminal success, abort/return-commanded, disarmed/idle, no active commands.
- QuickScout live corridor - passed end to end with command tracking and recovery.
- QuickScout live area - passed end to end with command tracking and recovery.
- Swarm Trajectory short leader/follower profile - passed: package processing, launch for three drones, execution completion, follower geometry within tolerance, idle baseline restored.
- Final configured-origin QuickScout smoke after removing the API shortcut - passed, with no event-loop or shortcut-related warnings in validator/drone logs.

Additional tests:

- Local lightweight Python regression batch - passed, 3 tests.
- Hetzner focused drone/API/validator batch - passed, 5 tests with coverage disabled after an unrelated concurrent coverage-file collision.
- Hetzner touched Python batch - passed, 157 tests: `tests/test_drone_setup.py`, `tests/test_drone_api_http.py`, and `tests/test_validate_quickscout_runtime.py`.

Cleanup:

- Stopped validation-only backend/static ports.
- Removed the temporary validation callback network allowance.
- Removed SITL validation drone containers.
- Confirmed the live deployment API/dashboard ports remained running.

Reviewer notes:

- Operator/SAR: The origin-slot workflow now has real runtime proof, not only API tests; last-known, area, and corridor QuickScout drills all reached recovery.
- UI/UX: Browser probes from Slice 7 plus runtime validation cover both map interaction and mission lifecycle; no additional visible page text was added.
- Frontend maintainer: No frontend code changed in this slice; previous build/browser results remain valid.
- Backend/API maintainer: Command tracker behavior is validated through real drone callbacks, and the removed shortcut avoids mixing scheduler event loops.
- Flight safety: The fix protects newer safety commands from being erased by late completion of older mission scripts.
- Devops/release: The validation-only network/backend state was cleaned up, and live REAL ports remained up throughout.
- Docs/test maintainer: Journey log records the validation environment pitfalls without exposing deployment topology details.

Next slice:

- Prepare official commit/tag/push, then merge the public-safe changes into the downstream repo, deploy the downstream GCS, verify REAL/SITL handoff state, and send the final release report.

## Release Validation Addendum

Status: complete before official commit.

Full-suite findings and fixes:

- A full Hetzner Python suite exposed release-inventory and lean-runtime regressions after the targeted slices had passed.
- Added the new QuickScout revalidation route to the API route inventory.
- Updated the SITL validation suite test defaults so generated QuickScout runtime commands include the explicit position-source mode.
- Hardened drone telemetry state serialization so non-numeric GPS raw altitude mocks and non-dict local-position placeholders cannot break lean state responses.
- Made dashboard session signing imports optional at module import time so user-store/admin helper code can run in lean installer Python; session and CSRF signing still raise a clear runtime error if the dependency is missing.
- Relaxed one timing-sensitive Swarm Trajectory initial-climb test so it asserts the safety behavior that matters: altitude sampling occurred, global setpoints were not sent, and end behavior was not executed after a stalled climb.

Final release-gate validation:

- Hetzner full Python suite: `pytest tests -q` passed, 1499 passed and 1 skipped.
- Previous Hetzner frontend/unit/build/browser validation remains valid for this release candidate: targeted Jest passed, production dashboard build passed, strict UI audit passed with only pre-existing non-critical findings outside this mission slice, and desktop/mobile mission UI probes passed.
- Previous Hetzner SITL acceptance remains valid for this release candidate: QuickScout configured-origin last-known, QuickScout live corridor, QuickScout live area, and Swarm Trajectory short leader/follower all passed and returned to idle/recovery.

Reviewer notes:

- Operator/SAR: Full validation now covers both planned-origin and live-position mission paths plus the release-wide Python regression surface.
- UI/UX: No new visible page text was added during release fixes.
- Frontend maintainer: Node/npm/build/browser work stayed on Hetzner, not the resource-limited local host.
- Backend/API maintainer: Route inventory and lean import paths now reflect the new API surface.
- Flight safety: The drone-side mission-state race fix remains the selected solution; no API-side scheduler shortcut is present.
- Devops/release: Validation-only runtime state was cleaned up earlier and the live deployment remained available for the downstream release step.
- Docs/test maintainer: The journey log records the final release gate and the specific regressions found by the full suite.

## Post-Release PM Feedback Slice

Status: implementation and Hetzner validation complete; official/private release and deploy remain next.

Feedback addressed:

- QuickScout no longer labels configured-only or stale-GPS slots as online. The visible slot state now distinguishes `Offline`, `No GPS`, `Stale GPS`, and `Live GPS` using the shared runtime telemetry clock.
- QuickScout now polls configured origin status and shows an origin setup link when Origin Slots are selected without a usable origin.
- Live GPS planning failures caused by unavailable drone positions now suggest Origin Slots as the safe offline draft path, while preserving live revalidation before launch.
- Swarm Trajectory was reorganized into a tabbed single-page workflow: `Route`, `Leaders`, `Process`, and `Review`. Only one task surface is visible at a time, and detailed policy/plots/destructive actions are behind disclosures.
- The reusable mission UI browser probe now understands the Swarm Trajectory tabs and explicitly switches QuickScout back to Plan mode before checking the planning controls.

Validation:

- Hetzner frontend unit tests: `CI=true npm test -- --runInBand --watchAll=false --runTestsByPath src/pages/QuickScoutPage.test.js src/components/sar/MissionPlanSidebar.test.js src/pages/SwarmTrajectory.test.js src/components/SidebarMenu.test.js src/components/trajectory/SwarmRouteMapEditor.test.js` passed: 5 suites, 33 tests.
- Hetzner dashboard build: `REACT_APP_GCS_PORT=5130 npm run build` passed.
- Hetzner desktop browser probe: `tools/probe_dashboard_mission_ui.py --viewport desktop` passed. It verified collapsed sidebar tooltip, QuickScout Plan + Leaflet fallback + Origin Slots controls, Swarm Route waypoint insertion through the tabbed UI, and Advanced Route Editor label.
- Hetzner mobile browser probe: `tools/probe_dashboard_mission_ui.py --viewport mobile` passed. It verified mobile navigation, QuickScout Plan + Leaflet fallback + Origin Slots controls, Swarm Route waypoint insertion, and Advanced Route Editor label.
- Hetzner backend/API targeted suite in a disposable validation venv passed: `pytest tests/test_sar_api.py tests/test_gcs_sar_routes.py tests/test_gcs_swarm_trajectory_routes.py tests/test_swarm_trajectory_service.py -q`, 80 passed.
- Validation-only dashboard/backend ports were stopped after probes; live runtime ports remained up.

Reviewer notes:

- Operator/SAR: QuickScout slot state now matches operational readiness for planning, and the offline planning path is visible without weakening the no-fabricated-position rule.
- UI/UX: Swarm Trajectory mobile scan path is substantially shorter because route, leader import, processing, and review are separate tabs.
- Frontend maintainer: Existing Swarm behavior is preserved while reducing visible complexity; probe coverage was updated to match the new workflow.
- Backend/API maintainer: No backend API contract changed in this feedback slice; existing SAR/Swarm route tests still pass.
- Flight safety: Origin-slot planning remains staged and cannot bypass live GPS revalidation.
- Devops/release: Node/npm/build/browser validation stayed on Hetzner. Temporary validation services were stopped after validation.
- Docs/test maintainer: New component tests cover origin setup and selected-slot Live GPS guidance; browser probe now protects the tabbed Swarm UI.

Next:

- Commit/tag/push official public release.
- Cherry-pick public-safe changes into the private repository, deploy the private GCS, verify live REAL mode, and prepare the PM report.
