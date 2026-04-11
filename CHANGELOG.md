# Changelog

All notable changes to MAVSDK Drone Show (MDS) project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses simple two-part versioning: `X.Y` (Major.Minor).

---

## [Unreleased]

### Added
- QuickScout runtime monitoring now treats MAVSDK mission-progress callbacks as
  optional hints instead of the sole completion signal, adds bounded upload /
  start / airborne / post-action timeouts plus a bounded arm-RPC timeout in the
  shared startup seam, and keeps slot-plus-hardware identity visible in the
  QuickScout monitor cards so live operator context stays consistent with the
  wider enrollment / identity doctrine
- a 2026-04-10 enrollment/identity release-closeout note documenting the
  explicit slot-vs-hardware operator doctrine across Mission Config, Smart
  Swarm, Swarm Trajectory, QuickScout, and Fleet Enrollment, the shared UI
  identity guidance strips, the detached-worktree git/runtime fixes, the full
  green Hetzner `operator_regression` acceptance pass, and the refreshed public
  SITL archive publication
- a 2026-04-10 node-enrollment phase closeout note documenting the final
  `hw_id` / `pos_id` / `mav_sys_id` doctrine, the operator decision tree for
  new-node acceptance versus same-airframe recovery versus spare replacement
  versus ordinary slot swaps, the Smart Swarm `hw_id` rationale, and the
  remaining explicit post-v1 debt
- a 2026-04-10 combined node-enrollment and `mavlink-anywhere` review note
  documenting the final bootstrap/enrollment scenario guidance, the clarified
  `hw_id` / `pos_id` targeting doctrine, the current on-device identity files,
  the QuickScout slot-selection consistency fix, and the non-breaking
  improvement plan for `mavlink-anywhere`
- explicit 2026-04-10 identity-targeting doctrine guidance documenting when
  MDS should stay `hw_id`-anchored versus when high-level mission planners may
  remain `pos_id`-anchored and resolve to current hardware at launch, plus
  clarified bootstrap-wrapper versus init-engine usage and on-device identity
  file locations
- a 2026-04-10 consolidated node-enrollment and identity-alignment brief
  documenting the current bootstrap/candidate/enrollment workflows, the
  scenario-by-scenario operator guidance, the `hw_id` / `pos_id` / `mav_sys_id`
  doctrine for cross-mode consistency, the public standards references checked,
  and the explicit post-v1 `mavlink-anywhere` / identity-model follow-up debt
- a 2026-04-10 node-bootstrap and fleet-enrollment v1 recap note documenting
  the implemented workflow boundaries, the operator scenarios for accept /
  replace / recover, the current post-v1 deferred items, and the tester-facing
  caveats for hardware rollout and future automation
- a 2026-04-10 node-bootstrap candidate-announce checkpoint note documenting
  the new canonical `mds_node_announce.sh` helper, the `mds_node_init.sh`
  announce integration, the expanded node manifest/bootstrap report fields, the
  active docs/headless-automation cleanup, and the paired local / Hetzner
  validation results
- a 2026-04-10 fleet-enrollment operator-workflow checkpoint note
  documenting the dedicated `Fleet Enrollment` page, the new same-hardware
  recovery route, the retirement of the old `ReplaceDroneWizard`, the Mission
  Config cutover onto the canonical enrollment workflow, and the paired local /
  Hetzner validation results
- a 2026-04-10 Mission Config pending-enrollment cutover checkpoint note
  documenting the removal of heartbeat-driven auto-add, the new derived
  pending-candidate review panel, the replacement-wizard standby-node reuse,
  and the focused Hetzner validation/build results for the safer fleet
  enrollment transition
- a 2026-04-10 node-bootstrap phase 1 foundation checkpoint note documenting
  the generic companion-node bootstrap cleanup, the new
  `/etc/mds/node_identity.json` manifest, the optional `--report-json` machine
  output seam, the active-doc alignment for cloning/automation workflows, and
  the validation boundary before candidate-enrollment work begins
- a 2026-04-10 node-bootstrap and fleet-enrollment design brief documenting
  the current `install_mds_node.sh` / `mds_node_init.sh` provisioning stack audit, the
  recommendation to retire heartbeat-driven auto-add and the deprecated
  `raspberry_setup.sh` path, the proposed candidate-registration workflow,
  the real-hardware replacement/recovery scenarios, and the phased automation /
  MCP-friendly implementation plan
- deferred guidance for converging `INIT_SYSID` onto the shared PX4 parameter
  service later, while keeping it out of the main runtime PX4 Parameters page
  until the broader action-pipeline audit is active, plus explicit deferral of
  firmware/build identity display until a clean vehicle-served source is added
- a 2026-04-09 PX4 Parameters scan-first UI refinement note documenting the
  dialog-first desktop/mobile inspection flow, the reduced compact-card and
  desktop-table density, the cleaner metadata grouping, the refreshed Hetzner
  browser stack, and the focused frontend validation/build results
- explicit PX4 parameter metadata-source-order guidance documenting the
  production doctrine for vehicle-served metadata, local PX4 catalog fallback,
  optional read-only docs caching, and the deferred hardware-grade metadata
  cache follow-up
- a 2026-04-09 PX4 Parameters responsive handoff refinement note documenting
  the compact/mobile inspector flow, the explicit skip-offline batch behavior,
  the tracked single-drone PX4 reboot control, and the refreshed Hetzner
  frontend validation/build results
