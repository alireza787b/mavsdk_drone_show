# Changelog

All notable changes to MAVSDK Drone Show (MDS) project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses simple two-part versioning: `X.Y` (Major.Minor).

---

## [Unreleased]

### Fixed
- Swarm Trajectory processed CSVs now preserve `vx/vy/vz` and `ax/ay/az` as real local NED metric quantities instead of raw lat/lon/alt derivatives, which makes runtime diagnostics and `continue_heading` end behavior consistent with the controller contract
- Swarm Trajectory initial drift sampling now uses the same non-blocking local-API pattern as Drone Show, and drift correction is skipped when preflight only has a fallback current-position reference instead of PX4's actual GPS global origin
- Swarm Trajectory runtime now treats its launch-time global reference explicitly instead of carrying it through the mission path as a misleading `home_position` name:
  - pre-flight prefers PX4 GPS global origin, with a bounded fallback to the current global position sample when the origin RPC is unavailable
  - that reference is now documented and tested as readiness / drift / recovery truth only, not as a redefinition of the authored global route geometry
- Swarm Trajectory waypoint authoring now locks confirmation until terrain lookup resolves or the operator explicitly chooses the estimated-terrain fallback, so high-terrain routes cannot be saved against stale `groundElevation=0` assumptions while the planner is still loading terrain
- Swarm Trajectory waypoint authoring now rejects non-increasing manual arrival times at the modal boundary instead of waiting for a later route-readiness pass to discover the chronology error
- Swarm Trajectory coordinate edits and dragged waypoint moves now refresh terrain truth at the new coordinates: `Target AGL` waypoints preserve the authored clearance intent by recomputing stored MSL altitude against the refreshed ground elevation, `MSL input` waypoints keep their stored mission altitude while updating derived terrain review, and stale async terrain replies are ignored so rapid waypoint moves cannot overwrite newer planner edits
- Swarm Trajectory waypoint-panel coordinate saves now show that terrain and clearance are being refreshed instead of pretending the edit is an instant local-only change, keeping operator feedback aligned with the real async terrain update path
- Swarm Trajectory workspace wording now treats partial outputs as attention-state review packages instead of generic launch-ready results, frames git commit as optional mission traceability rather than a safety gate, and labels the handoff back to command control as `Open Mission Trigger` so launch approval is clearly anchored in dashboard preflight
- Swarm Trajectory cluster-state handling now normalizes partial-state aliases in the shared frontend model, so readiness cards, processing workspace views, and tests cannot silently drift if a legacy `partial` state appears in mocked or transitional data
- Swarm Trajectory follower generation now applies NED/body offsets around each leader waypoint's instantaneous global position instead of a fixed formation centroid, and `offset_z` now follows the documented Swarm Design `Up-positive` convention all the way through the global follower projection math
- Swarm Trajectory planner, launch review, docs, and shared execution doctrine now state the mission frame explicitly: authored routes stay global lat/lon with stored MSL altitude, while PX4 launch/home truth remains an execution-time readiness and recovery input instead of a hidden route transform; the mission script also no longer carries the stale `shapes/.../swarm/processed` provenance path
- Swarm Trajectory planner import/export language now calls out the real asset boundary: CSV import/export is the authored leader route for round-trip editing or assignment, not the processed multi-drone mission package that gets launched later from `Swarm Trajectory` + dashboard Mission Type 4
- Swarm Trajectory planner/library/transfer summaries now label authored **Route Time** explicitly instead of a generic duration, because real command completion can be materially longer once initial climb, RTL, landing, and other end-behavior cleanup are included
- launch-from-ground mission dispatch now uses a live per-drone MAVSDK armability probe before GCS sends the command, closing the gap where passive telemetry could still look ready while PX4 would deny arming at mission start
- Drone API now exposes an explicit live armability probe endpoint backed by the same MAVSDK startup-health logic used by Drone Show and Swarm Trajectory mission startup, so launch gating and mission runtime share one armability definition
- telemetry readiness now distinguishes actual PX4 HOME_POSITION truth from the first fallback GPS position cache, so `home_position_set` and launch gating no longer silently treat "we have a position sample" as "PX4 home is established"
- Swarm Trajectory / live readiness validation now treats a lone MAVLink `system_status=UNINIT` report as an advisory when PX4 preflight data and live telemetry are otherwise healthy, preventing false launch blocks after SITL mission recovery while still surfacing the discrepancy to operators
- Swarm Trajectory Mission Type 4 launch readiness is now scope-aware instead of globally all-or-nothing: a selected subset can launch when every selected drone has a processed output and the full required leader chain is included, while unrelated incomplete clusters stay as warnings instead of false blockers
- Swarm Trajectory selected-target safety is now enforced in both layers: the dashboard preflight blocks broken leader chains or missing processed outputs, and the backend `/submit_command` path rejects the same unsafe subset even if the UI is bypassed
- the standard `linux_dashboard_start.sh --sitl` / development launcher path no longer starts FastAPI with `--reload` by default, because backend auto-reload splits in-memory telemetry, heartbeat, and command-tracker state across processes; backend reload is now an explicit opt-in debug override only
- Swarm Trajectory planner, transfer dialog, docs, and validation tooling now share one clearer four-stage operator model (`author leader path -> define route entry/leg intent -> assign leader -> process/review/launch`), and the runtime validator now imports the real repo timeout model instead of silently falling back to stale internal timeout constants when run from the `tools/` path
- Swarm Trajectory authoring terminology is now precise about leg-vs-waypoint ownership: the UI and docs use `Route entry delay`, `Waypoint arrival time`, `Preferred leg speed`, `Required leg speed`, and `Entry heading` / `Arrival heading` consistently, so operators no longer have to infer whether a field belongs to the route anchor, the inbound leg, or the arrival posture
- Swarm Trajectory route-entry timing now comes from one shared timing policy: waypoint 1 defaults to a `10s` route-entry delay after mission start, the planner surfaces that default explicitly, and timing helpers use the same fallback instead of hidden duplicated magic numbers
- Swarm Trajectory mission briefs and transfer summaries now show the real authored route-entry delay (for example `Entry +12s`) instead of only counting that a route-entry anchor exists
- Swarm Trajectory runtime validation can now prepare its own short deterministic top-leader profile before processing, so subset SITL acceptance runs (for example 3-drone cluster tests) no longer depend on a previously loaded long route on the host
- local Docker SITL now shares the host `shapes_sitl/swarm_trajectory/` workspace into each container through a dedicated runtime path, so same-host Swarm Trajectory processing and execution stay consistent without forcing a repo commit or leaving the container repo dirty
- Swarm Trajectory end-behavior recovery is now fail-closed: if `return_home` and every recovery path still fail, the mission exits with failure instead of logging a critical line and then incorrectly reporting mission success
- Swarm Trajectory RTL completion now has a bounded near-ground low-motion fallback for SITL/PX4 edge cases where the aircraft is effectively down but never transitions to `ON_GROUND`, preventing one drone from hanging the entire command for the full RTL timeout
- the Swarm Trajectory runtime validator now tracks per-drone peak altitude gain over time instead of requiring every selected drone to be above the climb threshold on the same polling tick, which removes false failures on short follower routes that clear the climb gate and then descend into a lower processed path
- Swarm Trajectory authoring and transfer now use the real operator wording end to end: the planner action is `Assign to Cluster`, readiness transfer labels match that cluster-assignment model, planner notices now say when a leader path was assigned rather than vaguely "sent", and the transfer dialog title/copy no longer hides that this is a leader-cluster handoff
- Swarm Trajectory authoring guidance is now single-source across the planner, waypoint modal, waypoint panel, and transfer surface: shared descriptions explain what `MSL input`, `Target AGL`, `Speed-driven ETA`, `Time-driven speed`, `Auto heading`, `Manual heading`, and the `Mission start anchor` actually mean, while waypoint intent tags move that extra detail into hover hints instead of duplicating noisy prose inline
- Swarm Trajectory planner and transfer now expose one shared operator-policy strip before assignment: the UI states explicitly that missions always execute stored MSL altitude, `Target AGL` is authoring input converted at planning time, terrain confidence changes review posture, and waypoint 1 owns route-entry timing/heading while later legs own ETA-versus-speed intent
- Swarm Trajectory processing workspace now repeats the same execution boundary before launch review: operators see in-page that only top leaders are authored, processed drones fly per-drone generated global paths, Smart Swarm is the live-follow mode instead, and any earlier AGL planning input has already been converted into the stored MSL mission package
- Swarm Trajectory planner CSV interchange now preserves authoring intent as optional metadata columns: exported leader CSVs keep altitude reference, target AGL, terrain confidence, timing mode, preferred speed, and calculated heading for round-trips back into the planner, while older minimal mission CSVs still import correctly and backend processors continue accepting the same required core columns
- Swarm Trajectory `Leg Review` now supports condensed attention-only and full-route audit modes, and each leg exposes compact timing, heading, altitude, and terrain-confidence intent so operators can audit the whole path without leaving the planner
- Swarm Trajectory subset runtime validation now adapts its generated short-profile route-entry delay to the selected follower offsets and reports inactive/post-mission geometry windows explicitly, preventing misleading failures when a short SITL validation route ends before a large-offset cluster can fully form
- the first Swarm Trajectory waypoint now stays explicit/manual all the way through modal initialization, so the mission-start anchor no longer boots in a contradictory auto-heading state or disables the operator's initial route-entry heading field
- Swarm Trajectory initial climb is now a real safety gate instead of a time-only phase: waypoint progression no longer advances while the climb gate is still unresolved, launch altitude confirmation can fall back to launch-referenced absolute altitude when relative altitude lags, and a failed climb now terminates loudly with safe cleanup instead of silently exhausting the mission in the background
- Swarm Trajectory 5-drone SITL runtime validation now passes end to end on the hardened mission engine, including process -> climb gate -> in-flight follower geometry -> long return-home completion -> command tracker terminal success -> fleet idle reset
- Swarm Trajectory planner utilities and authoring components no longer emit routine browser-console warning noise for handled fallback paths, and the trajectory authoring surface was cleaned of stale phase-specific banner comments that no longer described the maintained behavior
- Swarm Trajectory runtime validation now budgets the terminal wait window from the processed mission peak altitude instead of the early formation snapshot altitude, so high-altitude RTL descents no longer time out while the aircraft is still descending correctly
- Swarm Trajectory mission validation now enforces a real initial-climb altitude sample before leaving the takeoff gate, preventing premature path-follow entry on time-only progress
- Swarm Trajectory `return_home` cleanup is now bounded and mode-aware: the mission verifies that PX4 really enters RTL, retries once if a drone remains stuck in Hold/Offboard, and degrades to explicit LAND fallback with bounded action-RPC waits instead of hanging indefinitely on a lost ACK or non-engaged RTL state
- Swarm Trajectory planner geodesic math is now self-contained and testable: speed, heading, timing, and trajectory statistics no longer depend on the heavier Turf bundle in `SpeedCalculator`
- Swarm Trajectory planner statistics now use the same 3D path-distance model as the speed/timing logic, so climb/descent legs are reflected consistently in operator-facing totals and average speed
- direct frontend utility coverage now exists for Swarm Trajectory planner speed, heading, timing validation, and 3D stats
- Swarm Trajectory waypoint authoring now has an explicit segment-planning model instead of a hidden time-only assumption: later-waypoint modals can run in `Auto from leg speed` or `Manual arrival time`, the waypoint panel exposes `Segment Plan` and `Leg Speed` inline, and derived arrival times are clearly shown as derived rather than free-edit fields
- Swarm Trajectory planner state now preserves operator intent through modal -> panel -> save/load/export -> undo/redo, including timing mode, preferred leg speed, and terrain context metadata instead of dropping those fields after creation
- Swarm Trajectory altitude authoring now supports both direct `MSL input` and terrain-assisted `Target AGL` entry while keeping canonical mission storage in MSL, and the planner review surface now shows derived AGL context plus the stored altitude plan instead of hiding that conversion
- Swarm Trajectory planner now publishes a real mission brief before swarm transfer, summarizing distance, duration, altitude envelope, max-leg-speed posture, timing mode mix, altitude-input mix, heading intent, and terrain-confidence so operators can catch speed or terrain caveats before leader assignment
- Swarm Trajectory planner now repeats its execution model on the authoring surface itself, so `Trajectory Planning` explicitly declares that it authors top-leader paths only, keeps launch-readiness/terrain/speed caveats visible above the map, and avoids forcing operators to infer workflow state from separate pages
- waypoint authoring and review now expose the same operator intent model everywhere: the modal publishes altitude-plan / segment-plan / heading / terrain summary cards, and waypoint cards show compact tags for altitude reference, timing mode, heading mode, and terrain confidence before launch
- Swarm Trajectory planner save/load now uses one shared trajectory-library dialog instead of duplicated page-local modal code, and the library view exposes duration, distance, max speed, modified time, and autosave status so operators can reload the right leader path without guessing
- Swarm Trajectory planner mission-envelope defaults are now centralized in one shared policy module, so altitude/speed defaults, validation bounds, terrain-safety fallback altitude, and operator-facing envelope text no longer drift between modal, panel, search, storage, and planner summary surfaces
- Swarm Trajectory waypoint leg ownership is now consistent across math and UI: the first waypoint is always the explicit manual mission-start anchor, while every later waypoint owns the arrival-leg speed and auto-heading that reaches it instead of mixing inbound timing with outbound heading/speed labels
- Swarm Trajectory waypoint review no longer forces operators to mentally convert terrain-backed altitudes: the panel now makes `Altitude Input` editable, keeps stored MSL explicit, and lets `Target AGL` waypoints edit `Clearance AGL` directly while recomputing canonical stored altitude
- Swarm Trajectory processing/review now uses one clearer staged workspace model: the page surfaces a single workspace-status banner, explicit step cards for upload/process/review readiness, step-local processing recommendations, and commit actions that live inside the review stage instead of being scattered across the screen
- Swarm Trajectory planner/transfer readiness now uses one explicit mission-posture model: timing conflicts, single-waypoint drafts, and impossible-speed legs are surfaced as transfer blockers, review-only caveats stay separate from blockers, and the `Send to Swarm` dialog now shows whether a path is `Draft only`, `Review required`, or `Ready to process` while using real cluster-state truth instead of a simplified ready/uploaded heuristic
- Swarm Trajectory authoring labels are now consistent across the planner, waypoint modal, and waypoint panel: the first point is explicitly treated as the `Mission start anchor`, non-initial legs use `Speed-driven ETA` vs `Time-driven speed`, altitude review emphasizes canonical stored MSL, and duplicate warning noise was removed from the header stats so action-focused caveats stay in the workflow brief instead
- Swarm Trajectory planner handoff/navigation is now wired end-to-end: `Send to Swarm` can open `Swarm Design` or `Swarm Trajectory` directly from the dialog, readiness/docs/runtime copy now explicitly treat `Swarm Design` as the prerequisite step, and launch instructions now point to `Dashboard -> Command Control -> Mission Trigger` instead of the stale `Mission Control` wording
- Mission Type 4 preflight now summarizes the processed Swarm Trajectory package more clearly, including ready clusters, processed drones, missing uploads, the active processing session, and direct remediation links back to the authoring / processing pages
- Trajectory planner undo/redo state now uses the real recalculated waypoint arrays for add/update/delete/move operations, preventing stale internal state from drifting away from what the operator actually sees in the planner
- Swarm Trajectory planner now uses inline notices for destructive actions, waypoint edit validation, modal altitude validation, and keyboard-shortcut help instead of blocking browser popup flows, while keeping altitude authoring explicitly MSL with terrain-derived AGL context
- Swarm Trajectory processing/status truth is now richer and less heuristic: recommendations include expected/uploaded/missing leader IDs, processing results now distinguish `success` vs `partial` outcome, cluster status exposes explicit states/issues/advisories, and planner export now uses the current in-memory path instead of stale saved-local-storage state
- drone `UPDATE_CODE` commands now preserve their runtime `update_branch` payload all the way into mission execution, so dashboard-triggered repo sync actually runs instead of reporting accepted while silently failing branch resolution on the drone
- git-sync verification now ignores generated SITL provenance metadata files, so stock containers do not stay permanently `dirty` just because they carry build/provenance markers
- the `Sync Now` flow now verifies real branch/commit convergence before reporting success, and default all-drone sync now prefers recently active drones instead of counting stale offline config slots from the same host
- `tools/update_repo_ssh.sh` now resolves user/home robustly even in non-interactive container execution, avoiding `USER: unbound variable` failures during scripted sync actions
- `tools/update_repo_ssh.sh` no longer treats ICMP `ping` as a hard requirement for connectivity, so Docker/SITL sync uses TCP-aware advisory probing and lets the actual `git fetch` decide whether network access is available
- mission and action scheduling now present GCS-aligned UTC execution times more clearly, so operator confirmations/toasts stay consistent even when the browser wall clock is off
- browser/GCS clock-drift notes now appear only for material offsets instead of small harmless differences, reducing operator noise during normal SITL use
- per-drone overview-card overrides now explain that they are airborne intervention controls, so disarmed or link-unavailable cards no longer look like broken action panels
- overview preflight tiles no longer flicker back to "Checking git state" on each poll, and now use quieter state coloring plus hover diagnostics instead of text churn
- the Actions tab is more compact, action descriptions moved to hover/confirmation context, and flight/test actions can now be scheduled without forcing maintenance or danger actions into delayed execution
- dashboard drone cards now separate warning/unknown link states from true blocked readiness, add clearer link-state hover details, and avoid treating every non-ready state as the same red alarm
- the Custom CSV workflow now has a real dashboard upload/validate/preview path instead of the old placeholder/CORS-broken preview behavior
- the Drone Show dashboard now states more clearly that SkyBrush ZIP import and Custom CSV are separate operator workflows, reducing accidental mode confusion
- **Custom Repo Workflow Validation**:
  - documented the real GitHub behavior that public upstream forks stay public by default, so confidentiality-sensitive customer setups should use a private mirror/custom repo path instead of assuming a private fork
  - GCS and drone SSH repo setup now pin repo-local `core.sshCommand` when SSH is used, so pre-existing host `~/.ssh/config` GitHub identities do not silently override the intended MDS deploy key
  - GCS env configuration now rewrites `/etc/mds/gcs.env` when repo, branch, or access mode changes on a non-interactive rerun, so launcher/runtime state stays aligned with the selected customer repo instead of preserving stale official defaults
  - SITL runtime and SITL image preparation now prefer file-backed private GitHub auth via `MDS_GIT_AUTH_TOKEN_FILE`, so private mutable SITL and private custom-image builds avoid exposing raw tokens in process arguments while keeping `MDS_GIT_AUTH_TOKEN` as a legacy fallback
  - fresh headless GCS startup is now robust when Node.js was installed via `nvm`, because the launcher discovers the Node toolchain explicitly and uses absolute `uvicorn` / `gunicorn` / `npm` paths inside tmux panes instead of depending on inherited shell PATH state
  - SITL image preparation and live SITL runtime no longer blank the repo URL when authenticated GitHub HTTPS is unavailable, and official/custom image builds now stop immediately if runtime filesystem preparation fails instead of flattening a partial container
