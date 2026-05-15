# MDS SAR Mission Workflow Redesign Decision Memo

Date: 2026-05-15
Status: Slice 0 approval checkpoint
Scope: QuickScout, Swarm Trajectory, shared mission planning UI, planning APIs, operator documentation, test and release gates.

## Decision

Keep QuickScout and Swarm Trajectory as separate mission modes with shared planning foundations.

QuickScout remains the fast SAR/surveillance dispatch workflow that produces PX4 Mission-style autonomous waypoint missions. Swarm Trajectory remains the precise MDS trajectory/offboard-style workflow that produces processed per-drone trajectories, leader/follower outputs, and explicit transfer/commit semantics. The two modes will share the map workspace, geometry editing, drone selection, altitude controls, progress dialogs, review dialogs, error display, and job-status UI, but they will not share launch semantics or hide the difference between PX4 Mission and MDS trajectory execution.

This phase should partially merge the operator experience by moving Swarm Trajectory toward a single-page planning workflow and by reusing shared components with QuickScout. It should not perform a deep backend consolidation that makes SAR mission planning and offboard trajectory processing look like the same operation. Backend APIs can share a common error and long-running job model while keeping separate namespaces and typed payloads.

## Baseline Audit

Clean implementation will use a fresh official checkout, not the active dirty root worktree. Public main and main-candidate were aligned at the v5.4.0 branding handoff baseline. A downstream private checkout was verified separately for later merge and deployment after public privacy review.

Current QuickScout data flow:

1. The dashboard loads drone config and telemetry.
2. The operator chooses a template: area sweep, last-known-point search, or corridor search.
3. The UI collects geometry and options, then calls `POST /api/sar/mission/plan`.
4. The backend reads live telemetry positions, computes a coverage plan, optionally applies terrain-following, persists the mission, and returns mission waypoints and estimates.
5. Launch submits tracked commands for selected drones.
6. `quickscout_mission.py` uploads the waypoint mission through MAVSDK Mission, starts PX4 Mission execution, reports progress, and performs the configured return behavior.
7. The dashboard monitors progress, findings, handoff, and abort/recovery actions.

Current QuickScout issues to fix:

- Last-known-point planning can be seeded through forms/search, but map click selection is not wired.
- Multi-vertex corridor geometry is partly present, and the backend can buffer a line, but the operator interaction is not clear enough and needs end-to-end validation.
- Planning is synchronous with a frontend timeout. There is no server-side progress, cancellation, or phase status.
- Terrain lookup failure is silently downgraded to cruise altitude in the planner.
- Telemetry positions are accepted if latitude/longitude are present, without rejecting stale, invalid, or default `(0, 0)` values.
- The page is verbose, review is inline, and abort still uses a browser confirm in shared mission controls.

Current Swarm Trajectory data flow:

1. `TrajectoryPlanning` supports map waypoint authoring, import/export, assignment, and terrain context.
2. `SwarmTrajectory` supports leader CSV upload, processing, status/recommendation review, generated downloads, clear/reset, and commit.
3. FastAPI routes under `/api/v1/swarm-trajectories` call trajectory service and processor functions.
4. The processor expands leader routes into smoothed per-drone outputs, follower offsets, plots, and metadata.
5. Dashboard mission launch submits `Mission.SWARM_TRAJECTORY` targets only after target-scope validation confirms required processed outputs.
6. `swarm_trajectory_mission.py` executes processed drone CSVs through MAVSDK Offboard-style setpoints with preflight and synchronized-start gates.

Current Swarm Trajectory issues to fix:

- The workflow is split across pages and feels disconnected from route authoring to execution.
- `SwarmTrajectory` has no integrated map preview/edit surface.
- Processing is synchronous from the UI perspective and lacks a real job/progress/cancel contract.
- Terrain/altitude behavior is clearer in `TrajectoryPlanning` than in processing, preview, and commit.
- Leader/follower and cluster visualization are mostly textual instead of map-first.
- Documentation describes the split workflow and is stale for the desired operator model.

## External Design Constraints

The redesign will use these references as constraints, not copied content:

- PX4 Mission mode requires a global 3D position estimate and is automatic once engaged: https://docs.px4.io/main/en/flight_modes_fw/mission.html
- PX4 Offboard mode requires continuous external setpoint proof-of-life above 2 Hz and has explicit loss failsafe behavior: https://docs.px4.io/main/en/flight_modes/offboard.html
- QGroundControl Plan View separates planning, upload, and flight execution and uses planned home for estimates: https://docs.qgroundcontrol.com/master/en/qgc-user-guide/plan_view/plan_view.html
- QGroundControl Corridor Scan is polyline-based with width and terrain-related constraints: https://docs.qgroundcontrol.com/master/en/qgc-user-guide/plan_view/pattern_corridor_scan.html
- NIST public safety UAS guidance emphasizes degraded communications and practical limits for UAS swarms: https://www.nist.gov/ctl/pscr/research-portfolios/uncrewed-aircraft-systems
- NASA display standards require visibly distinct modes/states, stale-data indication, and visible operational-limit violations: https://www.nasa.gov/reference/appendix-f-vol-2/
- NASA RPAS remote pilot station guidance will inform pilot task support, control consistency, and workload reduction: https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20190000211.pdf
- IAMSAR Volume III will inform immediate SAR pattern presets and later pattern-library expansion: https://hamnetkzn.org.za/files/training/IAMSAR%20Manual%20Doc9731_vol3_en_2016%20Edition.pdf

## QuickScout Target Workflow

QuickScout should support a direct 0-to-launch operator flow:

1. Select mission type: point dispatch, last-known-point search, area search, corridor search, or monitor existing mission.
2. Select drones and see readiness: online, GPS/global position, telemetry freshness, battery, API auth state, and mission compatibility.
3. Choose or draw geometry:
   - Point dispatch: map click, search result, drone/current point, or typed coordinate.
   - Last-known point: map click, incident search result, manual coordinate, or explicit telemetry/finding source with timestamp.
   - Area search: polygon draw/edit/import.
   - Corridor search: multi-vertex polyline draw/edit plus corridor width.
4. Choose altitude policy: fixed MSL, AGL/terrain-follow where provider is available, or explicit degraded no-terrain fallback.
5. Compute plan using a bounded sync path only for trivial jobs; otherwise use a job with phases, progress, cancel, retry, and actionable failure details.
6. Review a centered launch dialog with selected drones, mission type, geometry summary, altitude source, distance/time, readiness blockers, warnings, return behavior, and abort/recovery note.
7. Launch through the existing tracked-command path.
8. Monitor progress, findings, drone assignments, stale telemetry, and recovery actions.
9. Abort or return through a centered confirmation dialog with explicit affected drones and command state.
10. Preserve mission history and handoff state for recovery after page reload or backend restart where current persistence supports it.

## Swarm Trajectory Target Workflow

Swarm Trajectory should support a single-page 0-to-execution workflow where possible:

1. Choose mode: single drone, cluster, leader/follower, or fleet.
2. Draw, import, or edit waypoints in global coordinates.
3. Select altitude behavior: fixed MSL, target AGL with terrain source, imported altitude, or explicit degraded terrain-unavailable mode.
4. Assign drones, clusters, leader routes, follower offsets, and any imported leader CSVs.
5. Validate route and swarm relationships before processing: malformed waypoints, missing leaders, missing cluster members, duplicate drone assignments, stale processed session, altitude conflicts, and unsupported local/no-GPS cases.
6. Preview route geometry before writing/committing generated outputs when feasible.
7. Process using a job with phases, progress, cancel, warnings, and partial-output state.
8. Show map visualization for leader path, follower offsets, per-drone generated path, conflicts, altitude source, and processing status.
9. Commit or transfer generated outputs only after a review dialog explains selected drones, files/session, offboard requirements, synchronized start, and recovery behavior.
10. Monitor readiness and clear/reset session with guarded dialogs that state what will be removed.

The existing `TrajectoryPlanning` page should be folded into this workflow or retained temporarily as a focused lower-level route editor with clear navigation and docs. It should not remain a confusing second step without a documented reason.

## Shared UI/UX Component Plan

Create shared mission-planning primitives under a new mission-planning component boundary. Names may change to match repository conventions, but the responsibilities should remain stable:

- `MissionMapWorkspace`: map provider wrapper, Mapbox/Leaflet fallback, geometry event normalization, selected drones overlay, path preview overlay, and mobile layout boundary.
- `MissionGeometryToolbar`: point, waypoint sequence, polyline, polygon, corridor, edit, clear, undo where supported.
- `MissionGeometrySummary`: compact validity, dimensions, point count, area/corridor width, distance, and warnings.
- `MissionDroneSelector`: shared selected/available/readiness summary with degraded state chips.
- `MissionAltitudeControl`: fixed MSL, AGL/terrain, imported altitude, provider state, terrain warnings, and docs link.
- `MissionJobProgressDialog`: centered accessible dialog with phase, progress, elapsed time, cancel, retry, and error details.
- `MissionReviewLaunchDialog`: centered accessible review and launch/commit confirmation, replacing inline verbose review and browser confirms.
- `MissionPlanStatusBar`: concise current mission type, selected drones, geometry validity, altitude source, readiness, and next action.
- Geometry helpers: point, waypoint sequence, polygon, polyline, corridor buffer metadata, path summaries, and GeoJSON conversion.

Reuse or adapt existing `LeafletMapBase`, `LeafletDrawControl`, Mapbox drawing code, `SearchBar`, trajectory waypoint components, `ConfirmDialog`, `MetricStrip`, `StatusBadge`, operator notices, and existing design tokens. Deprecate duplicated verbose sidebar guidance and route-specific map interaction code after tests cover the shared path.

## Backend And API Plan

Shared API policy:

- Use deterministic error codes, concise human messages, machine-readable details, and HTTP status consistency.
- Keep optional API-auth compatibility unchanged.
- Log job lifecycle, validation failures, launch/commit requests, terrain-provider failures, and cancellation without logging secrets.
- Design job payloads for future MCP/AI-agent use: typed schemas, status endpoints, phases, warnings, errors, stable ids, and replayable input summaries.
- Never silently fabricate coordinates or use default origins.

QuickScout API plan:

- Harden `/api/sar/mission/plan` schemas for point dispatch, last-known-point search, polygon area search, and multi-vertex corridor search.
- Reject missing, stale, invalid, or default `(0, 0)` telemetry unless the operator explicitly selected that coordinate as mission geometry.
- Return explicit position-unavailable and origin-unavailable states.
- Preserve existing polygon/boustrophedon coverage behavior.
- Make terrain provider failure explicit as either a blocker or a degraded warning, based on selected altitude policy.
- Add or expose planning jobs when compute can exceed a few seconds: create, status, cancel, result, and expiry.
- Add last-known-point presets that are practical now, such as expanding square or sector-style options, while deferring a full IAMSAR pattern library if needed.

Swarm Trajectory API plan:

- Keep FastAPI routing under the existing swarm trajectory namespace; no legacy Flask-style route should be introduced.
- Add typed validate/preview/process/commit/clear semantics around global waypoints, imported leader routes, clusters, leaders, followers, altitude source, and terrain state.
- Prefer preview/validate before destructive processing writes.
- Add process jobs with progress, cancel, warnings, partial-output status, and clear reset semantics.
- Ensure backend output includes enough path and relationship metadata for the frontend to draw leader/follower paths and conflicts.
- Keep target-scope validation before dispatch and document Offboard proof-of-life and failsafe implications.

## Operator Scenarios

The implementation and validation should cover:

- US/Taiwan coast guard-style shoreline point dispatch with one drone.
- Last-known-position search from a clicked point, incident coordinate, or finding/telemetry source with timestamp.
- Multi-drone area sweep with explicit sectors and stale-telemetry handling.
- Multi-vertex corridor search along a shoreline, road, or vessel route.
- Degraded connectivity where progress/status may lag but UI remains bounded and recoverable.
- No Mapbox token or Mapbox load failure with Leaflet fallback.
- Stale telemetry, no GPS/global position, local-position-only, and baro-only cases with clear blocked/degraded states.
- Terrain provider failure with explicit altitude behavior.
- SITL public demo with deterministic sample coordinates and at least four drones where available.
- Swarm single-drone global route, leader/follower cluster route, clear/reset, and stale processed-session handling.

## Documentation, Tests, And Release Plan

Documentation to update:

- `docs/quickscout.md`
- `docs/features/swarm-trajectory.md`
- A new shared mission planning workspace guide if shared components become operator-visible.
- Docs index and version references.
- Telemetry display policy documentation, because the referenced policy file is missing from the clean public baseline.
- Tester handoff and release notes.

Tests to add or strengthen:

- QuickScout planner route tests for missing position, stale position, default `(0, 0)` rejection, terrain unavailable behavior, last-known point, point dispatch, multi-vertex corridor, and job cancel/status if added.
- QuickScout UI tests for last-known map click, corridor drawing, bounded progress, review dialog, and Leaflet fallback.
- Swarm trajectory tests for validate/preview/process/commit/clear errors, missing cluster, missing leader, malformed waypoint/CSV, terrain-unavailable state, stale session, and generated visualization metadata.
- Shared geometry helper/component tests.
- Manual or automated Mapbox and Leaflet fallback validation.
- Existing backend and frontend regression tests before release.

Release order:

1. Public implementation, tests, docs, commit, tag, and push.
2. Privacy review before downstream merge.
3. Downstream private merge/cherry-pick, private deployment, SITL/runtime validation, optional board sync only when safe.
4. Final handoff with commits/tags, tests, deployment state, runtime mode, known deferrals, and operator instructions.

## Stale Or Deprecated Items Identified

- The telemetry display policy doc referenced by the task is not present in the clean public baseline.
- Swarm Trajectory documentation has stale version/date text and documents the old split workflow.
- QuickScout text still implies Mapbox is mandatory in places despite Leaflet fallback support.
- QuickScout launch/recovery controls still use at least one browser confirm path.
- `tests/test_sar_api.py` has duplicate corridor test method names, reducing real coverage.
- `/trajectory-planning` and `/swarm-trajectory` are both first-class navigation entries, which currently splits a workflow that operators expect to be continuous.

## Acceptance Criteria

This phase is complete only when:

- QuickScout compute cannot spin indefinitely; progress, timeout, cancel, retry, and actionable errors are available.
- QuickScout last-known-point selection works from the map and from explicit coordinate/search sources.
- QuickScout supports multi-vertex corridor planning end to end.
- QuickScout never silently plans from `(0, 0)` or fabricated telemetry.
- Terrain/altitude behavior is explicit for both modes.
- Swarm waypoint creation, edit, preview, process, commit, clear, and reset work in one clear workflow or a documented temporary split.
- Leader/follower and cluster relationships are visible on the map and in review.
- Review/launch/commit/abort dialogs are centered, responsive, keyboard-accessible, and concise.
- Main-page explanatory text is reduced; docs, tooltips, and contextual details carry deeper guidance.
- Mapbox primary and Leaflet fallback paths are validated.
- Backend route errors are typed, actionable, and covered by tests.
- Docs and version references are current.
- Public artifacts contain no downstream private data.

## Risks, Assumptions, And Deferrals

Risks:

- Adding durable planning jobs may require careful integration with existing SQLite stores and process lifetime behavior.
- Terrain provider reliability may not support full terrain following everywhere; the UI and API must expose this instead of hiding it.
- Single-page Swarm Trajectory may require staged migration to avoid breaking existing processing and dashboard dispatch.
- Heavy frontend/backend builds and SITL should run on a resource-appropriate host during later slices.

Assumptions:

- Existing tracked-command launch flow remains the correct dispatch boundary.
- PX4 Mission and Offboard safety gates should remain explicit rather than abstracted behind a generic "launch" label.
- Field hardware validation may be deferred if boards are unavailable or operators are actively testing.

Allowed deferrals with explicit follow-up:

- Full IAMSAR pattern library beyond immediate point, last-known, area, corridor, expanding-square, and sector-style presets.
- Advanced multi-drone deconfliction beyond validation and visible warnings.
- Full terrain-following if no reliable elevation provider is available.
- Full no-GPS/VIO execution support beyond clear planning/display blocks.
- Automated SAR replanning after findings.
- Hardware validation when boards are unavailable or unsafe to touch.

## Slice 0 Gate

No functional implementation should start until this decision is approved. After approval, Slice 1 should build the shared mission planning foundation, followed by QuickScout backend hardening, QuickScout UI cleanup, Swarm Trajectory backend cleanup, Swarm single-page workflow, docs/tests, SITL/runtime validation, and release/deployment.