- a 2026-04-09 PX4 parameter workspace phase 2 checkpoint note documenting the GCS diff/import/patch-job routes, the new dashboard `PX4 Parameters` page, the reusable runtime validator scaffold, the batch scope reuse, and the paired backend/Hetzner frontend validation results
- `docs/px4-parameters.md`, a dedicated operator/developer guide for the new GCS-managed PX4 parameter workflow, metadata source rules, QGC interoperability, and current deferred follow-up items
- a 2026-04-09 PX4 parameter-management foundation checkpoint note documenting the new shared `px4-params` models, the drone-local MAVSDK param facade, the canonical drone/GCS snapshot routes, the runtime docs-link policy envelope, and the focused `50 passed` backend validation batch
- a 2026-04-09 PX4 parameter-management design brief documenting the current raw-MAVSDK-only state, the recommended dedicated `px4-params` subsystem, the planned single-drone and batch workflows, the QGC/PX4/MAVLink research findings, and the phased implementation plan
- a 2026-04-08 QuickScout tester-handoff checkpoint note documenting the implemented v1 feature set, the shared map/workspace consistency review versus Swarm Trajectory, the current post-v1 debt, and the recommended browser test flows and expected outcomes
- a 2026-04-08 QuickScout template-complete runtime-validation phase 18 checkpoint note documenting the new area/corridor runtime builders, the reusable template-regression SITL plans, the live Hetzner area/corridor drills, and the passing reset-backed QuickScout template regression suite
- a 2026-04-08 QuickScout findings-aware runtime-validation phase 17 checkpoint note documenting the live single-drone and multi-drone handoff/evidence validator passes, the updated reusable QuickScout plan semantics, and the narrowed remaining post-v1 QuickScout debt
- a 2026-04-08 QuickScout findings cleanup and follow-up checkpoint note documenting the findings-only contract cleanup, the removal of public `/api/sar/poi` aliases, the finding-led follow-up search seed flow, the map focus fix, and the paired local/Hetzner validation results
- a 2026-04-08 QuickScout multi-drone SITL-platform checkpoint note documenting the new reusable `quickscout` validator mode, the stable bundled `quickscout_runtime` plan, the multi-drone last-known-point runtime drill, and the paired local/Hetzner validation results
- a 2026-04-08 QuickScout runtime-validation checkpoint note documenting the live launch-path debugging chain, the fresh-container Hetzner validator pass, the local regression additions for the mission executor, and the remaining next-slice QuickScout execution work
- a 2026-04-08 QuickScout execution-semantics phase 13 checkpoint note documenting the new operator-facing mission phases, honest control-availability contract, follow-up-planning guidance, and the paired local/Hetzner validation results
- a 2026-04-08 QuickScout point-geometry phase 9 checkpoint note documenting the point-search geometry utility, the point-centered map radius preview, the derived footprint guidance, and the focused Hetzner frontend validation/build results
- a 2026-04-08 QuickScout template-foundation phase 8 checkpoint note documenting the new mission-template contract, the first `last_known_point` search flow, the template-aware workspace recovery/signature logic, and the paired local/Hetzner validation results
- a 2026-04-08 QuickScout launch-review phase 7 checkpoint note documenting the new stale-package recompute gate, the shared preflight-backed launch-review card, the planning-signature and launch-readiness utilities, and the focused Hetzner frontend validation/build results
- a 2026-04-08 QuickScout mission-briefing phase 6 checkpoint note documenting the new durable mission label/profile/brief metadata, the recovered workspace hydration updates, the mission-catalog display improvements, and the paired local/Hetzner validation results
- a 2026-04-08 QuickScout operator setup phase 5 checkpoint note documenting the new planning profile presets, explicit QuickScout end-behavior controls, the operator-setup sidebar refactor, and the focused Hetzner validation/build results
- a 2026-04-08 QuickScout workspace recovery UI phase 4 checkpoint note documenting the reusable saved-mission workspace panel, the QuickScout page recovery/hydration flow, the new page-level recovery tests, and the focused Hetzner validation/build results
- a 2026-04-08 QuickScout recovery phase 3 checkpoint note documenting the new mission catalog/workspace recovery endpoints, the matching SAR frontend service hooks, the route-inventory update, and the paired local/Hetzner validation results
- a 2026-04-08 QuickScout command-lifecycle phase 2 checkpoint note documenting the shared tracked-submit extraction, the new QuickScout tracked launch/control responses, the mission-scope targeting fix, the abort-behavior mapping fix, and the paired local/Hetzner validation results
- a 2026-04-07 QuickScout foundation phase 1 checkpoint note documenting the new durable SQLite-backed QuickScout store, the backend service boundary that replaces the old in-memory mission/POI managers, the stricter live-GPS planning gate, the camera-interval waypoint persistence, and the focused backend validation results
- a 2026-04-07 Mission Config launch-map polish checkpoint note documenting the Google-satellite default, tighter launch-layout fit behavior, zoom-adaptive marker styling, always-reviewable Origin status affordance, and the focused Hetzner React validation/build results
- a 2026-04-07 Mission Config actionable-alert checkpoint note documenting the new clickable Mission Config review alerts, the origin-loading versus origin-missing distinction, the origin-workflow jump action, the zero-origin Mission Layout export fix, and the focused Hetzner React validation/build results
- a 2026-04-07 Mission Config launch-map and git-sync finalization checkpoint note documenting the new expected/live Leaflet launch map, zero-origin handling fix, click-through card parity, explicit sync target branch/commit reporting, and the final live Hetzner runtime cleanup
- a 2026-04-07 advanced SITL regression checkpoint note documenting the new integrated mixed-mode leader-override validator, the runtime mission-state root-cause fix, the green Hetzner `integrated_mixed_mode` and `advanced_operator_regression` runs, and the updated advanced-plan documentation
- a 2026-04-06 Phase 4 UI closeout note documenting the shortened Overview scope guidance, the compacted preflight strip, the reduced Mission Details readiness/timing copy, and the paired Hetzner Jest/build validation results
- a 2026-04-06 Mission Config / command-surface cleanup phase 4 checkpoint note documenting the compressed Mission Config ops shell, the plot/map launch-layout toggle, the shorter command/mission copy, the Custom Show token overrides, the tablet-width trajectory compact behavior, and the paired Hetzner Jest/build validation results
- a 2026-04-06 trajectory-authoring phase 3 checkpoint note documenting the map-first Trajectory Planning layout, the docked compact route-review surface, the collapsed Swarm Trajectory workspace-review flow with related-tool links, the map resize/fly-to fixes, the focused trajectory Jest coverage, and the paired Hetzner build result
- a 2026-04-06 shared operator-scope phase 2 checkpoint note documenting the explicit visible-cards-to-command-scope bridge, the new card-level command-scope markers, the shared Overview-owned target state, the build-found PropTypes/hook fixes, and the paired Hetzner Jest/build validation results
- a 2026-04-06 Mission Config architecture-reset phase 1 checkpoint note documenting the issue-first Mission Config workspace shell, the compacted assignment-card default view, the corrected secondary tool-panel layout, the Precision Move lint-warning cleanup, and the paired Hetzner Jest/build validation results
- a 2026-04-06 Precision Move phase 2 checkpoint note documenting the operator-control-surface cleanup, the new Planned Move vs Live Jog behavior, the reduced dialog verbosity, the improved frame wording, the terminal-status tone cleanup, the low-bandwidth command-submit timeout safeguard, and the paired Hetzner React validation results
- a 2026-04-06 Precision Move operator-UX refinement checkpoint note documenting the compact controller-style dialog layout, folded manual/tuning sections, shared scope-edit return path, live command-status strip, runtime policy endpoint, and the paired backend/frontend validation results
- a 2026-04-06 Precision Move SITL validation checkpoint note documenting the fixed fresh-container branch-sync boot path, the green live Hetzner 3-drone Precision Move action run, the validator false-negative fixes, and the confirmed immediate-action override semantics
- a 2026-04-06 Precision Move phase 1 checkpoint note documenting the new `PRECISION_MOVE (112)` action, the typed command/executor path, the dedicated dashboard dialog, the quick-control and direct-HOLD refinements, the reusable SITL validator extension, the fresh-container git-sync bootstrap fix, and the remaining deferred follow-up items
- a 2026-04-04 SITL release refresh checkpoint note documenting the final deferred-debt audit result, the low-space release packaging fix, the stale Hetzner validation-tree cleanup, and the refreshed packaged image publication flow
- a 2026-04-04 SITL plan-library checkpoint note documenting the checked-in `tools/sitl_plans/` scenario library, the named-plan CLI entrypoint, the currently validated scenario coverage, and the deferred advanced combined-mode boundary
- a 2026-04-04 SITL validation-platform phase 2 checkpoint note documenting the new Mission Config/origin runtime validator, the `config_only` template, the host-agnostic validator/runtime-root guidance, the full live Hetzner operator-regression pass, and the updated AI-agent/runtime docs
- a 2026-04-04 SITL clean-image regression checkpoint note documenting the stale mixed-runtime finding, the fully green Hetzner operator-regression run on a rebuilt pinned image, and the post-validation host cleanup
- a 2026-04-04 SITL validation-platform checkpoint note documenting the new standalone action validator, the declarative suite templates/plan-file flow, deterministic dry-run/provenance output, explicit QuickScout deferral, and the focused local/Hetzner validation results
- a 2026-04-04 API closeout checkpoint note documenting the websocket-contract cleanup, the explicit deferred API follow-ups, the standing rules for future API additions, and the focused validation results
- a 2026-04-04 Swarm Trajectory typed-contract checkpoint note documenting the typed success models, OpenAPI request/response cleanup, operational failure normalization, and the paired local/Hetzner validation results
- a 2026-04-04 subsystem error-envelope checkpoint note documenting the Swarm Trajectory error-contract cleanup, the QuickScout/Swarm Trajectory OpenAPI response-metadata alignment, and the focused subsystem validation results
- a 2026-04-04 GCS error-envelope and typed-mutation checkpoint note documenting the shared FastAPI error contract, the typed request-model cleanup for fleet/origin/swarm/show-management/GCS-config routes, and the paired local/Hetzner validation results
- a 2026-04-04 command-submit idempotency checkpoint note documenting the canonical `idempotency_key` contract, the replay-safe command tracker path, the replay/conflict response semantics, and the paired local/Hetzner validation results
- a 2026-04-04 command-contract canonicalization checkpoint note documenting the canonical snake_case command envelope, the backend/frontend/runtime caller migration, the refreshed command API docs, the paired local/Hetzner validation results, and the remaining merge-readiness review debt
- a 2026-04-04 drone canonicalization checkpoint note documenting the shared drone route constants, the canonical `/api/v1/git/status` and `/api/v1/navigation/position-deviation` routes, the retirement of the legacy drone business aliases, the HTTP/WebSocket state serializer alignment, and the paired local/Hetzner validation results
- a 2026-04-03 API-modernization review audit note documenting why the stream is not yet merge-ready, with the remaining drone-side contract, caller-migration, schema, and documentation slices required before any merge to `main`
- a 2026-04-03 GCS telemetry contract-cleanup checkpoint note documenting the retirement of the duplicate GCS telemetry aliases, the removal of the fake command-cancel endpoint, the validator migration onto canonical health/telemetry routes, and the LAND/RTL timeout fallback fix
- a 2026-04-03 SITL suite runtime-root fix checkpoint note documenting the reusable multi-mode validator, the stale live gunicorn restart on Hetzner, the validator-root/runtime-root split, and the corrected end-to-end live 3-drone suite pass across Drone Show, Smart Swarm, and Swarm Trajectory
- a 2026-04-03 stream-surface codification checkpoint note documenting the third Phase 5 API-modernization slice, the explicit WebSocket transport-root policy, the shared GCS WebSocket route builders/constants, and the Hetzner Jest/build validation results
- a 2026-04-03 logging-domain hardening checkpoint note documenting the second Phase 5 API-modernization slice, the shared session-path validation, typed log-route models, the stable-root policy for `/api/logs/*` and `/api/sar/*`, and the paired local/Hetzner validation results
- a 2026-04-03 SAR router normalization checkpoint note documenting the first Phase 5 API-modernization slice, the QuickScout router-factory cleanup, the removal of the old `sys.path` import hack, and the paired local/Hetzner validation results
- a 2026-04-03 operational HTTP alias retirement checkpoint note documenting the sixteenth Phase 4 API-modernization slice, the removal of the last versionless heartbeat/network/git HTTP aliases, the runtime default-route cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 Swarm Trajectory v1-retirement checkpoint note documenting the fifteenth Phase 4 API-modernization slice, the retirement of the versionless Swarm Trajectory routes, the runtime-tool/frontend/doc cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 origin legacy-retirement checkpoint note documenting the fourteenth Phase 4 API-modernization slice, the removal of the old origin verb-style aliases, the route-resolver/request-log cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 command-control legacy-retirement checkpoint note documenting the thirteenth Phase 4 API-modernization slice, the removal of the old command verb-style aliases, the request-log and shared-route cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 show-management legacy-retirement checkpoint note documenting the twelfth Phase 4 API-modernization slice, the removal of the old show import/metrics/plot/deploy aliases, the shared frontend resolver cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 config/swarm legacy-retirement checkpoint note documenting the eleventh Phase 4 API-modernization slice, the removal of the GCS configuration/swarm verb-style aliases, the shared frontend resolver cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 legacy-route retirement audit note documenting the remaining GCS compatibility buckets as remove-now, keep-temporarily, and defer-with-reason so the remaining API cleanup can proceed deliberately
- a 2026-04-03 management/static legacy-retirement checkpoint note documenting the tenth Phase 4 API-modernization slice, the removal of the old GCS config/network/static plot aliases, the shared frontend resolver cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 git legacy-retirement checkpoint note documenting the ninth Phase 4 API-modernization slice, the removal of the deprecated one-off git detail endpoints, the route-inventory cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 canonical management/static v1 checkpoint note documenting the eighth Phase 4 GCS route-migration slice, the new `/api/v1/system/gcs-config`, `/api/v1/fleet/network-details`, and `/api/v1/swarm-trajectories/plots/{filename}` routes, the frontend caller migration, dead frontend helper removal, and the paired local/Hetzner validation results
- a 2026-04-03 canonical internal-caller cleanup checkpoint note documenting the seventh Phase 4 API-modernization slice, the shared drone/tool GCS route constants, the drone-side callback/bootstrap migration, and the paired local/Hetzner validation results
- a 2026-04-03 canonical show-management v1 checkpoint note documenting the sixth Phase 4 GCS route-migration slice, the new `/api/v1/shows/skybrush/*` and `/api/v1/shows/custom/*` routes, the shared frontend caller migration, and the paired local/Hetzner validation results
- a 2026-04-03 canonical git v1 checkpoint note documenting the fifth Phase 4 GCS route-migration slice, the new `/api/v1/git/status` and `/api/v1/git/sync-operations` routes, the request-log classification cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 canonical origin v1 checkpoint note documenting the fourth Phase 4 GCS route-migration slice, the new `/api/v1/origin*` routes, the bootstrap-resource naming cleanup, and the paired local/Hetzner validation results
- a 2026-04-03 canonical swarm-config v1 checkpoint note documenting the third Phase 4 GCS route-migration slice, the new `/api/v1/config/swarm` and `/api/v1/config/swarm/assignments/{hw_id}` routes, the internal caller migration, and the paired local/Hetzner validation results
- a 2026-04-03 canonical fleet-config v1 checkpoint note documenting the second Phase 4 GCS route-migration slice, the new `/api/v1/config/fleet*` aliases, the trajectory-start position contract cleanup, the frontend service migration, and the paired local/Hetzner validation results
- a 2026-04-03 canonical command v1 checkpoint note documenting the first Phase 4 GCS route-migration slice, the new `/api/v1/commands` and `/api/v1/command-reports/*` aliases, the frontend service migration, and the paired local/Hetzner validation results
- a 2026-04-03 Commands router extraction checkpoint note documenting the eighth Phase 3 backend route-domain split, the extracted Commands compatibility surface, the `submit_command` validation hardening, the `app_fastapi.py` monolith-route removal milestone, and the paired local/Hetzner validation results
- a 2026-04-03 Swarm Trajectory router extraction checkpoint note documenting the seventh Phase 3 backend route-domain split, the extracted trajectory-management compatibility surface, the malformed-JSON contract fix, the stale Flask duplicate removal, and the paired local/Hetzner validation results
- a 2026-04-03 Show Management router extraction checkpoint note documenting the sixth Phase 3 backend route-domain split, the extracted Drone Show / Custom Show compatibility surface, the helper move into `gcs-server/show_management.py`, the show-specific contract fixes, and the paired local/Hetzner validation results
- a 2026-04-03 Management and Static Assets router extraction checkpoint note documenting the fifth Phase 3 backend route-domain split, the GCS management/static compatibility surfaces moved out of `app_fastapi.py`, the explicit `save-gcs-config` stub contract, the static plot path-hardening work, the Hetzner validation-venv setup, and the paired backend/frontend validation results
- a 2026-04-03 Origin router extraction checkpoint note documenting the fourth Phase 3 backend route-domain split, the extracted origin/elevation surface, the compute-origin contract cleanup, the launch-position export behavior, and the combined local/Hetzner validation results
- a 2026-04-03 Git router extraction checkpoint note documenting the third Phase 3 backend route-domain split, the extracted Git REST/WebSocket surface, the preserved sync-helper seam in `app_fastapi.py`, and the combined local/Hetzner validation results
- a 2026-04-03 Configuration and Swarm router extraction checkpoint note documenting the second Phase 3 backend route-domain split, the modular config/swarm route move, the shared swarm-cycle validation move, the configuration error-status cleanup, and the combined local/Hetzner validation results across the extracted router suites
- a 2026-04-03 GCS core router extraction checkpoint note documenting the first Phase 3 backend route-domain split, the preserved `app_fastapi` patch seams, and the paired local/Hetzner backend validation results
- a 2026-04-03 API modernization phase 2 completion note documenting the remaining frontend caller migration, dead legacy frontend removal, auth/MCP readiness rules, Hetzner validation results, and the build hardening required for Node 22 on Hetzner
- a 2026-04-03 API modernization phase 2 checkpoint note documenting the core frontend caller migration onto the centralized GCS service layer, the focused Hetzner validation batch, the production build result, and the remaining route domains for the next slice
- a 2026-04-03 API contract audit phase 1 note documenting the live GCS/drone route inventory, the main naming and identity inconsistencies, the `/api/v1` migration target, and the staged MCP-ready API cleanup plan
- a 2026-04-01 dashboard UI hardening checkpoint note covering the live Hetzner mobile/tablet/desktop screenshot pass, the operator-console dashboard shell/theme changes, and the remaining runtime sync caveats before browser handoff
- a 2026-04-01 frontend audit checkpoint note documenting the recovered context, Hetzner-backed screenshot review, the responsive dashboard/trajectory work completed in this slice, and the explicit QuickScout follow-up todo for the next pass
- explicit operator documentation for compact identity shorthand `Pn|Hm` across the frontend field naming standard and config/identity guides, so recovered checkpoints and new operators can read dashboard scope labels without guessing
- a 2026-04-02 UI compact checkpoint note covering the Mission Config slot-state compaction, cluster count badge cleanup, explicit graph direction guidance, Hetzner validation results, and the deferred next-phase backlog
- `tools/publish_sitl_release_to_mega.sh`, a configurable session-first MEGA publish helper for packaged SITL releases that supports existing-session reuse, session-string login, optional stdin credential fallback, remote artifact replacement, public link export, and machine-readable output for operator or agent workflows