- the official public SITL archive was rebuilt from the corrected release flow, republished on MEGA, and re-linked in the SITL guide after validation on a fresh Hetzner host
- dashboard runtime freshness now uses a server-derived telemetry clock hint instead of blindly trusting the operator browser clock, so fresh remote SITL sessions no longer show false stale-link readiness states just because the client clock is skewed
- Drone Show and Swarm Trajectory offboard startup now share a bounded MAVSDK armability gate before arming, reducing transient PX4 pre-arm denials during SITL and hardware mission launch
- drone readiness cards now preserve a recent PX4 readiness snapshot as a warning-only link issue instead of immediately flipping the whole card to `Unverified`, so low-bandwidth or briefly delayed telemetry is shown more cleanly for operators
- the Custom CSV page now uses the served image endpoint directly instead of a cross-origin `fetch()` blob path, which removes the false preview error caused by browser CORS on `:3030 -> :5000`
- drone card position-ID comparison now normalizes numeric/string values before flagging a mismatch, so matching IDs no longer show a false warning icon
- the Overview dashboard now normalizes live telemetry before rendering drone cards, so browser/server clock skew no longer produces false `Heartbeat only` / `Link lost` card states, and short 3-point SkyBrush imports now process correctly through the linear fallback path
- the telemetry API now exposes a server clock header and the dashboard uses that server-derived time when evaluating freshness, so moderate browser clock drift no longer silently degrades link state; if a meaningful client/server offset exists it is surfaced in the link-status tooltip instead
- Swarm Trajectory readiness now uses truthful per-cluster backend state instead of heuristic leader-count guesses: uploaded raw CSV content changes force a fresh reprocess, leader uploads are validated against the current top-leader set, processing status now exposes real cluster readiness/missing followers/plot availability, and the dashboard distinguishes `ready`, `pending process`, and `missing upload`
- Mission Type 4 dashboard launch gating now follows that same backend cluster truth instead of only generic mission heuristics, so missing uploads, pending processing, partial outputs, cluster issues, and missing active-package state all block launch before dispatch
- Swarm Trajectory review/git actions now respect the actual GCS write-back mode: writable setups keep `Commit & Push Outputs`, while read-only/demo setups use a truthful local-commit-only path and the backend stops before pull/push when `MDS_GIT_AUTO_PUSH=false`
- direct frontend tests now cover the Swarm Trajectory launch-readiness model, Mission Type 4 launch gating, and the page-level local-commit wording for read-only GCS deployments
- Swarm Trajectory planner now includes a dedicated `Leg Review` surface so operators can see per-leg distance, duration, required speed, and nominal / review / unsafe pacing before assigning a leader path to a swarm cluster
- Swarm Trajectory planner/operator guidance now states explicitly that current `Target AGL` assistance is waypoint-based rather than full along-leg terrain following, so sparse routes over changing terrain are not misinterpreted as true terrain-follow missions