### Fixed
- the PX4 Parameters workspace no longer depends on MAVSDK’s older float-only
  component-information path for most metadata: drone-side snapshot rows now
  prefer PX4’s generated `parameters.json` catalog when available, which brings
  defaults, range, descriptions, units, reboot flags, and grouped metadata
  across integer and float parameters instead of leaving most rows value-only
- PX4 Parameters no longer falls back to the wrong desktop interaction model on
  touch devices that request browser “desktop mode”: compact card selection and
  the focused detail dialog now remain active on coarse-pointer narrow-physical
  devices, which keeps the page readable on phones/tablets
- the PX4 Parameters page no longer collapses into a desktop-only workflow on
  phone/tablet: compact view now uses searchable target selection, parameter
  cards, and a focused detail dialog instead of an unreadable grid-plus-inline
  inspector layout
- PX4 parameter metadata is no longer effectively hidden on compact screens:
  current/default/range/reboot/docs affordances now stay visible in the compact
  flow, and the single-drone workspace surfaces tracked inline status for
  snapshot refresh, write/import, and reboot operations
- batch PX4 profile/patch apply no longer hard-blocks the whole scope when some
  selected drones are offline; operators now get an explicit skip-offline
  confirmation path plus a clearer per-drone result summary
- PX4 Parameters no longer floods operators with raw floating-point precision:
  parameter values now use PX4 decimal hints when available and otherwise fall
  back to trimmed display precision, while compact/tablet widths keep the
  focused dialog flow instead of collapsing back into a below-table inspector
- PX4 parameter snapshots no longer depend solely on MAVSDK `GetAllParams`: drone-local snapshot refresh now waits for the target drone HTTP API to become healthy in live SITL, and the drone-side service falls back to the MAVLink parameter microservice on the routed local `14569` endpoint when the runtime MAVSDK server does not implement bulk parameter listing
- the PX4 parameter-management runtime no longer depends on a stale gRPC pin: `requirements.txt` now aligns with the installed `mavsdk 3.10.2` generated stubs by pinning `grpcio==1.71.0`, which fixes the live Hetzner backend import failure exposed during the first clean-sync PX4 smoke attempt
- the PX4 Parameters batch workspace test now waits for the fleet scope to finish loading before dispatching a patch, matching the real operator flow and preventing a false zero-target no-op during Jest validation
- QuickScout is no longer falsely tracked as “deferred” in the reusable SITL platform: the live runtime validator now supports stable multi-drone last-known-point drills, the suite exposes a first-class `quickscout` validator mode plus `quickscout_only` template and `quickscout_runtime` bundled plan, and the shared SITL docs now describe QuickScout as a dedicated gate included in the current mission/operator regression bundles
- QuickScout launch validation no longer stalls in a false "executing/searching" state on fresh SITL: the mission executor now boots its own MAVSDK server on the canonical gRPC port, coerces runtime CLI/action payloads safely, aligns mission items with the vendored MAVSDK signature, normalizes optional numeric fields such as `yaw_deg`, gates startup on the same local readiness/home signals the rest of the stack already trusts, marks the first mission item as a takeoff item, and passes the live Hetzner launch-hold-abort-reset validator end to end
- QuickScout monitor status no longer collapses every live mission into coarse generic survey state: the GCS now derives operator-facing phases such as `ready_to_launch`, `launch_partial`, `holding`, and `return_commanded`, and the live status payload carries compact summary/guidance text plus resolved control availability for UI, automation, and future MCP consumers
- QuickScout no longer advertises a fake direct resume path for paused coverage packages: `/api/sar/mission/{mission_id}/resume` now returns explicit `replan_required` guidance without mutating mission state, the monitor action bar prioritizes follow-up planning, and monitor mode surfaces the same doctrine to operators
- QuickScout per-drone monitor cards now carry compact runtime notes from launch/control/progress updates, so operators can tell “launch not accepted”, “holding on operator command”, “executing assigned search track”, and mission-end return behavior apart without decoding raw state transitions
- QuickScout planning and monitoring now expose mission end behavior explicitly instead of relying on an implicit backend default or implying fixed RTL semantics: plan requests now carry `return_behavior`, recovered missions restore it, and the monitor action bar reflects the configured end behavior
- QuickScout no longer depends on one browser-local `missionId` after refresh: the page can now reopen persisted workspaces, auto-recover active missions, restore saved plan geometry/config/drone selections, and surface a shared saved-mission panel in both planning and monitor contexts
- QuickScout now exposes durable mission-recovery surfaces instead of forcing the frontend to rely on one in-memory `missionId`: persisted missions can now be listed, a single workspace payload can reopen the stored mission package plus live-derived status, and the dashboard SAR service layer has matching recovery entrypoints for the later workspace redesign
- QuickScout no longer bypasses the shared tracked command lifecycle for launch, pause, and abort: launch now returns per-drone tracked command submissions, pause/abort now return typed tracked control responses, and durable mission recovery data now includes compact last-command summaries instead of ephemeral route-local success dicts
- QuickScout mission controls no longer default to all configured drones when no subset is provided; pause, resume, and abort now scope to mission participants by default, which removes a real cross-mission control hazard from the old PoC path
- QuickScout abort now respects the selected return behavior instead of always sending RTL, mapping `return_home` to `RETURN_RTL`, `land_current` to `LAND`, and `hold_position` to `HOLD`
- advanced SITL mixed-mode validation no longer fails because override missions clobber their own staged mission metadata: interrupting a running mission now preserves the replacement mission/state while the superseded process is terminated, so leader-only Swarm Trajectory overrides report `mission=4` correctly in fleet telemetry and the integrated operator drill stays observable end to end
- Mission Config now opens on a tighter assignment wall instead of a long top-heavy explainer stack: the header copy is shorter, issue/origin warnings are compact alert rows, filters live in one ops rail, the visible-card summary is terse, and the right-side launch-review panel can switch between the default engineering plot and a real map view without leaving the workspace
- Trajectory Planning and Swarm Trajectory now use their compact authoring-first behavior through tablet width as well as phone width, so route authoring no longer falls back to the verbose desktop layout on mid-sized operator screens
- Trajectory Planning no longer front-loads desktop route review above the working surface: the map/waypoint workspace stays first, review surfaces dock below it, and the route-policy brief is now one compact disclosure instead of a separate expanded desktop block
- Swarm Trajectory no longer repeats operator guidance in a standalone top banner: workspace doctrine/stage review is collapsed into the workspace summary and the related-tool handoff is now a compact reusable link row instead of another full-width explainer
- Command Control, mission-trigger cards, and Custom Show no longer carry as much tester-reported copy/token noise: target-scope guidance is shorter, mission notes are glanceable, and Custom Show now forces dashboard tokens for dark/light readability instead of inheriting weaker default MUI colors
- the Precision Move dialog now prioritizes the fast operator path: compact controller-style nudges, folded manual tuning, direct scope-edit return into the shared Command Control selector, visible live runtime defaults, and cleaner live command-state context without forking the main target-selection workflow
- GCS now exposes `/api/v1/commands/policy/precision-move`, a typed runtime policy envelope for default speed/tolerance/timeout/limit values so UI, automation, and future MCP surfaces can reuse the live backend contract instead of hardcoded frontend guesses
- the action system now supports a typed local-relative `PRECISION_MOVE` command end to end, from GCS submit validation to drone runtime payload staging, timeout budgeting, `DroneSetup` mission routing, and the offboard local-position executor that settles then returns control to PX4 Hold
- the dashboard Actions tab no longer has to force parameterized precision moves through the generic two-step confirm flow; the new dedicated Precision Move dialog is now the single operator confirmation surface and still submits through the standard command lifecycle tracker
- command submission normalization now explicitly preserves nested `precision_move` payloads while still converting the surrounding command envelope onto the canonical snake_case GCS API contract
- Docker SITL release packaging no longer requires a full intermediate `.tar` on disk when compression is enabled and `--keep-tar` is not requested; `tools/package_sitl_image.sh` now streams `docker save` directly into `7z`, which keeps the release workflow viable on smaller VPS hosts
- Hetzner promotion-style SITL validation is now documented against the mode that actually proved stable in practice: fresh rebuilt image, fresh fleet recreation, and boot-time repo/dependency sync disabled during the regression run
- the reusable SITL suite is no longer just a hardcoded mission wrapper: it now supports the standalone action-control drill, plan-hash/provenance capture, side-effect-free dry-run, final reset/failure cleanup behavior, and explicit deferred QuickScout tracking for future expansion
- Swarm Trajectory short-profile preparation no longer leaves shared raw leader CSVs mutated after a validation run; the validator now snapshots the original raw profiles, restores them in a finalization step, and records the restore result in the JSON summary
- Drone Show and Smart Swarm runtime validators no longer rely on success-only cleanup paths; both now emit structured fail results, attempt runtime cleanup, and still write final JSON summaries after failures
- `WS /ws/heartbeats` now emits the normalized heartbeat list contract documented in the GCS API instead of the older raw internal heartbeat map, and the old skipped GCS websocket suite was replaced with deterministic route-level contract coverage for telemetry, heartbeat, and git-status streams
- the GCS and drone websocket API docs now match the live transport contracts more closely: GCS examples reflect the real payload shapes, and drone docs no longer claim bidirectional command transport over `WS /ws/drone-state`
- the active Swarm Trajectory success surfaces now use typed GCS schema models and `response_model` contracts, so `/docs` and `/openapi.json` describe the real leaders/upload/recommendation/status/policy/process/clear/remove/commit payloads instead of leaving that domain as ad hoc dictionaries
- `POST /api/v1/swarm-trajectories/process` and `POST /api/v1/swarm-trajectories/commit` now use typed optional request models, which removes the last manual request parsing in that route family and standardizes schema/body failures onto the shared `422 Validation error` envelope
- Swarm Trajectory processing and clear-processed service failures now raise typed `SwarmTrajectoryError` instead of returning `200` with `success=false`, so transport success and operational success are no longer conflated on that domain boundary
- frontend API error extraction now handles structured validation/detail arrays, and the Swarm Trajectory frontend service now surfaces backend process/clear failures as readable operator errors instead of raw Axios status strings
- the remaining Swarm Trajectory route-family failures now use the shared GCS `ErrorResponse` envelope instead of route-local `success=false` payloads, so malformed JSON, missing processed assets, and operator-facing git/cluster errors now surface stable `error`, `detail`, `timestamp`, and `path` fields like the rest of the cleaned GCS HTTP surface
- Swarm Trajectory git commit/push failures now map to explicit operation statuses (`409` for divergence/conflict cases, `502` for network/auth/timeout upstream failures) instead of collapsing every failure into a generic `500` with a custom body
- QuickScout SAR and Swarm Trajectory router docs/OpenAPI metadata now advertise the shared error-response contract directly at the router boundary, instead of relying on app-level behavior while the subsystem routers looked undocumented in isolation
- canonical GCS FastAPI HTTP routes now use one shared machine-readable error envelope for request validation, `HTTPException`, and uncaught server failures, so clients receive stable `error`, `detail`, `timestamp`, and `path` fields instead of mixed default FastAPI payloads and raw exception strings
- the remaining high-value GCS mutation routes no longer hand-parse JSON bodies ad hoc: fleet config, GCS config stub writes, origin compute, swarm config save/patch, and Drone Show deployment now use typed request models with standard `422` validation behavior
- the canonical swarm-config resource now returns normalized saved assignment objects, including defaulted `offset_x`, `offset_y`, `offset_z`, and `frame` fields, instead of mixed sparse payload shapes between read and write paths
- command submission is now replay-safe at the GCS contract boundary: `POST /api/v1/commands` accepts canonical `idempotency_key`, returns `replayed=true` when the same normalized submission is retried, and rejects conflicting reuse of the same key with `409` instead of creating a second live tracked command
- command submit/status responses now surface `idempotency_key`, so future MCP/tooling layers can correlate transport retries with the long-running tracked command instead of relying on hidden client-side bookkeeping
- the drone API now treats the canonical `/api/v1/...` contract as the only current public business HTTP surface, adding `GET /api/v1/git/status` and `GET /api/v1/navigation/position-deviation` while retiring the legacy drone business aliases that previously stayed mounted beside the v1 routes
- first-party runtime/tooling callers now use the shared canonical drone route surface instead of repeating legacy strings such as `/get_drone_state`, `/get-home-pos`, `/get-git-status`, and `/api/live-armability`, so GCS polling, validators, mission runtimes, and local helpers no longer reinforce the retired contract
- `GET /api/v1/drone/state` and `WS /ws/drone-state` now share one validator-backed serializer, so the live drone state payload stays schema-aligned across HTTP and WebSocket transport instead of drifting by transport path
- duplicate GCS HTTP telemetry aliases `GET /telemetry` and `GET /api/telemetry` are now retired, leaving `GET /api/v1/fleet/telemetry` as the single current fleet-telemetry snapshot route
- the fake `POST /api/v1/commands/{command_id}/cancel` endpoint has been removed because it never dispatched a live cancel to drones; the only current cancellation contract remains `POST /api/v1/commands` with `missionType=0`
- reusable live validators, request-log classification, route inventory, and shared frontend/docs guidance now prove and describe the canonical `GET /api/v1/system/health` and `GET /api/v1/fleet/telemetry` routes instead of preserving removed telemetry aliases as pseudo-compatibility
- LAND / RTL timeout fallback estimation now reads the drone home-position `altitude` field instead of the nonexistent `alt`, preventing under-budgeted tracking windows when relative-altitude telemetry is unavailable
- the third Phase 5 API-modernization slice now treats `/ws/telemetry`, `/ws/heartbeats`, and `/ws/git-status` as intentional canonical transport roots instead of leaving them as undocumented versionless leftovers, closing the last open GCS route-shape policy gap after the Phase 4 HTTP retirement work
- shared GCS frontend route helpers now build WebSocket URLs from the configured backend base URL with correct `http`→`ws` and `https`→`wss` protocol mapping while preserving already-absolute WebSocket URLs, so future stream consumers do not reintroduce hardcoded or incorrectly prefixed socket endpoints
- the second Phase 5 API-modernization slice now hardens the shared logging session layer so session IDs must resolve inside the configured log directory, which closes the path-traversal risk for both GCS and drone-side `/api/logs/*` session access and export flows
- GCS log routes now use typed request/response models for frontend reports, export requests, config toggles, and session payloads instead of relying on untyped dictionaries, bringing the logging domain in line with the broader contract-cleanup standard without renaming the stable `/api/logs/*` namespace
- the API modernization policy now treats `/api/logs/*` and `/api/sar/*` as intentional stable subsystem roots rather than unfinished alias debt, so the remaining open contract question is concentrated on the GCS WebSocket stream surface instead of churn for already-namespaced domains
- the first Phase 5 API-modernization slice now normalizes the QuickScout SAR backend onto the same dependency-injected router-factory pattern as the rest of the cleaned GCS API, replacing the old module-global router and `sys.path` mutation in `gcs-server/sar/routes.py` without changing the live `/api/sar/*` contract
- QuickScout route handlers now read `load_config`, telemetry state, and command-dispatch dependencies from the live `app_fastapi` module object at request time, so tests and future auth/MCP wrapping no longer depend on import-time state capture inside the SAR route module
- the sixteenth Phase 4 API-modernization slice now retires the remaining versionless operational HTTP aliases `POST /heartbeat`, `POST /drone-heartbeat`, `GET /get-heartbeats`, `GET /get-network-status`, `GET /git-status`, and `POST /sync-repos`, leaving the canonical `/api/v1/fleet/heartbeats`, `/api/v1/fleet/network-status`, `/api/v1/git/status`, and `/api/v1/git/sync-operations` routes as the only supported GCS HTTP contract for those operational reads and mutations
- the default drone heartbeat sender path now comes from the shared canonical route constant `GCS_FLEET_HEARTBEATS_ROUTE` instead of the old `/drone-heartbeat` string, so runtime callbacks no longer keep a removed compatibility alias artificially alive
- the shared frontend route resolver, request-log classification, route inventory, and active git/heartbeat docs now treat the operational v1 routes as the single current HTTP surface instead of quietly preserving retired alias knowledge
- the fifteenth Phase 4 API-modernization slice now retires the versionless Swarm Trajectory routes `GET /api/swarm/leaders`, `POST /api/swarm/trajectory/upload/{leader_id}`, `POST /api/swarm/trajectory/process`, `GET /api/swarm/trajectory/recommendation`, `GET /api/swarm/trajectory/status`, `GET /api/swarm/trajectory/policy`, `POST /api/swarm/trajectory/clear-processed`, `POST /api/swarm/trajectory/clear`, `POST /api/swarm/trajectory/clear-leader/{leader_id}`, `DELETE /api/swarm/trajectory/remove/{leader_id}`, `GET /api/swarm/trajectory/download/{drone_id}`, `GET /api/swarm/trajectory/download-kml/{drone_id}`, `GET /api/swarm/trajectory/download-cluster-kml/{leader_id}`, `POST /api/swarm/trajectory/clear-drone/{drone_id}`, and `POST /api/swarm/trajectory/commit` because the dashboard, tooling, and validation clients now use the canonical `/api/v1/swarm-trajectories/*` surface
- the shared frontend GCS route resolver, Swarm Trajectory runtime validator, route inventory, and API docs now treat `/api/v1/swarm-trajectories/*` as the single current contract, so the retired versionless routes cannot linger as pseudo-compatibility
- removed an unused block of stale trajectory schema models that still advertised non-existent legacy endpoints, keeping schema metadata aligned with the live contract instead of preserving dead API shapes
- the fourteenth Phase 4 API-modernization slice now retires the public origin legacy routes `GET /get-origin`, `POST /set-origin`, `GET /get-gps-global-origin`, `GET /elevation`, `GET /get-origin-for-drone`, `GET /get-position-deviations`, `POST /compute-origin`, and `GET /get-desired-launch-positions` because they have no remaining live dashboard, runtime-tooling, or SITL-helper callers
- the shared frontend GCS route resolver and GCS request-log classification now treat the canonical origin surface as the single source of truth, so removed backend origin routes cannot linger in UI helpers or operational logging heuristics
- the active operator/developer docs, origin router coverage, HTTP regressions, and route inventory now reflect the canonical origin surface only instead of continuing to advertise or assert the retired aliases as current behavior
- the thirteenth Phase 4 API-modernization slice now retires the public command-control legacy routes `POST /submit_command`, `GET /command/{command_id}`, `GET /commands/recent`, `GET /commands/active`, `GET /commands/statistics`, `POST /command/{command_id}/cancel`, `POST /command/execution-start`, and `POST /command/execution-result` because they have no remaining live dashboard, runtime-tooling, or SITL-helper callers
- the shared frontend GCS route resolver and GCS request-log classification no longer keep the retired command aliases alive as pseudo-compatibility, so removed backend routes cannot linger in UI helpers or operational logging heuristics
- the public GCS API docs, command router coverage, route inventory, and HTTP regression batches now reflect the canonical command-control surface only, instead of continuing to advertise or assert the retired aliases as current behavior
- the tenth Phase 4 API-modernization slice now retires the public management/static legacy routes `GET /get-gcs-config`, `POST /save-gcs-config`, `GET /get-network-info`, and `GET /static/plots/{filename}` because they have no remaining live dashboard, runtime-tooling, or validation-script callers
- the shared frontend GCS route resolver no longer recognizes the retired management/static legacy paths, so removed backend routes cannot survive as frontend pseudo-compatibility
- the public GCS API docs now describe only the canonical management/static surface for GCS config, detailed fleet network metadata, and Swarm Trajectory plots instead of presenting removed aliases as current endpoints
- the ninth Phase 4 API-modernization slice now retires the deprecated one-off git detail routes `GET /get-gcs-git-status` and `GET /get-drone-git-status/{drone_id}` because they have no remaining live callers and the canonical `GET /api/v1/git/status` surface already carries the same data
- git route inventory, router coverage, HTTP regressions, and the public git documentation now reflect the retired route set instead of preserving those deprecated endpoints as misleading permanent compatibility debt
- the eighth Phase 4 GCS route-migration slice now introduces canonical management/static routes: `GET /api/v1/system/gcs-config`, `PUT /api/v1/system/gcs-config`, `GET /api/v1/fleet/network-details`, and `GET /api/v1/swarm-trajectories/plots/{filename}`
- the shared frontend GCS service layer now uses the canonical management/static routes for GCS configuration reads/writes, detailed fleet network metadata, and Swarm Trajectory plot URLs instead of reinforcing `/get-gcs-config`, `/save-gcs-config`, `/get-network-info`, and `/static/plots/{filename}`
- the canonical GCS-config write path is now modeled truthfully as `PUT /api/v1/system/gcs-config` while the legacy `POST /save-gcs-config` alias remains mounted during rollout, preventing the canonical resource contract from inheriting the older action-style route shape
- route inventory, router coverage, HTTP regressions, and shared dashboard GCS service tests now cover the canonical management/static surface, and the dead frontend git-status helper exports were removed instead of being preserved as misleading compatibility debris
- the sixth Phase 4 GCS route-migration slice now introduces canonical show-management routes for both live show workflows: `POST /api/v1/shows/skybrush/import`, `GET /api/v1/shows/skybrush`, `GET /api/v1/shows/skybrush/archives/raw`, `GET /api/v1/shows/skybrush/archives/processed`, `GET /api/v1/shows/skybrush/metrics`, `GET /api/v1/shows/skybrush/safety-report`, `GET /api/v1/shows/skybrush/validation`, `POST /api/v1/shows/skybrush/deployments`, `GET /api/v1/shows/skybrush/plots`, `GET /api/v1/shows/skybrush/plots/{filename}`, `GET /api/v1/shows/custom`, `POST /api/v1/shows/custom/import`, and `GET /api/v1/shows/custom/preview`
- the shared frontend GCS service layer now uses the canonical show-management routes for show metadata, custom-show metadata, SkyBrush/custom imports, processed/raw downloads, plot discovery, and custom preview assets instead of reinforcing the legacy compatibility paths
- canonical show-management naming now reflects the two real operator workflows explicitly: standard SkyBrush processing lives under `/api/v1/shows/skybrush/*`, the specialist shared-CSV flow lives under `/api/v1/shows/custom/*`, and the read-only validation snapshot is modeled as `GET /api/v1/shows/skybrush/validation` even though the legacy compatibility route remains `POST /validate-trajectory`
- show route inventory, router coverage, HTTP regressions, and shared dashboard GCS service tests now cover the canonical show-management surface so later cleanup cannot silently drift from the mounted routes or active callers
- the public GCS API docs and Drone Show feature guide now present the canonical show-management surface first while keeping the legacy compatibility routes explicit during rollout
- the seventh Phase 4 API-modernization slice now moves the remaining real internal GCS callers in drone runtime/tooling onto canonical routes instead of the compatibility aliases
- drone-side execution callbacks now post to `POST /api/v1/command-reports/execution-start` and `POST /api/v1/command-reports/execution-result`, including the direct fallback path used when a queued command is superseded before runtime launch
- drone-side bootstrap-origin fetches now use `GET /api/v1/origin/bootstrap`, and the Drone Show validation tooling plus the standalone import test page now use the canonical SkyBrush/custom show routes
- `src/gcs_api_routes.py` now provides one shared route constant surface for the drone runtime and validation tooling, preventing the same canonical GCS paths from drifting into new hardcoded copies
- drone-side regression coverage now explicitly checks the canonical superseded-command callback path and canonical bootstrap-origin fetch, and the updated drone-side batch passes locally and on Hetzner with `105` tests
- the fifth Phase 4 GCS route-migration slice now introduces canonical git routes: `GET /api/v1/git/status` and `POST /api/v1/git/sync-operations`
- the shared frontend GCS service layer and the remaining active hardcoded dashboard git-status poll now use the canonical git routes instead of reinforcing `/git-status` directly
- canonical git-sync naming now reflects the real contract: the API performs dispatch plus convergence verification synchronously, so the canonical path is `sync-operations` instead of the earlier provisional `sync-jobs` wording
- successful canonical git-status polls are now classified as routine `DEBUG` request noise the same way legacy `/git-status` polls were, preventing log-volume regressions during caller migration
- route inventory, HTTP regressions, router coverage, and dashboard service tests now cover the canonical git surface so later cleanup cannot silently drift from the mounted routes
- the fourth Phase 4 GCS route-migration slice now introduces canonical origin routes: `GET /api/v1/origin`, `PUT /api/v1/origin`, `GET /api/v1/origin/bootstrap`, `GET /api/v1/navigation/global-origin`, `GET /api/v1/origin/elevation`, `GET /api/v1/origin/deviations`, `POST /api/v1/origin/compute`, and `GET /api/v1/origin/launch-positions`
- the shared frontend GCS service layer and the Drone Show runtime/validation tooling touched in this slice now use the canonical origin paths instead of reinforcing the older compatibility URLs
- the canonical origin write contract no longer falsely requires altitude when the dashboard treats it as optional; `PUT /api/v1/origin` now defaults omitted altitude to `0.0` MSL and preserves the explicit `source` field in the typed origin response
- origin bootstrap consumers now have a distinct canonical route at `GET /api/v1/origin/bootstrap` instead of relying on an implicit mis-mapping to the generic origin-read resource, which keeps the v1 surface semantically explicit for future MCP/automation use
- origin route inventory, HTTP regressions, router coverage, dashboard-service tests, and the Drone Show validation helper all now cover the canonical origin surface, preventing silent drift between the migration blueprint and live callers
- the third Phase 4 GCS route-migration slice now introduces canonical swarm-config routes: `GET /api/v1/config/swarm`, `PUT /api/v1/config/swarm`, and `PATCH /api/v1/config/swarm/assignments/{hw_id}`
- the canonical swarm-config `GET` route now returns the persisted typed resource shape `{version, assignments}` instead of the older raw-list compatibility payload, while the legacy `/get-swarm-data` route remains available during rollout
- the shared frontend GCS service layer now uses the canonical swarm-config resource path, saves swarm assignments through `PUT /api/v1/config/swarm`, and unwraps canonical swarm envelopes centrally so `Overview`, `Mission Config`, and `Swarm Design` stay aligned on one config contract
- the misleading leader-only reassignment contract now has a canonical partial-update route at `PATCH /api/v1/config/swarm/assignments/{hw_id}`, matching the live behavior that can update `follow`, offsets, and frame together instead of pretending the route only changes leaders
- Smart Swarm runtime refresh/failover reporting, swarm analysis fallback, and the reusable validation scripts now call the canonical swarm-config routes; the reusable validation clients touched in this slice also use the canonical command submit/status paths so internal tooling stops reinforcing stale GCS URLs
- swarm route inventory and HTTP regression guardrails now cover the canonical swarm-config surface in addition to the legacy compatibility routes, including the enveloped canonical read contract and the partial assignment patch behavior
- the second Phase 4 GCS route-migration slice now introduces canonical fleet-config aliases: `GET /api/v1/config/fleet`, `PUT /api/v1/config/fleet`, `POST /api/v1/config/fleet/validation`, `GET /api/v1/config/fleet/trajectory-start-positions`, and `GET /api/v1/config/fleet/trajectory-start-positions/{pos_id}`
- the shared frontend GCS service layer now uses the canonical fleet-config resource paths, including `PUT /api/v1/config/fleet` for save and the path-parameter form for per-slot trajectory-start lookups
- the canonical per-position trajectory-start route now returns `x`/`y` to match the existing fleet trajectory-position collection, while the legacy `/get-trajectory-first-row?pos_id=...` path keeps its older `north`/`east` compatibility payload
- Mission Config trajectory-position hydration now accepts canonical `x`/`y` and legacy `north`/`east`, so the frontend can move to the cleaned config contract without breaking compatibility during rollout
- configuration route inventory and alias guardrails now cover the canonical fleet-config surface in addition to the legacy compatibility paths, preventing silent drift between the mounted FastAPI routes and the migration blueprint
- the first Phase 4 GCS route-migration slice now introduces canonical v1 command aliases: `POST /api/v1/commands`, `GET /api/v1/commands/{command_id}`, `GET /api/v1/commands/recent`, `GET /api/v1/commands/active`, `GET /api/v1/commands/statistics`, `POST /api/v1/commands/{command_id}/cancel`, `POST /api/v1/command-reports/execution-start`, and `POST /api/v1/command-reports/execution-result`
- the shared frontend GCS service layer now uses the canonical v1 command endpoints for submit/status/recent/active command flows instead of the legacy compatibility paths, so the operator UI and future MCP-facing consumers move onto one current command contract
- command-route inventory and alias guardrails now cover the canonical v1 command surface in addition to the legacy compatibility paths, preventing later drift between documented aliases and the mounted FastAPI routes
- request-log noise classification now recognizes canonical command poll/callback paths (`/api/v1/commands/...`, `/api/v1/command-reports/...`) so successful v1 command monitoring traffic stays at `DEBUG` while submit/cancel/operator actions remain visible at `INFO`
- the public GCS API documentation now presents the command control surface under canonical v1 routes first while still calling out the legacy compatibility paths explicitly
- `tools/run_sitl_validation_suite.py` now separates `--validator-root` from `--repo-root`, so temporary validation checkouts can execute the newest tooling while all reset steps and repo-backed runtime data operations target the same checkout that the live GCS actually serves from
- the reusable SITL validation workflow is now validated locally and on Hetzner with `371 passed, 8 skipped`, and the corrected live 3-drone suite passed end to end with the runtime-root-aware invocation
- the eighth Phase 3 backend extraction now moves the remaining Commands REST surface into `gcs-server/api_routes/commands.py`, so `app_fastapi.py` no longer owns `/submit_command`, `/command/{command_id}`, `/commands/recent`, `/commands/active`, `/commands/statistics`, `/command/{command_id}/cancel`, `/command/execution-result`, or `/command/execution-start`
- command-route coverage now has focused router-level tests for route registration, live dependency lookup, request-body validation, target-resolution failure handling, and the intentionally fail-closed cancel path, closing the last major gap in the extracted GCS route suite
- `POST /submit_command` now rejects malformed JSON, non-object JSON bodies, invalid `target_drones` shapes, and explicit target selections that match no configured drones with `400` instead of creating ambiguous zero-target command records or surfacing generic server errors
- command-only target-telemetry and altitude-budget helpers now live with the extracted command router instead of remaining as private file-local logic inside `app_fastapi.py`
- `SubmitCommandRequest` / `SubmitCommandResponse` schema metadata and the human-facing GCS API doc now align with the live command contract, including `target_drones`, the normalized hardware-ID response behavior, and the legacy-but-ignored ack fields
- `gcs-server/app_fastapi.py` no longer contains business `@app.get(...)`, `@app.post(...)`, or other business route decorators; it is now reduced to infrastructure, dependency state, router mounting, and shared compatibility seams on the GCS side
- the seventh Phase 3 backend extraction now moves the full Swarm Trajectory route surface into `gcs-server/api_routes/swarm_trajectory.py`, so `app_fastapi.py` no longer owns `/api/swarm/leaders`, `/api/swarm/trajectory/upload/{leader_id}`, `/api/swarm/trajectory/process`, `/api/swarm/trajectory/recommendation`, `/api/swarm/trajectory/status`, `/api/swarm/trajectory/policy`, `/api/swarm/trajectory/clear-processed`, `/api/swarm/trajectory/clear`, `/api/swarm/trajectory/clear-leader/{leader_id}`, `/api/swarm/trajectory/remove/{leader_id}`, `/api/swarm/trajectory/download/{drone_id}`, `/api/swarm/trajectory/download-kml/{drone_id}`, `/api/swarm/trajectory/download-cluster-kml/{leader_id}`, `/api/swarm/trajectory/clear-drone/{drone_id}`, or `/api/swarm/trajectory/commit`
- Swarm Trajectory route coverage now has focused router-level tests for route registration, live dependency lookup, runtime policy reads, and request-body validation, closing the gap where only route existence and the policy endpoint were asserted directly
- `POST /api/swarm/trajectory/process` and `POST /api/swarm/trajectory/commit` now reject malformed JSON and non-object JSON bodies with `400` instead of falling through to a generic `500`
- the stale unused Flask-era duplicate `gcs-server/swarm_trajectory_routes.py` has been removed, leaving the extracted FastAPI router as the single current Swarm Trajectory route definition in the repo
- the sixth Phase 3 backend extraction now moves the remaining Drone Show / Custom Show routes into `gcs-server/api_routes/show_management.py`, so `app_fastapi.py` no longer owns `/import-show`, `/download-raw-show`, `/download-processed-show`, `/get-show-info`, `/get-custom-show-info`, `/import-custom-show`, `/get-comprehensive-metrics`, `/get-safety-report`, `/validate-trajectory`, `/deploy-show`, `/get-show-plots`, `/get-show-plots/{filename}`, or `/get-custom-show-image`
- shared Drone Show / Custom Show helper logic now lives in `gcs-server/show_management.py`, while `app_fastapi.py` keeps compatibility wrappers for the patch-driven test seam instead of duplicating domain logic inline
- `POST /deploy-show` now accepts standard JSON content types with charset parameters instead of only an exact `application/json` header match
- show trajectory validation now preserves `FAIL` when safety blockers exist, instead of accidentally downgrading that result back to `WARNING` when collision or speed warnings are also present
- `GET /get-show-plots/{filename}` now resolves files through a bounded path check, closing the traversal risk in the legacy show-plot download surface
- `GET /get-show-plots` now returns an empty result for a missing plots directory instead of creating directories as a side effect of a read request
- the GCS API server docs now include the active custom-show endpoints and the expanded show-import response payload, removing the show-domain doc drift that had built up around the extracted routes
- the fifth Phase 3 backend extraction now moves `/get-gcs-config`, `/save-gcs-config`, `/get-network-info`, and `/static/plots/{filename}` into `gcs-server/api_routes/management.py` and `gcs-server/api_routes/static_assets.py`, so `app_fastapi.py` no longer owns that compatibility cluster
- `POST /save-gcs-config` now returns an explicit compatibility stub result with `success=true`, `persisted=false`, and warnings instead of the old ambiguous payload that looked like a real save even though no persistence path exists
- static plot serving now resolves paths through a bounded project-root check before returning files, closing the traversal risk that existed when arbitrary filenames were joined directly under the plots directory
- `MissionReadinessCard` now builds static-plot URLs through the shared GCS route helper instead of hardcoding `/static/plots/...`, keeping frontend route composition aligned with the centralized API contract
- the project `dev` extra now includes `pytest-timeout`, which fixes the mismatch where `pytest.ini` required timeout options but a clean validation environment did not install the plugin
- removed the redundant ignored `[tool.pytest.ini_options]` block from `pyproject.toml`, leaving `pytest.ini` as the single source of truth for pytest behavior
- the fourth Phase 3 backend extraction now moves the full Origin domain into `gcs-server/api_routes/origin.py`, so `app_fastapi.py` no longer owns `/get-origin`, `/set-origin`, `/get-gps-global-origin`, `/elevation`, `/get-origin-for-drone`, `/get-position-deviations`, `/compute-origin`, or `/get-desired-launch-positions`
- origin geometry/reporting helpers now live in `gcs-server/origin.py` instead of being duplicated inside route handlers, including the richer deviation report and desired-launch-position export payload used by the extracted router
- `POST /compute-origin` now behaves like the frontend/operator workflow already expects: it computes and returns a candidate origin without silently overwriting shared origin state; `POST /set-origin` remains the only explicit write path for origin persistence
- `compute_origin_from_drone(...)` now imports the `pyproj` primitives it already depends on, fixing a latent runtime failure path that could raise `NameError` when the origin-compute flow was exercised outside mocks
- `GET /get-desired-launch-positions` now actually honors its documented `heading` and `format` parameters: heading rotates formation offsets before GPS projection, `format=csv` returns a CSV attachment, and `format=kml` returns a KML attachment instead of those parameters being silently ignored
- command submission now preserves valid `auto_global_origin` coordinates at latitude/longitude `0.0`, replacing the old truthiness check that incorrectly treated equator/prime-meridian origins as missing
- route inventory coverage now includes a duplicate method/path guard for the GCS API so future route extractions cannot accidentally double-register a public surface without failing tests
- the third Phase 3 backend extraction now moves the Git routes into `gcs-server/api_routes/git_status.py`, so `app_fastapi.py` no longer owns `/git-status`, `/sync-repos`, `/ws/git-status`, `/get-gcs-git-status`, or `/get-drone-git-status/{drone_id}`
- Git route coverage now has focused router-level tests for route registration, live dependency lookup, and sync verification hook usage, closing the gap where Git extraction risk was previously covered only by the broader integration suite
- the extracted Git websocket now builds its payload from the same shared response builder used by the REST endpoint, keeping the live contract aligned between `/git-status` and `/ws/git-status`
- the second Phase 3 backend extraction now moves the configuration routes into `gcs-server/api_routes/configuration.py` and swarm configuration / Smart Swarm reassignment routes into `gcs-server/api_routes/swarm.py`, so `app_fastapi.py` no longer owns `/get-config-data`, `/save-config-data`, `/validate-config`, `/get-drone-positions`, `/get-trajectory-first-row`, `/get-swarm-data`, `/save-swarm-data`, or `/request-new-leader`
- configuration helper routes now have focused router-level coverage for route registration, live dependency lookup, invalid client payload preservation, and helper-path behavior, which closes the previous gap where only the broader API suite covered the domain partially
- invalid configuration payload shape now preserves `400` instead of being flattened into a generic `500`, while leaving the existing malformed raw JSON behavior unchanged for this slice
- both extracted mutable router domains now use `asyncio.get_running_loop()` for async git side-effect paths, aligning them with current async-loop practice
- swarm cycle validation now lives with the swarm router instead of as file-local helpers in `app_fastapi.py`, so the swarm domain keeps one cohesive validation surface instead of reaching back into the monolith for follow-chain rules
- the first Phase 3 backend extraction now moves GCS health, telemetry, heartbeat, and network-status routes into `gcs-server/api_routes/core.py` and mounts them through `create_core_router(...)`, reducing `app_fastapi.py` surface area without changing the live HTTP/WebSocket contract
- the extracted core router reads dependency attributes from the live `app_fastapi` module object at request time instead of capturing handler references at import time, so existing patch-driven backend tests and future auth/MCP layers keep one stable hook surface during modularization
- `GET /get-network-info` now returns the live heartbeat-derived network snapshot directly after the core route extraction, removing its stale dependency on the deleted private helper and keeping the legacy compatibility alias working
- the remaining active Drone Show, Swarm Trajectory, QuickScout, mission-detail, log, and SAR frontend consumers now use the shared GCS route/service layer instead of page-owned backend URLs, so uploads, downloads, static plot URLs, telemetry/config reads, and route-key polling all flow through one contract surface
- added a shared `apiError` helper and moved upload/import flows onto it, so blob-backed and JSON-backed API failures now resolve through one consistent operator-facing error path instead of each page re-parsing responses differently
- `buildGcsUrl()` now preserves absolute URLs instead of prefixing them twice, fixing a real service-layer bug exposed by the Swarm Trajectory migration where helper-built absolute URLs could otherwise become invalid request targets
- removed the dead unrouted `ImportShow` / `FileUpload` frontend path and its stale CSS instead of carrying it forward as misleading compatibility baggage; the live Drone Show workflow is now exclusively `ManageDroneShow` plus its import/visualization/export sections
- Hetzner frontend validation now includes dedicated `logService` and `sarApiService` regression coverage plus the updated `SwarmTrajectory` page/service mocks, closing the remaining route-centralization gaps in the focused API contract suite
- the dashboard build script now disables production sourcemaps and sets an explicit Node heap budget, so `npm run build` completes reliably on the Hetzner Node 22 runtime instead of failing with V8 heap exhaustion and third-party sourcemap noise
- the API modernization phase 2 slice now centralizes the highest-traffic frontend GCS callers behind `src/services/gcsApiService.js`, so Dashboard Overview, Mission Config, Swarm Design, Globe View, Drone Detail, git/sync widgets, origin helpers, mission-config save/validate flows, and command-service reads no longer hardcode backend route strings across pages and hooks
- added focused dashboard service coverage for the new route layer (`gcsApiService.test.js`) and the migrated command/swarm helpers (`droneApiService.test.js`), giving the API cleanup stream an explicit frontend contract gate instead of relying only on end-to-end browser checks
- `getSwarmClusterStatus()` now tolerates both raw axios responses and already-unwrapped status payloads, fixing a mixed response-shape bug that could hide processed-cluster state depending on which helper path supplied the data
- the first API modernization slice now exposes canonical `/api/v1/...` aliases for core GCS health/telemetry/heartbeat/network routes and core drone health/state/command/preflight/navigation/network routes while preserving legacy compatibility paths, giving docs/tests/automation a stable migration target before deeper route extraction and caller migration
- added machine-enforced route inventory coverage for the full current GCS and drone business API surfaces, including the active HTTP/WebSocket sets, heartbeat/health aliases, and deprecated git compatibility endpoints, so the API cleanup program can proceed against a frozen baseline instead of rediscovering the live contract by hand
- cluster-scope rails now render drone counts as discrete badges instead of parenthetical suffixes, keeping Dashboard, Mission Config, Swarm Design, and Command Control scope chips denser and easier to scan on mobile
- Mission Config show-slot status now collapses verbose config/heartbeat/auto prose into one compact verified/pending/review state with short source chips, explicit mismatch accept actions, and simulator-aware wording instead of noisy repeated slot sentences
- Swarm Design follow-chain guidance now states the graph direction explicitly as leader to follower, so operators do not misread the topology while reviewing cluster propagation
- the official SITL download guide now points to the refreshed MEGA release archive built from `main-candidate` commit `4cfbae9`, so docs, published image tags, and the packaged artifact no longer drift
- mobile theme application now updates the document root, body, `theme-color`, and `color-scheme` together, so Auto/Light mode reads more consistently on handheld browsers instead of inheriting a stale dark-biased frame state
- Mission Config and Drone Detail light-theme surfaces now use brighter, token-driven shadows and status chips, remove several dark-only hardcoded accents, and tighten the top identity summary cards for handheld audits
- dashboard theme selection now bootstraps before React mounts, so mobile Auto/Light mode applies on first paint instead of flashing the wrong palette
- dashboard webfont loading now matches the design system (`IBM Plex Sans` / `IBM Plex Mono`) instead of falling back to older mismatched type choices
- compact operator identity now standardizes on `Pn|Hm` for dense control surfaces where slot and hardware truth both matter, and that format now feeds cluster-scope labels, swarm follow-option labels, plot hover text, and dashboard search terms/tooltips instead of mixing longer ad hoc variants
- Drone Actions command buttons now keep icon and label alignment consistent even for shorter labels like `Hold`, so the action grid reads as one clean operator control matrix instead of a set of uneven cards
- Mission Config assignment cards now use tighter token-driven surfaces, less hard-coded accent styling, and denser identity/info/network layouts, reducing contrast drift and card clutter during the mobile operator audit
- Dashboard Overview now reuses the same cluster-scope rail as Mission Config and Swarm Design, so large fleets can be narrowed by detected top-leader cluster without changing command scope
- Command Control, mission cards, and action cards now use shorter operator-facing labels and less repeated copy while keeping the full command meaning in tooltips, confirmations, and detailed mission briefs
- Drone Actions, Drone Detail, Mission Config, and Smart Swarm light-theme surfaces now align more closely with the primary shell, reducing contrast drift between dashboard sections during mobile review
- dashboard theme auto mode now resolves against both dark/light media queries, falls back safely to dark when a mobile browser does not expose a clear preference, and advertises `color-scheme` in the document head so handheld browsers apply the operator palette more consistently
- light mode now uses a materially brighter canvas, sidebar, and body gradient instead of a slightly softened dark shell, so explicit `Light` selection reads like a real daylight operator theme on phones and tablets
- action override and mission selection cards now carry less always-visible copy: action buttons show the command label cleanly without stacked micro-descriptions, mission cards rely on shorter summaries plus native tooltips, and operator detail stays in the mission brief / confirmation flow instead of repeating on every card
- Mission Config now uses the same operator search grammar as Dashboard (`pos 1-5`, `hw 2,4`, free text, callsign) and adds a reusable cluster-scope rail driven by saved swarm topology, so assignment audits can be narrowed to one top-leader cluster or `Needs review` without changing the saved mission data
- Swarm Design now reuses the same cluster-scope rail and structured search grammar as Mission Config / Dashboard, so large topology audits can pivot between `All drones`, one top-leader cluster, and `Needs review` while preserving the existing grouped cluster layout
- the dashboard overview/command shell now switches to the overlay sidebar earlier on tablets, stacks summary/command sections cleanly on phone widths, and keeps drone-card density usable instead of leaving the dashboard in a cropped desktop layout on handheld screens
- dashboard theme control is now explicit instead of a confusing cycle-only control: expanded sidebar state shows a real light/dark/auto selector with the effective mode label, and operator-facing light/dark contrast is stronger across the dashboard shell, git info, command monitor, and mission readiness surfaces
- the dashboard responsive shell now audits cleanly on live Hetzner mobile captures: the sidebar/nav overlay uses the mobile viewport state correctly, the content column no longer keeps the stale desktop gutter, and overview/command-control cards no longer overflow or clip on a 390px phone viewport
- Trajectory Planning mobile authoring now uses a denser 2-column mission brief, a horizontally compact toolbar ribbon, and a mobile-first block order that pulls live authoring controls ahead of the longer review/policy sections while preserving the richer desktop layout in both light and dark themes
- QuickScout mobile layout groundwork now stacks the top bar/search and the map-plus-sidebar flow vertically instead of forcing the desktop split-pane into a phone viewport, but final operator acceptance of QuickScout remains explicitly deferred to the next UI audit slice
- Drone Show runtime validation now rebuilds and retries its safe GET polling after transient transport resets, recreates the selected SITL fleet between internal mode runs, waits on the same live per-drone launch-readiness probe that the backend enforces before dispatch, and only retries the specific transient launch-probe `HTTP 400` path after rechecking readiness, so long multi-mode validation no longer flakes out on stale transport, bad landed geometry, or short re-stage timing races
- Smart Swarm runtime validation now restores the selected saved swarm assignments after the in-flight reassignment drill, so acceptance runs no longer leave the SITL follow chain mutated for later sessions; the Smart Swarm guide now also states explicitly that cross-mode Drone Show / Swarm Trajectory validation still requires a launch-geometry reset because those modes can end with aircraft landed away from the show pads
- Drone Show runtime validation now re-checks selected-drone launch geometry immediately before each show/custom-show dispatch, so mixed-mode SITL drills fail fast when the fleet is idle but displaced off the show staging slots instead of attempting a bad launch
- shared command tracking now sizes standalone `LAND` and `RETURN_RTL` timeouts from live target altitude when that telemetry/home-position truth is available, so high-altitude recoveries no longer flip to terminal timeout while the fleet is still descending normally
- Drone Show runtime validation now treats `/get-position-deviations` as selected-fleet truth instead of full-config truth, so 3-drone acceptance runs no longer abort just because unlaunched config slots are intentionally offline while still failing selected drones that have launch-blocking geometry errors
- command terminal states are now immutable once they reach `phase=terminal`; late ACK/execution callbacks are captured under `late_reports` for diagnostics instead of reviving timed-out/cancelled/failed commands into a newer status
- Command Control now rehydrates its live/recent command monitor from `/commands/active` and `/commands/recent` on mount, so a dashboard refresh or route change does not silently drop in-flight command context that the backend is still tracking
- shared command monitoring now keeps `/commands/active` refreshed after hydration, backfills terminal transitions from `/commands/recent`, uses backend timestamps instead of raw browser wall-clock time for initial scheduled-state snapshots, and treats `HOVER_TEST` as the same strict synchronized offboard doctrine already enforced by the backend, so reloads / second-operator sessions / clock-skewed browsers no longer show stale command progress or the wrong late-start expectations
- frontend command activity now uses one shared store across `Command Control`, per-drone airborne overrides, and `Smart Swarm Runtime`, so those surfaces feed the same backend-backed command monitor instead of each command path behaving like an isolated toast-only flow
- Swarm Trajectory planner now recomputes `Speed-driven ETA` waypoint arrival times from the operator-owned preferred leg speeds whenever upstream geometry or altitude changes, so drag moves, terrain-backed altitude edits, imports, and panel edits no longer leave stale derived ETAs behind
- Swarm Trajectory planner now keeps save/import state honest: external CSV/JSON imports load into the planner as drafts instead of silently overwriting a saved route with the same name, imported terrain-backed waypoints re-resolve their ground context before use, and the toolbar distinguishes `Unsaved draft`, `Draft auto-saved`, and clean saved state instead of collapsing them into one misleading status
- Swarm Trajectory processing now resolves followers through their direct parent chain instead of flattening every nested follower to the top leader, and swarm follow-graph validation now fails fast on circular or missing parent chains instead of quietly producing misleading partial outputs
- Swarm Trajectory command tracking now resolves mission enums robustly across mixed import paths and budgets timeout from the actual selected processed trajectories, so subset launches no longer fall back to the generic 60s tracker timeout or time out just because unrelated drones have longer routes in the same processed package
- Mission Trigger, Mission Details, and Drone Actions now reuse one shared schedule/execution policy layer, so strict synchronized missions and standalone scheduled actions explain the same late-trigger / late-start behavior everywhere instead of drifting between pages and confirmation dialogs
- standalone `TAKEOFF` now reuses the shared bounded PX4 armability gate after its GPS/home preflight checks, aligning operator expectations with Drone Show and Swarm Trajectory startup behavior instead of relying on a one-shot arm attempt
- command/status docs now explicitly distinguish strict synchronized choreography retries from standalone action retry behavior, so delayed or missed trigger semantics stay consistent for operators and integrators
- Swarm Trajectory planner speed validation now uses the same `20.0 m/s` redesign ceiling as the current runtime policy, so preferred-speed input clamping, impossible-speed flags, and operator envelope wording no longer disagree about whether `20-30 m/s` routes are still acceptable
- mission scheduling surfaces now state the strict synchronized-launch doctrine in-page for Drone Show, Custom CSV, and Swarm Trajectory, so operators see the safe queue window / late-start-abort contract before dispatch instead of discovering it only from backend behavior
- Command Control now preserves recent command snapshots instead of replacing the previous live monitor every time a newer command arrives, so operators can cross-check multi-step dispatches without losing the earlier command's lifecycle context
- overview and expanded drone cards now treat `mission` as the live/current mission and keep `last_mission` as secondary history context, so operators no longer see a stale historical mission under a label that implies current execution truth
- Swarm Trajectory waypoint editing now treats derived fields consistently across the modal and side panel: AGL-authored stored MSL altitude, speed-derived arrival time, and auto-arrival heading stay read-only with inline operator guidance, while only the real operator-owned inputs remain directly editable
- synchronized Drone Show / Custom CSV / Swarm Trajectory dispatch now stops retrying once the safe queue window before trigger-minus-warmup has passed, and the offboard runtimes abort if they miss the requested start time beyond a configurable tolerance instead of starting late and pretending the mission stayed synchronized
- command tracking now treats execution-start and execution-result callbacks as authoritative acceptance evidence, so a dropped GCS->drone HTTP ACK no longer leaves a command stuck as offline/unknown after the drone actually executed it
- Command Control now keeps a persistent live command monitor fed by the normalized backend lifecycle stages, so operators can see acknowledgment/acceptance/execution state beyond transient toasts and can dispatch `Cancel Mission` back to the same targets before trigger time or during execution from the same surface
- drone-side execution-start and execution-result callbacks now retry through a bounded in-memory queue with backoff and per-command coalescing when GCS is temporarily unreachable, so brief network loss no longer forces command tracking to time out just because one callback POST was dropped
- same-host Swarm Trajectory SITL processing/review now resolves the configured shared trajectory workspace as the backend source of truth too, so reprocessing, status, plots, and mission execution stay aligned even when GCS code is running from a different repo checkout or validation worktree
- command submission now returns the backend-selected `tracking_timeout_ms`, lifecycle toasts reuse that mission-aware timeout instead of a flat 120s frontend guess, and scheduled commands include the future trigger delay in that same timeout budget, so long Drone Show / Swarm Trajectory / RTL flows no longer degrade into false "final status unknown" warnings while the backend is still tracking them correctly
- shared command submission/tracking now uses mission-aware timeout budgets plus active background timeout promotion, so TAKE_OFF / LAND / RTL / Drone Show / Custom CSV / Swarm Trajectory / QuickScout commands no longer share one flat tracker timeout or stay stuck forever when execution reporting disappears
- scheduled shared commands now include the future trigger delay in their backend/frontend lifecycle timeout budget, so delayed takeoff/show/swarm launches do not age out before the trigger time arrives
- drone-side command handling now treats duplicate delivery of the same active `command_id` as an idempotent ACK, installs overrides transactionally so failed replacements do not falsely supersede the earlier queued mission, and gives `missionType=0` a real cancel/clear path instead of routing it through the normal mission-install flow
- the old tracker-only `POST /command/{id}/cancel` path now fails closed instead of pretending to cancel a live mission without dispatching anything to drones; live cancellation must go through the real shared command path (`missionType=0`)
- standalone `RETURN_RTL` action completion now means the full operator-visible lifecycle completed (return, touchdown, disarm) rather than only "RTL mode was accepted", which keeps action semantics aligned with command tracking, mission end-behavior handling, and long-tail landing cleanup across modes
- Swarm Trajectory planner waypoint authoring now comes from one shared operator-brief builder across the waypoint modal and waypoint panel, so altitude/timing/heading ownership uses the same labels, tones, and derived-vs-operator wording in add/edit/review flows instead of drifting between separate component-specific summaries
- Swarm Trajectory waypoint-panel altitude editing now follows the same single-owner rule as timing and heading: `Target AGL` keeps stored MSL altitude as a derived readout, while direct MSL editing stays available only when `MSL input` owns the waypoint altitude
- Swarm Trajectory planner toolbar now surfaces the live handoff posture (`Draft only`, `Review required`, `Ready to process`) and reuses the readiness model's real transfer label instead of always showing the same generic cluster-assignment action even when the current route still needs review
- command tracking now exposes one normalized operator-facing `progress` snapshot across all missions, and lifecycle toasts use it to distinguish queued/scheduled commands, active execution, and the legitimate long-tail `finishing remaining drones` phase instead of making operators infer everything from the coarse legacy `status=executing` label
- Swarm Trajectory runtime validation logs now print the same normalized command `progress` snapshot that the API exposes, so live Hetzner/SITL audits can see execution-vs-finishing lifecycle state directly in terminal output instead of only raw ACK/execution counters
- Swarm Trajectory launch-preflight now consumes backend session change-detection truth, so stale processed packages are blocked when swarm structure, raw leader CSV contents, or trajectory-processing parameters changed after the last processing pass; the workspace stages and doctrine now surface the same freshness rule instead of treating those cases as merely advisory
- Swarm Trajectory planner timing presentation now comes from one shared utility across the waypoint panel, planner brief, leader-transfer dialog, and library summaries, so `Mission clock` / `Route entry` / `Route motion` wording no longer drifts and the waypoint panel no longer shows mission clock under the older ambiguous `Route time` label
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
- Swarm Trajectory planner terrain review no longer mistakes `groundElevation=0` for missing terrain, so sea-level routes keep their real terrain-confidence and AGL-clearance context in waypoint review instead of silently dropping those cues
- Swarm Trajectory authoring guidance now treats terrain confidence as a first-class operator cue and uses `leg` terminology consistently in the waypoint modal, keeping altitude/timing/heading/terrain ownership aligned across modal, panel, docs, and tests
- Trajectory library saves now reject blank/whitespace-only route names at both the dialog and storage layers, so planner saves cannot quietly create invalid catalog entries and valid names are normalized consistently before reuse or overwrite
- Swarm Trajectory planner, launch review, docs, and shared execution doctrine now state the mission frame explicitly: authored routes stay global lat/lon with stored MSL altitude, while PX4 launch/home truth remains an execution-time readiness and recovery input instead of a hidden route transform; the mission script also no longer carries the stale `shapes/.../swarm/processed` provenance path
- Swarm Trajectory planner import/export language now calls out the real asset boundary: CSV import/export is the authored leader route for round-trip editing or assignment, not the processed multi-drone mission package that gets launched later from `Swarm Trajectory` + dashboard Mission Type 4
- Swarm Trajectory planner/library/transfer summaries now label authored **Route Time** explicitly instead of a generic duration, because real command completion can be materially longer once initial climb, RTL, landing, and other end-behavior cleanup are included
- launch-from-ground mission dispatch now uses a live per-drone MAVSDK armability probe before GCS sends the command, closing the gap where passive telemetry could still look ready while PX4 would deny arming at mission start
- Drone API now exposes an explicit live armability probe endpoint backed by the same MAVSDK startup-health logic used by Drone Show and Swarm Trajectory mission startup, so launch gating and mission runtime share one armability definition
- live armability callers now use one total HTTP timeout budget derived from MAVSDK connect time + probe time + transport margin, so slow-but-valid SITL probes no longer get mislabeled as unreachable before the drone-side readiness endpoint has actually finished
- telemetry readiness now distinguishes actual PX4 HOME_POSITION truth from the first fallback GPS position cache, so `home_position_set` and launch gating no longer silently treat "we have a position sample" as "PX4 home is established"
- Swarm Trajectory / live readiness validation now treats a lone MAVLink `system_status=UNINIT` report as an advisory when PX4 preflight data and live telemetry are otherwise healthy, preventing false launch blocks after SITL mission recovery while still surfacing the discrepancy to operators
- Swarm Trajectory Mission Type 4 launch readiness is now scope-aware instead of globally all-or-nothing: a selected subset can launch when every selected drone has a processed output and the full required leader chain is included, while unrelated incomplete clusters stay as warnings instead of false blockers
- Swarm Trajectory selected-target safety is now enforced in both layers: the dashboard preflight blocks broken leader chains or missing processed outputs, and the backend `/submit_command` path rejects the same unsafe subset even if the UI is bypassed
- Swarm Trajectory status/preflight now exposes authoritative processed-package timing and altitude truth from the generated `Drone N.csv` files, so Mission Type 4 launch surfaces can show mission clock, route-entry time, route-motion window, and altitude envelope from the active package instead of relying on looser inferred summaries
- Swarm Trajectory package timing/altitude formatting now comes from one shared frontend utility across Mission Type 4 launch surfaces, and the leader-assignment dialog now shows the current selected-cluster package summary plus the exact “current outputs become stale until reprocess” impact of uploading a new leader CSV
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
- Swarm Trajectory waypoint authoring now labels derived timing/speed values explicitly (`Derived waypoint arrival time`, `Leg speed check`) so the modal and waypoint panel show which values are operator-owned versus planner-derived instead of relying on disabled fields or post-hoc warnings
- the waypoint panel guidance now tells operators that only owned inputs are editable, while derived timing and speed checks remain locked and continuously visible
- legacy frontend hook/dependency warnings in `DroneDetail`, `DroneGraph`, `Globe`, `MapSelector`, and `OriginModal` were cleaned up, and the dashboard production build now passes again under `CI=true`
- Swarm Trajectory planner and transfer now expose one shared operator-policy strip before assignment: the UI states explicitly that missions always execute stored MSL altitude, `Target AGL` is authoring input converted at planning time, terrain confidence changes review posture, and waypoint 1 owns route-entry timing/heading while later legs own ETA-versus-speed intent
- Swarm Trajectory processing workspace now repeats the same execution boundary before launch review: operators see in-page that only top leaders are authored, processed drones fly per-drone generated global paths, Smart Swarm is the live-follow mode instead, and any earlier AGL planning input has already been converted into the stored MSL mission package
- Swarm Trajectory planner CSV interchange now preserves authoring intent as optional metadata columns: exported leader CSVs keep altitude reference, target AGL, terrain confidence, timing mode, preferred speed, and calculated heading for round-trips back into the planner, while older minimal mission CSVs still import correctly and backend processors continue accepting the same required core columns
- Swarm Trajectory `Leg Review` now supports condensed attention-only and full-route audit modes, and each leg exposes compact timing, heading, altitude, and terrain-confidence intent so operators can audit the whole path without leaving the planner
- Swarm Trajectory subset runtime validation now adapts its generated short-profile route-entry delay to the selected follower offsets and reports inactive/post-mission geometry windows explicitly, preventing misleading failures when a short SITL validation route ends before a large-offset cluster can fully form
- command tracking now reopens ACK-only failed commands when later execution evidence proves the drone really ran the mission, so low-bandwidth false-offline classifications do not stay terminal forever
- Swarm Trajectory runtime validation now exposes stable processed-window aliases and requires sustained active geometry before declaring formation success, so a t=0 coincidence or immediate mission drop-out does not look like a valid convergence pass
- Swarm Trajectory subset formation validation now uses the processed per-drone mission package as the authoritative geometry reference over mission time, instead of re-deriving follower expectations from raw assignment offsets that no longer fully represent the executed global paths
- Swarm Trajectory planner timing summaries now separate `Mission Clock` from `Route Motion`, so route-entry delay is no longer silently folded into the same operator-facing “route time” number while also being shown separately elsewhere
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
- Swarm Trajectory page now takes processing recommendation and freshness guidance from the status payload itself, so workspace state, review prompts, and launch gating no longer depend on a second recommendation fetch that could drift from the active session snapshot
- Swarm Trajectory follower generation no longer carries a stale `formation_origin` contract through the processor; offsets are now documented and coded directly against each leader waypoint's instantaneous global position, which removes one misleading origin concept from the stack
- Swarm Trajectory planner/operator doctrine now states that follower regeneration is leader-waypoint-relative global geometry, not a separate centroid/origin model, so the planner brief and launch-policy notes match the real processor/runtime contract
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
- detached-worktree runtimes now resolve a meaningful git branch name for both
  GCS-side and drone-side git status reporting instead of surfacing
  `HEAD`/branch-read failures when the runtime lives in a git worktree