### Added
- **Custom Repo Workflow Guide**:
  - new `docs/guides/custom-repo-workflow.md` covering customer/private repo operation across GCS, real drones, SITL, upstream sync, and custom release images
- **Repo-wide AI agent operating spec**:
  - new root `AGENTS.md` as the canonical machine-oriented SITL audit/debug/release loop
  - thin root `CLAUDE.md` and `GEMINI.md` shims that point to the shared spec instead of duplicating instructions
  - new `docs/superpowers/specs/2026-03-26-ai-agent-sitl-audit-loop.md` for the deeper agent-only execution contract
  - new `docs/superpowers/README.md` index so agent-only specs/plans stay organized without cluttering user-facing docs
- **Drone Show Operator Guide**:
  - new `docs/features/drone-show.md` covering SkyBrush import flow, GLOBAL/LOCAL modes, Custom CSV, trigger timing, and read-only demo guidance
- **Unified Logging System (`mds_logging`)**: Shared logging contract for all components
  - JSONL format for machine-parseable log files with ISO 8601 UTC timestamps
  - Session-based retention with configurable limits (count + size)
  - Colored console output with component-tagged messages
  - Component self-registration registry for auto-discovery
  - In-memory pub/sub watcher for SSE streaming
  - Shared CLI flags: `--verbose`, `--debug`, `--quiet`, `--log-json`, `--log-dir`
  - Environment variable config with `MDS_LOG_*` prefix and deprecation shims