- the SSH git-sync bootstrap/update path now falls back to a detached
  `origin/<branch>` checkout when the named branch is already owned by another
  worktree, which keeps clean-runtime deployments and startup git sync working
  together on Hetzner and future production hosts
- generated SITL validator artifacts and trajectory-session state are now
  treated as runtime data instead of tracked repo content, so successful
  validation runs do not make the runtime repository appear dirty
- the public SITL download instructions in `docs/guides/sitl-comprehensive.md`
  now point at the refreshed `main@1c0ebc6` archive link published on
  2026-04-10
- the SITL validation docs now state the container lifecycle policy explicitly: recreate at suite start, before late Drone Show after other mission families, and after the suite; container reuse remains a narrow debugging convenience rather than the acceptance-grade default
- the SITL validation suite now supports a checked-in scenario library through `--list-bundled-plans` and `--plan-name`, so maintainers, CI, and AI agents can run named git-tracked scenarios from `tools/sitl_plans/` instead of relying on ad hoc temporary JSON plan files
- the checked-in SITL plan library now exposes stable named scenarios for configuration round-trip, Drone Show, actions, Smart Swarm, Swarm Trajectory, mission regression, and full operator regression while leaving the harder mixed-mode/fault-injection drills explicitly deferred until they are deterministic enough for routine acceptance
- the reusable SITL validation platform now treats Mission Config/origin as a first-class deterministic acceptance gate via `tools/validate_configuration_runtime.py`, a safe `config_only` template, and the default `operator_regression` flow `reset -> configuration -> reset_before_drone_show -> Drone Show -> actions -> Smart Swarm -> Swarm Trajectory -> final reset`
- fleet config persistence now accepts `PUT /api/v1/config/fleet?commit=false`, so live validation and other temporary config workflows can bypass git auto-push safely instead of inheriting the global writable-host policy
- suite provenance now tolerates non-git validator roots cleanly, so plain synced validator copies remain supported for split-root or remote-host workflows without noisy git stderr leakage
- the SITL validation docs and AI-agent SITL operating spec now describe the platform as host-agnostic, with explicit same-host, split-root, and remote-`base_url` usage instead of one VPS-specific layout
- retired the public GCS show-management legacy routes `/import-show`, `/download-raw-show`, `/download-processed-show`, `/get-show-info`, `/get-custom-show-info`, `/import-custom-show`, `/get-comprehensive-metrics`, `/get-safety-report`, `/validate-trajectory`, `/deploy-show`, `/get-show-plots`, `/get-show-plots/{filename}`, and `/get-custom-show-image`, leaving the canonical `/api/v1/shows/skybrush*` and `/api/v1/shows/custom*` surfaces as the only supported GCS contract for show workflows
- retired the public GCS configuration/swarm legacy routes `/get-config-data`, `/save-config-data`, `/validate-config`, `/get-drone-positions`, `/get-trajectory-first-row`, `/get-swarm-data`, `/save-swarm-data`, and `/request-new-leader`, leaving the canonical `/api/v1/config/fleet*` and `/api/v1/config/swarm*` surfaces as the only supported GCS contract for those domains
- `Show Design` / `Custom Show` operator guidance, Mission Details, and the Drone Show guide now reflect the current split between the normal SkyBrush import pipeline and the expert-only Custom CSV override
- Bootstrap installers now propagate custom repo/branch selections all the way into `mds_gcs_init.sh` / `mds_node_init.sh`, including explicit `--repo-url` support and correct persistence of custom branch settings in later config/state
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
  - `tools/mds_node_init.sh`: Uses shared banner with git info
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
- **Enterprise Raspberry Pi Initialization**: Production-ready `mds_node_init.sh`
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
# 2026-04-07

### Smart Swarm Airborne Gate
- Added Smart Swarm launch readiness gating in the dashboard so grounded targets now block formation dispatch, show the airborne count in scope, and expose a one-click quick-takeoff action for just the grounded drones using the shared Take Off altitude.
- Fixed the Smart Swarm readiness card so mission blockers render alongside advisories instead of silently hiding airborne-launch problems.
- Added reusable `smartSwarmLaunchReadiness` coverage plus Smart Swarm mission-detail tests for the grounded-target quick-takeoff workflow.

### Mission Config Card Compaction
- Reworked Mission Config drone cards around compact indicator buttons for slot, link, git, and custom fields so operators see identity and status first, then tap into the exact detail panel they need.
- Moved slot-source reconciliation, runtime transport/link data, and git diagnostics behind touch-friendly drilldowns instead of keeping verbose text permanently above the fold.
- Added focused `DroneConfigCard` test coverage for the new indicator-to-detail workflow.

# 2026-04-08

### QuickScout Corridor Search Foundation
- Added `corridor_search` as a real QuickScout mission template across schemas, persistence, workspace recovery, and operator planning state instead of treating QuickScout as polygon-plus-special-case search.
- Added corridor route and width planning inputs, buffered search-footprint previews, and corridor-aware stale-plan detection on both Mapbox and Leaflet planning surfaces.
- Generalized the shared QuickScout draw controls so area sweep can stay polygon-based while corridor search uses explicit line authoring instead of forcing route input through polygon-only code.
- Fixed a duplicated corridor resolver branch in the QuickScout service so one canonical template-to-polygon flow now feeds the planner and persisted workspace.
- Replaced the dashboard’s umbrella `@turf/turf` import with explicit geometry subpackages, updated the lockfile, and restored focused Jest coverage for QuickScout geometry helpers under the current CRA test stack.