- **Frontend Log Viewer (Phase 3)**:
  - Log Viewer page at `/logs` with Operations and Developer modes
  - Operations mode: WARNING+ filter, health bar, live event feed, clean UI
  - Developer mode: all log levels, component tree, search, session selector, export
  - Explicit `GCS` vs `Drone #N` scope switch for live streams and historical sessions
  - Human-readable session labels with explicit UTC note, clickable error/warning drill-down, and time-window focus controls
  - Active filter chips, one-click `Clear All Filters`, and explanatory empty states to reduce operator confusion
  - MUI DataGrid virtual scroll for 100K+ log rows
  - Real-time SSE streaming via `useLogStream` hook with 200ms batching and 5000-line ring buffer
  - Historical session browsing with filtering and client-side pagination
  - Export sessions as JSONL or ZIP, including proxied drone sessions
  - ErrorBoundary catches React render errors and reports to `POST /api/logs/frontend`
  - New "System" sidebar section with Log Viewer entry
  - `@mui/x-data-grid` dependency for virtual scroll
- **Log Aggregation & Streaming (Phase 2)**:
  - Drone-side log API: `GET /api/logs/sessions`, `GET /api/logs/sessions/{id}`, `GET /api/logs/stream` (SSE)
  - GCS log API router with 10 endpoints at `/api/logs/*`
  - Real-time SSE streaming with level/component/source/drone_id filtering
  - GCS-to-drone log proxy (sessions, session content, SSE stream forwarding)
  - Session export as JSONL or ZIP via `POST /api/logs/export`
  - Frontend error reporting via `POST /api/logs/frontend`
  - Component registry endpoint at `GET /api/logs/sources`
  - Optional background pull of WARNING+ logs from drones (`MDS_LOG_BACKGROUND_PULL`)
  - Runtime config toggle at `POST /api/logs/config`
  - `read_session_lines()` helper for filtered session content retrieval
  - `httpx` async HTTP client dependency for drone proxy
- **SITL Image Release Tooling**:
  - `tools/sitl_image_prepare.sh` to rebuild a clean runtime filesystem inside a temporary container
  - `tools/release_sitl_image.sh` to flatten and retag official SITL releases without carrying old `docker commit` history
  - `tools/run_with_log_policy.py` for bounded runtime file logs in SITL containers
- **Smart Swarm Runtime Guide**:
  - Dedicated operator/developer guide at `docs/features/smart-swarm.md`
  - Explicit command-scope model for single-drone vs swarm-level runtime controls
  - Documented leader-loss policy and extension points for future election strategies
- **Smart Swarm Acceptance Tooling**:
  - `tools/validate_smart_swarm_runtime.py` for branch-level 5-drone SITL validation
  - waits for preflight readiness before takeoff so fresh-boot SITL checks do not race container startup
  - validates full command acceptance/execution, cluster settle, live reassignment, leader-only RTL, hold, land, and final disarm

### Changed
- `Show Design` / `Custom Show` operator guidance, Mission Details, and the Drone Show guide now reflect the current split between the normal SkyBrush import pipeline and the expert-only Custom CSV override
- Bootstrap installers now propagate custom repo/branch selections all the way into `mds_gcs_init.sh` / `mds_init.sh`, including explicit `--repo-url` support and correct persistence of custom branch settings in later config/state
- Root `README.md` and `docs/README.md` now use a cleaner "start here" / role-based navigation model so testers, operators, deployers, and maintainers can reach the right guide with less duplication and less scrolling
- Drone git sync now uses the same repo/branch source of truth in both boot-time sync and operator-triggered `UPDATE_CODE` flows by loading `/etc/mds/local.env` before resolving `MDS_REPO_URL` / `MDS_BRANCH`
- Bootstrap and setup flows now accept `--fork OWNER` or `--fork OWNER/REPO`, so customer org/private repo paths no longer require ad hoc URL rewriting
- README, docs index, setup guides, automation guides, and troubleshooting guides now route custom repo users to a single end-to-end workflow instead of assuming only a personal GitHub fork
- fresh-host setup guides now include the missing `curl` prerequisite for the one-line GCS bootstrap and explicitly note the validated headless `/health` readiness check after launch
- SITL archive docs now standardize on the official `MEGAcmd` client installed through MEGA's Ubuntu package and `apt`, so public downloads and authenticated archive replacement use one consistent toolchain
- the official public SITL archive was refreshed again from the exact validated branch state and re-exported on MEGA with baked commit `f55a65b`
- the SITL guide now points directly to the YouTube playlist, trims repeated Mega wording, clarifies that manual browser download of the same archive is acceptable on local systems, and adds a stronger advanced/custom/hardware caution with direct contact info
- Drone Show now separates the tracked stock SITL demo origin (`data/origin.sitl.default.json`) from the mutable runtime origin override (`data/origin.json`), and the stock Azadi Stadium default is shared by both GCS origin fallback and `startup_sitl.sh`
- The shipped SITL Drone Show bundle now matches the stock 5-drone SITL config end-to-end, and packaged Drone Show metrics were refreshed so stock assets no longer drift from config
- Superseded running Drone Show missions now report a terminal execution result back to GCS instead of leaving command tracking stuck in `executing`
- GCS HTTPS/demo installs now write `MDS_GIT_AUTO_PUSH=false` into `/etc/mds/gcs.env`, and dashboard imports/saves fail fast instead of hanging on interactive push prompts
- Drone Show dashboard surfaces now avoid misleading empty export/visualization states before any show is imported, and the custom CSV confirmation path is explicit about its local-only execution model
- All GCS server components migrated from `gcs_logging`/`logging_config` to `mds_logging`
- All drone-side components migrated from `configure_logging()`/inline setup to `mds_logging`
- CLI flags unified: `--debug` replaced with `--verbose`/`--debug`/`--quiet`
- Backend compatibility shims and test helpers now match the current FastAPI/httpx websocket path, telemetry schema, and session ordering behavior so the full regression suite stays green on current dependencies
- `multiple_sitl/startup_sitl.sh` now keeps runtime repo sync via `git fetch/reset`, only reinstalls Python requirements when `requirements.txt` changes, and bounds container-side file logs by default
- Docker SITL image prep now preserves the real PX4 git/submodule metadata, records PX4 provenance in image metadata files, and makes the startup repo auto-sync behavior explicit as mutable latest-on-boot mode
- Docker SITL launcher now persists wrapper-level startup diagnostics, strips repetitive PX4 shell prompt noise from `sitl_simulation.log`, and waits for PX4/router/coordinator readiness before reporting success
- `tools/build_custom_image.sh` now produces flattened custom images instead of layering more state through `docker commit`
- SITL image preparation/build docs now pin PX4 plus baked `mavsdk_server` inside the image, pass `MDS_MAVSDK_VERSION` / `MDS_MAVSDK_URL` through the image-build path, and use updated MAVSDK release asset naming for current releases
- SITL public setup docs now separate pinned validated releases from mutable latest-on-boot development mode, add a dedicated custom release workflow guide, and refresh FastAPI startup/version guidance for current GCS deployment behavior
- Root and docs index READMEs now reflect the current MDS 5 scope more accurately, including QuickScout SAR, trajectory planning, unified logging, and the current SITL/custom-release workflow paths
- Smart Swarm now refreshes GCS-backed assignments before startup role selection, exposes compact swarm-runtime controls in the dashboard, and uses a safer `upstream_or_hold` leader-loss default instead of cross-cluster numeric fallback
- Smart Swarm runtime controls now default to `Selected Drone`, with explicit `Selected Cluster` scope for formation-level actions so mixed missions stay predictable
- Smart Swarm dashboard flow now includes a clearer `Formation Preview`, live readiness snapshot, scoped start blockers, explicit cluster-target semantics, and less redundant ready-state noise on drone cards
- Smart Swarm follower recovery now restarts offboard cleanly on follower re-entry, waits for state lock before sending setpoints, and treats stale leader telemetry as a failover condition
- GCS swarm updates now reject follow-chain cycles both for dashboard saves and live `/request-new-leader` changes
- Smart Swarm predictor/control internals now use corrected grouped-state Kalman process noise, incremental prediction timing, and leader-velocity feedforward to reduce formation lag
- Smart Swarm leader-change notifications now update only `follow` in GCS so failover or runtime reassignment does not overwrite fresher operator-edited offsets/frame values
- GCS launcher logging is now quieter by default: duplicate raw access logs are disabled unless `MDS_GCS_ACCESS_LOGS=true`, and noisy third-party HTTP client debug output is suppressed so Smart Swarm/runtime signal stays readable
- GCS launchers now set console logging deterministically through `MDS_GCS_CONSOLE_LOG_LEVEL` (default `INFO`), so inherited shell/debug state does not silently make the first-run tester flow noisy
- Smart Swarm and GCS polling paths now use named transport timeout parameters instead of scattered literals, including follower leader-state fetches, GCS swarm-config refresh, leader-change notify, and GCS drone telemetry/git pulls
- Routine successful command-status polling (`GET /command/<id>`) and internal execution-result callbacks are now treated as `DEBUG` request noise instead of `INFO`
- Drone config lookups no longer spam routine `INFO` lines during normal runtime polling
- SITL and Smart Swarm docs now reflect Python 3.11+ manual requirements, the optional nature of external NetBird/MAVLink routing, the stock 5-drone SITL config limit, and the validated Smart Swarm acceptance flow
- SITL distribution docs now treat third-party `megatools` as public-download-only and standardize authenticated archive replacement on official `MEGAcmd`, including the refreshed public archive link for the current validated image
- README and Smart Swarm docs now spell out the first dashboard-driven Smart Swarm operator path from `Overview` readiness checks through `Swarm Design` runtime control