### QuickScout Template-Aware Launch Review
- Updated the QuickScout launch-review card so it now shows template-specific search-doctrine context instead of presenting corridor, point, and polygon packages as one generic coverage job.
- Added corridor launch-review context for route-point count, route length, width, and buffered footprint, plus point-search review context for center and radius.
- Added reusable route-length geometry math plus focused launch-review component coverage to keep the review stage aligned with the new template-first planning workflow.

### QuickScout Monitor Package Context
- Added a shared QuickScout presentation utility so template labels, geometry summaries, and package metrics stay consistent between launch review and monitor mode.
- Updated monitor mode to keep mission-package context visible after launch, including template, footprint, coverage-time estimate, geometry summary, and mission brief.
- Added focused monitor-sidebar coverage so reopened corridor, point, and polygon missions retain operator context instead of collapsing to drone-state-only monitoring.

### QuickScout Findings Foundation
- Finished the QuickScout findings pivot by adding typed create/update finding payloads and using canonical `/api/sar/findings` bodies instead of raw dict patches.
- Migrated the QuickScout durable store onto a real `quickscout_findings` table with automatic import from the older `quickscout_pois` table so persistence is no longer half-renamed.
- Removed the redundant monitor-mode findings poll so QuickScout now rehydrates findings from the mission-status payload instead of making an extra request every cycle.
- Moved finding save/delete writes back into the QuickScout page container so the subsystem keeps one mutation path instead of hiding API writes inside leaf UI components.
- Added focused backend schema/store/route coverage plus Hetzner React tests and production build proof for the findings review flow.