### Removed
- `gcs-server/logging_config.py` (857 lines, DroneSwarmLogger)
- `gcs-server/gcs_logging.py` (PYTHONPATH workaround wrapper)
- `src/logging_config.py` (drone-side logging config)
- `configure_logging()` function from `drone_show_src/utils.py`
- `setup_logging()` function from `functions/file_management.py`
- All `logging.basicConfig()` calls across the codebase

---

## [5.0] - 2026-02-24

### Added
- **QuickScout SAR/Reconnaissance Module**: Multi-drone cooperative area survey
  - New mission mode: `QUICKSCOUT = 5` with boustrophedon coverage planning
  - Boustrophedon (lawn-mower) coverage path planner with Shapely polygon operations
  - ENU coordinate conversion via pymap3d for accurate local planning
  - Automatic sector partitioning and GPS-proximity drone assignment
  - PX4 Mission Mode executor (`quickscout_mission.py`) with MAVSDK mission upload
  - Mission lifecycle management: plan, launch, pause, resume, abort
  - Point of Interest (POI) management with CRUD operations
  - Terrain-following altitude adjustment
  - Camera trigger actions at configurable intervals
- **SAR API Endpoints**: FastAPI APIRouter at `/api/sar`
  - Coverage planning, mission control, drone progress, POI, and elevation endpoints
  - Thread-safe singleton managers for mission state and POI storage
- **QuickScout Dashboard Page**: Full Plan/Monitor UI
  - Mapbox GL polygon drawing for search area definition
  - Coverage path preview with per-drone color coding
  - Real-time drone progress monitoring with status cards
  - Interactive POI marker system
  - Survey configuration panel with advanced options
- **SAR Test Suite**: Schema validation, coverage planner algorithm, and API endpoint tests
- **New Dependencies**: `shapely>=2.0.0` and `pymap3d` (GCS server only), `@mapbox/mapbox-gl-draw` (frontend)
- **Documentation**: `docs/quickscout.md` with architecture, API reference, and configuration guide

---

## [4.5] - 2026-02-24

### Added
- **Automated mavlink-router Integration**: Dashboard binary auto-download, systemd service setup via `mavlink_setup.sh`

### Changed
- **Config/Swarm migrated from CSV to JSON** (`v4.5.0-config-json`):
  - `config.csv` → `config.json`, `swarm.csv` → `swarm.json` (same for SITL variants)
  - JSON envelope format: `{"version": 1, "drones": [...]}` / `{"version": 1, "assignments": [...]}`
  - Native types: `mavlink_port`/`baudrate` as int, `follow` as int
  - Pydantic schemas with `extra='allow'` for user-defined custom fields (e.g. `color`, `notes`)
  - Shell scripts use `jq` for config parsing (dependency checked at runtime)
  - Dashboard: JSON import/export (primary), CSV import as fallback
  - Resource templates updated (10 files)
  - One-time migration tool: `tools/migrate_csv_to_json.py`
  - Guide: `docs/guides/config-json-format.md`
- **Swarm offset fields renamed** for clarity and extensibility:
  - `offset_n/offset_e/offset_alt` → `offset_x/offset_y/offset_z`
  - `body_coord` (bool) → `frame` (enum: `"ned"` | `"body"`)
  - Meaning of x/y/z depends on frame (ned: North/East/Up; body: Forward/Right/Up)
  - `offset_z` is always positive-up regardless of frame

---

## [4.4] - 2026-01-30

### Changed
- Version bump for enterprise services and configuration improvements

---

## [4.3] - 2026-01-28

### Added
- **Enhanced Repository Management**: Interactive fork vs default repository selection
  - Clear read-only warning for default repo users
  - SSH access detection for collaborators
  - Fork configuration verification (matches RPi init behavior)
- **NetBird VPN Integration**: VPN networking guidance in installation summary
  - New guide: `docs/guides/netbird-setup.md`
  - Network architecture diagrams
  - Step-by-step setup instructions
- **CLI Improvements**: New `--fork` option for `install_gcs.sh`
  - Quick fork setup: `curl ... | sudo bash -s -- --fork username`
  - Better error messages and guidance

### Changed
- **Repository Selection Flow**: Separated "what repo" from "how to access"
  - Step 1: Choose official repo or your own fork
  - Step 2: Choose HTTPS or SSH access
  - SSH recommended for production (enables git sync)
- **Path Resolution**: Fixed PYTHONPATH for GCS server module imports
  - Works correctly from any execution directory
  - Explicitly sets PROJECT_ROOT in PYTHONPATH
- **Documentation**: Updated gcs-setup.md with repository options and VPN networking

### Fixed
- **Module Import Issues**: GCS server can now find functions module from any path
- **Version Consistency**: All files updated to 4.3.0

---

## [4.2] - 2026-01-28

### Added
- **Unified MDS Branding**: Consistent ASCII art banner across all initialization scripts
  - New shared banner file: `tools/mds_banner.sh`
  - `print_mds_banner()` function for consistent display
  - `get_git_info()` function for git branch/commit retrieval
- **Version/Git Info at Startup**: All scripts now display version, branch, and commit at startup
  - GCS bootstrap shows version and branch during installation
  - GCS init displays version, branch, commit, and timestamp
  - RPi init displays version, branch, commit, and timestamp
  - Dashboard startup shows version and git info

### Changed
- **Banner Unification**: All scripts now use the same MDS ASCII art
  - `tools/install_gcs.sh`: Replaced box-drawing banner with unified banner
  - `tools/mds_gcs_init.sh`: Uses shared banner with git info
  - `tools/mds_gcs_init_lib/gcs_common.sh`: Sources shared banner
  - `tools/mds_init.sh`: Uses shared banner with git info
  - `tools/mds_init_lib/common.sh`: Sources shared banner
  - `app/linux_dashboard_start.sh`: Replaced wide ASCII with unified banner
- **Version Synchronization**: All version numbers updated to 4.2.0
  - `GCS_VERSION` in gcs_common.sh
  - `MDS_VERSION` in common.sh
  - `MDS_BANNER_VERSION` in mds_banner.sh
  - Documentation updated (README.md, docs/README.md, gcs-setup.md)

---

## [4.1] - 2026-01-24

### Added
- **GCS Initialization System**: Enterprise-grade VPS/Ubuntu GCS setup
  - One-line installation: `curl ... | sudo bash`
  - Comprehensive `mds_gcs_init.sh` with 9 phases
  - Library modules for prereqs, Python, Node.js, firewall, etc.
- **Documentation Updates**: GCS setup guide and documentation links

---

## [4.0] - 2026-01-20

### Added
- **Enterprise Raspberry Pi Initialization**: Production-ready `mds_init.sh`
  - Modular library architecture in `mds_init_lib/`
  - 13 installation phases with state tracking
  - Resume capability for interrupted installations
  - SSH key management for git sync
- **Production Dashboard Startup**: Enhanced `linux_dashboard_start.sh`
  - FastAPI/Flask backend selection
  - Development and production modes
  - tmux session management

---

## [3.8] - 2025-11-07

### Added
- Automated version bump (minor)

### Changed
- See commit history for detailed changes

---


## [3.7] - 2025-11-07

### Added
- **Comprehensive Project Cleanup**: Removed 14 unnecessary files and directories from root
  - Removed backup files: `config.csv.backup`, `config_sitl.csv.backup`
  - Removed old code backups: `drone_show_bak.py`, `smart_swarm_old.py`
  - Removed test/experimental scripts: `offboard_multiple_from_csv.py`, `test_config_*.py`
  - Removed empty npm artifacts: `drone-dashboard@1.0.0`, `react-scripts`
  - Removed misplaced `package-lock.json` from root (React is in `app/dashboard/drone-dashboard/`)
- **.gitignore Enhancements**: Added patterns to prevent future clutter
  - Backup files: `*.backup`, `*.bak`, `*_bak.py`, `*_old.py`
  - Binary executables: `mavsdk_server*`
  - Empty npm artifacts: `react-scripts`, `drone-dashboard@*`
  - Test scripts in root: `/test_config*.py`, `/offboard_multiple*.py`
- **PolyForm Dual Licensing**: Professional open-source licensing framework
  - PolyForm Noncommercial 1.0.0 for education, research, non-profits
  - PolyForm Small Business 1.0.0 for small commercial operations (< 10 drones, < $1M revenue, < 100 employees)
  - Custom commercial licensing for large operations
  - Comprehensive legal protection: LICENSE, DISCLAIMER.md, NOTICE, ETHICAL-USE.md

### Fixed
- **Critical UX Issue - Modal Dialog Centering**: Confirmation dialogs now properly center in viewport
  - Implemented React Portal for modal rendering (CommandSender.js)
  - Modal now renders to `document.body` instead of inline in container
  - Users no longer need to scroll to find confirmation dialogs - major UX improvement
- **React Console Warnings Resolved**:
  - Removed 6 debug `console.log()` statements from `missionConfigUtilities.js`
  - Fixed "assign before export" warning in `version.js` by refactoring export pattern
  - Updated `tools/version_sync.py` to generate ESLint-compliant JavaScript exports
  - Kept appropriate `console.error()` statements for error handling

### Changed
- **JavaScript Export Pattern**: Modernized version.js and auto-generation script
  - Declare constants first, then export (ESLint best practice)
  - Updated `tools/version_sync.py` template to generate compliant code