### QuickScout Findings Cleanup And Follow-Up
- Removed the remaining public QuickScout `/api/sar/poi*` compatibility surface so findings are now the single active operator concept end to end.
- Removed the active `pois` / `poi_count` mirrors from mission status and mission summary contracts and renamed the remaining schema enums to `FindingType` / `FindingPriority`.
- Added monitor-mode actions to center the map on a reviewed finding and seed a new `last_known_point` follow-up search package directly from that finding.
- Unified QuickScout map focus behavior behind one shared page-level focus helper so monitor actions and follow-up planning use the same viewport path.
- Fixed the follow-up-plan label fallback so singleton mission catalogs preserve the mission label during follow-up seeding instead of dropping back to a generic `QuickScout follow-up`.

### QuickScout Handoff And Evidence Workflow
- Added a canonical `GET /api/sar/mission/{mission_id}/handoff` contract so operator handoff/export data is generated on the backend instead of being improvised in the browser.
- Added evidence-reference editing to the finding review workflow while keeping the extra detail folded behind an explicit operator action instead of permanently expanding the monitor sidebar.
- Added a compact QuickScout monitor handoff panel with a live brief, reviewed/unresolved/reference counts, top finding summary rows, and copy/export actions.
- Extended the QuickScout contracts, route inventory, backend tests, frontend service tests, and monitor-mode component coverage for the new handoff/evidence workflow.

# 2026-04-09

### PX4 Parameters Profile Library And Safer Batch Workflow
- Added canonical GCS routes for repo-backed PX4 parameter profiles and moved approved fleet-baseline assets under `resources/px4_param_profiles/` instead of scattering reusable parameter bundles across unrelated SITL or action paths.
- Added a first-class `Profiles` workspace to the dashboard PX4 Parameters page so operators can review saved baselines, compare them against a live drone snapshot, export typed MDS profile JSON, and hand the selected profile directly into tracked batch apply.
- Reworked PX4 batch writes so operator scope now starts at `None`, saved profiles are the default repeatable path, and one-off raw batch entry stays available only as an explicit advanced mode.
- Removed the older `Apply Common Params` operator shortcut from the dashboard action surface so PX4 parameter management has one clean operator entry point instead of competing UI flows.
- Added focused backend profile-store/route coverage plus focused React coverage for the PX4 parameter workspaces, profile workflows, and action-surface cleanup.
## 2026-04-09

### Added
- **PX4 Parameters Profile Library And Safer Batch Workflow**
  - repo-backed PX4 parameter profiles now live under `resources/px4_param_profiles/`
  - new `Profiles` workspace in the dashboard for review, diff, export, and batch handoff
  - new storage-layout guide: `docs/guides/repo-asset-layout.md`
  - new `resources/README.md` documenting the intended repo-backed asset layout

### Changed
- **PX4 Parameter Storage Clarification**
  - live fleet config remains rooted at `config*.json` / `swarm*.json`
  - generated mission artifacts remain under `shapes/` / `shapes_sitl/`
  - legacy `APPLY_COMMON_PARAMS` compatibility now defaults to `resources/common_params.csv`

# 2026-04-10

### Fleet Candidate Registry Foundation
- Added a durable GCS-side fleet candidate registry under `runtime_data/` so heartbeat-visible or explicitly announced nodes now have one canonical pending-enrollment source of truth instead of Mission Config inferring candidates in the browser.
- Added canonical `/api/v1/fleet/candidates/*` routes for list, announce, accept, replace, reject, and ignore actions, with typed schemas for future CLI/MCP/operator automation.
- Wired heartbeat acceptance to observe unknown nodes into the candidate registry without reviving silent config enrollment, while keeping heartbeat acceptance itself the primary path.
- Reworked replacement semantics so a spare like `H101` taking over failed slot `P12` rewrites both `config.json` and `swarm.json` follow references instead of treating replacement as a browser-only config edit.
- Cut Mission Config over to the backend candidate registry so pending enrollment cards now come from GCS state, not a second local heartbeat-diff algorithm.
- Narrowed the announce contract to node identity / bootstrap fields only, keeping GCS-derived state out of the bootstrap payload and avoiding another mixed source-of-truth surface.

### PX4 Parameters Compact Grouping And Touch Layout Refinement
- Reworked the PX4 Parameters compact/touch list into a grouped scan-first layout so phone, tablet, and touch desktop-mode sessions browse by PX4 section instead of reading a squeezed pseudo-table.
- Reduced compact row clutter by moving rich metadata back into the detail dialog and keeping inline rows focused on name, current value, and safety/reference icons.
- Fixed the compact group state so operators can manually open a different PX4 section without the UI snapping back to the previously selected parameter group.
- Added focused React coverage for grouped compact browsing plus the shared dialog flow across narrow and touch-coarse viewports.
- Followed up the compact list alignment so rows now read as a proper operator list: parameter identity stays left-aligned, current value and state icons trail on the right, and snapshot refresh no longer auto-selects a parameter before the operator chooses one.