- **Legal Documentation Structure**: Confirmed LICENSE files correctly placed in root per industry standards
  - LICENSE, NOTICE, DISCLAIMER.md remain in root (GitHub/Apache/Google best practice)
  - Dual licensing structure clearly documented for easy discovery

---

## [3.6] - 2025-11-06

### Added
- **Documentation Restructure**: Comprehensive reorganization of all project documentation
  - Created organized folder structure: `docs/quickstart/`, `docs/guides/`, `docs/features/`, `docs/hardware/`, `docs/api/`
  - Created `docs/archives/` for historical documentation and implementation summaries
  - New documentation index at `docs/README.md` for easy navigation
- **Versioning System**: Unified version management across entire project
  - Single source of truth: `VERSION` file in project root
  - Automated version synchronization script: `tools/version_sync.py`
  - Dynamic version display in dashboard with git commit hash
  - Versioning workflow guide at `docs/VERSIONING.md`
- **CHANGELOG.md**: Separate, structured changelog following Keep a Changelog format
- **GCS Configuration Enhancements**:
  - Dashboard .env file auto-update feature for GCS IP changes
  - Checkbox option to update `REACT_APP_SERVER_URL` when changing GCS IP
  - User warnings about rebuild requirements and server location
- **UI/UX Production Improvements**:
  - Origin coordinate display with responsive multi-line layout
  - GPS coordinates truncated to 6 decimal places (0.11m accuracy)
  - Modal dialogs now center on viewport instead of container
  - Comprehensive toast notifications for save operations with git status
  - Save button renamed to "Save & Commit to Git" for clarity

### Changed
- **README.md**: Cleaned and streamlined for professional presentation
  - Added table of contents
  - Removed embedded version history (moved to CHANGELOG.md)
  - Better separation of quick start vs comprehensive guides
  - Improved navigation and structure
- **Documentation Organization**:
  - Moved implementation summaries to `docs/archives/implementation-summaries/`
  - Moved legacy docs (v2.0, HTML, PDF) to `docs/archives/`
  - Renamed and relocated current docs to new folder structure
  - Dashboard README customized for MDS (was generic Create React App template)
- **Dark Mode Fixes**:
  - Fixed unreadable metric boxes in ManageDroneShow page
  - Replaced MUI inline styles with CSS variables for theme compatibility
  - Added 80+ lines of dark mode compatible CSS
- **Version Display**: Dashboard sidebar now shows `v3.6 (git-hash)` dynamically

### Fixed
- GCS configuration dialog showing empty "Current IP" field (nested data structure issue)
- GCS IP not differentiating between SITL mode (172.18.0.1) and Real mode (100.96.32.75)
- Confirmation dialogs requiring scroll to see (viewport centering issue)
- No visual feedback during configuration save/commit operations
- Origin GPS coordinates overflowing container
- Dark mode color accessibility in VisualizationSection components

---

## [3.5] - 2025-09

### Added
- **Professional React Dashboard** with expert portal-based UI/UX using React Portal architecture
- **3D Trajectory Planning** with interactive waypoint creation, terrain elevation, and speed optimization
- **Enhanced Mobile Responsiveness** with touch-friendly interface and responsive design
- **Smart Swarm Trajectory Processing** with cluster leader management and dynamic formation reshaping
- **Expert Tab Navigation** with professional mission operations interface
- **Advanced UI/UX Improvements** with modal overlays, responsive design, and touch-friendly controls

### Changed
- Complete dashboard redesign with modern React patterns

### Fixed
- Multiple bug fixes and performance improvements for production deployment

---

## [3.0] - 2025-06

### Added
- **Smart Swarm Leader–Follower System**: Fully operational with leader failover, auto re-election, and seamless follower sync
- **Global Mode Setpoints**: Unified approach for both offline and live missions
- **Enhanced Failsafe Checks**: Comprehensive preflight health checks and in-flight monitoring
- **Stable Startup Sequence**: Three-way handshake mechanism ("OK-to-Start" broadcast)
- **Unified All-in-One System**: Single platform for both drone shows and live swarm operations

### Fixed
- Race condition issues under high CPU load (GUIDED → AUTO transitions)
- Emergency-land command reliability during mode transitions
- Network buffer tuning for large-scale simulations (100+ drones)

---

## [2.0] - 2024-11

### Added
- Enhanced React GUI with improved user experience
- Robust Flask backend architecture
- Comprehensive drone-show scripts
- Docker SITL environment for testing
- [100-Drone SITL Test Video](https://www.youtube.com/watch?v=VsNs3kFKEvU)

### Changed
- Major GUI overhaul
- Backend infrastructure improvements

---

## [1.5] - 2023-08

### Added
- Mission configuration tools
- SkyBrush CSV converter utility
- Expanded MAVLink2REST integration

---

## [1.0] - 2023-03

### Added
- **Stable Release Milestone**
- Flask web server implementation
- Professional API structure

### Removed
- UDP dependencies (replaced with more reliable protocols)

---

## [0.8] - 2022-09

### Added
- Major GUI enhancements
- Kalman-filter–based swarm behaviors
- Optimized cloud SITL performance

---

## [0.7] - 2022-04

### Added
- React GUI for real-time swarm monitoring
- Docker automation for PX4 SITL environments

---

## [0.6] - 2021-12

### Added
- Complex leader/follower swarm control capabilities
- Docker-based SITL environment

---

## [0.5] - 2021-07

### Added
- Basic leader/follower missions on real hardware
- Enhanced GCS data handling

---

## [0.4] - 2021-02

### Added
- `Coordinator.py` for advanced swarm coordination
- Improved telemetry and command systems

---

## [0.3] - 2020-10

### Added
- SkyBrush CSV processing integration
- Code optimizations for drone show performances

---

## [0.2] - 2020-06

### Added
- Multi-drone support with offset/delayed CSV trajectories

---

## [0.1] - 2020-03

### Added
- Initial release
- Single-drone CSV trajectory following
- Basic MAVSDK integration

---

## Release Types

- **Major Version (X.0)**: Significant architectural changes, breaking changes, or major new features
- **Minor Version (X.Y)**: New features, improvements, and non-breaking changes

---

© 2025 Alireza Ghaderi | Licensed under CC BY-NC-SA 4.0
