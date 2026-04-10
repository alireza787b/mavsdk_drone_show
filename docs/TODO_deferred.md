# Deferred TODOs — Product Backlog

Deferred items across identity, config, SITL, frontend, and command/runtime workflows.
Some older items originated in the hw_id/pos_id cleanup (2026-03-05), but this file is now the shared deferred backlog so phase handoffs do not lose important follow-up work.

---

## TODO 1: Decouple hw_id from MAV_SYS_ID (for >254 drones)

**Priority:** Medium (needed when fleet > 254)
**Status:** Deferred — current fleet uses 1-254 range

**Problem:** `hw_id` is currently set equal to `MAV_SYS_ID` (PX4 parameter). MAVLink system IDs are `uint8` (1-254). If hw_id exceeds 254, it silently truncates on the wire, causing collisions.

**Solution:** Add `mav_sys_id` field to config.json. `hw_id` becomes a pure software identity (any positive integer). `mav_sys_id` is the MAVLink address (1-254), independently assigned. Consider Skybrush's `SHOW_GROUP` parameter approach for >250 drones.

**Files to modify:**
- `actions.py` — `init_sysid()` function (currently sets `MAV_SYS_ID = HW_ID`)
- `multiple_sitl/startup_sitl.sh` — `MAV_SYS_ID` env variable
- `multiple_sitl/set_sys_id.py` — PX4 rcS modification
- `gcs-server/config.py` — add `mav_sys_id` to drone schema
- `src/drone_config/config_loader.py` — load mav_sys_id from config.json
- `tools/mds_init_lib/common.sh` — `validate_drone_id()` upper bound (currently 999)
- Frontend config editor — add mav_sys_id field

**Reference:** Skybrush Sidekick 1.8.0+ `SHOW_GROUP` extension

---

## TODO 2: Auto-update swarm follow chains on role swap

**Priority:** Medium
**Status:** Deferred — needs UX design for swarm mode interaction

**Problem:** `swarm.json` `follow` field references `hw_id`. If drone hw_id=2 fails and spare hw_id=10 takes pos_id=2, followers still reference `follow=2` (the dead drone). Operators must manually edit swarm.json.

**Solution:** When operator changes a drone's pos_id in config.json (via UI), detect if swarm.json follow chains reference the old hw_id and offer to auto-update. Options:
- (a) Change `follow` column to reference pos_id instead of hw_id
- (b) Keep hw_id reference but add UI warning + auto-update on role swap
- (c) Option (b) is recommended — minimal data model change, smart UI

**Files to modify:**
- `gcs-server/config.py` — add swarm chain validation in `validate_and_process_config()`
- `gcs-server/app_fastapi.py` — endpoint to update swarm follow chains
- Frontend `SwarmDesign.js` — warning when follow target is offline/replaced
- Frontend `SaveReviewDialog.js` — warn about broken follow chains

---

## TODO 3: ~~Move from CSV to JSON/YAML configuration~~ DONE

**Priority:** ~~Low~~ Completed
**Status:** DONE (2026-03-06) -- migrated to JSON with Pydantic validation

**Problem:** CSV was fragile (column order dependent, no nesting, no comments, no schema validation, no versioning). Complex config (nested parameters, arrays) could not be represented.

**Solution:** Migrated to JSON with Pydantic `extra='allow'` schemas. Config files are now `config.json`/`swarm.json` (and `config_sitl.json`/`swarm_sitl.json` for SITL). Dashboard supports both JSON (primary) and CSV (legacy import/export). See `docs/guides/config-json-format.md` for format reference.

---

## TODO 4: Central config service (pull-based)

**Priority:** Low
**Status:** Deferred — needs offline fallback design

**Problem:** Each drone reads config.json from its local filesystem. Config changes require git push + git pull on every drone. Slow for large fleets.

**Solution:** Drones pull config from GCS API on boot. GCS serves as config authority. Drones cache last-known config for offline fallback. Config changes propagate instantly on next heartbeat cycle.

**Files to modify:**
- `src/drone_config/config_loader.py` — add API-based config fetching
- `gcs-server/app_fastapi.py` — add `/drone-config/{hw_id}` endpoint
- `src/heartbeat_sender.py` — include config version hash in heartbeat

---

## TODO 5: Validate config on drone boot

**Priority:** Medium
**Status:** Deferred — needs inter-drone awareness at boot time

**Problem:** A drone boots and reads its config without checking for duplicate pos_ids. Two drones with the same pos_id will both arm and fly identical trajectories, causing mid-air collision.

**Solution:** On startup, after loading config, query GCS for all active drones' pos_ids. If collision detected, refuse to arm and show clear error. Alternative: GCS validates and blocks command submission if duplicates exist (partially implemented in `validate_and_process_config()`).

**Files to modify:**
- `src/drone_config/__init__.py` — add boot-time validation
- `coordinator.py` — fail-safe check before entering ready state
- `gcs-server/app_fastapi.py` — add `/validate-drone/{hw_id}` endpoint

---

## TODO 6: QuickScout mission-batch launch identity and optional true continue/resume adapter

**Status:** Deferred — wait until the new QuickScout mission workspace and operator workflow settle

**Problem:** QuickScout now uses the shared tracked command lifecycle for launch, hold, and abort, and monitor mode no longer pretends paused coverage packages can directly resume in V1. Two deliberate follow-up design questions still remain:

- launch creates one tracked command per drone because each QuickScout plan payload is unique
- a true FC-backed continue/resume adapter does not exist; the current product doctrine is to hold, then plan a follow-up package from current state

These are acceptable for the current subsystem maturity, but they should stay visible as follow-up design decisions rather than getting forgotten as accidental permanent behavior.

**Solution:** Revisit both after the next QuickScout workflow/UI slices:

- decide whether operators need a mission-batch launch identity that groups the per-drone launch commands under one mission-level launch record
- design a true continue/resume adapter only if the mission executor and operator workflow can support it cleanly without weakening the current honest hold-and-replan doctrine

**Likely touch points:**

- `gcs-server/sar/service.py`
- `gcs-server/sar/schemas.py`
- future QuickScout workspace/frontend components

## TODO 7: QuickScout advanced retasking and findings-aware SITL expansion

**Status:** Deferred — findings foundation, evidence refs, handoff/export, finding-seeded follow-up planning, and template-complete findings-aware runtime validation are complete, but mid-mission retasking and deeper advanced drills are not yet done

**Problem:** QuickScout now has real mission templates, tracked execution semantics, durable findings, and reusable SITL gates, but it still lacks the next operational layer:

---

## TODO 8: Converge maintenance identity / firmware reporting into PX4 parameter workflows deliberately

**Priority:** Medium
**Status:** Deferred — do not duplicate or hardcode before there is one clean shared contract

**Problem:** The product now has a proper `PX4 Parameters` workspace, but two related maintenance concerns still sit outside that finished operator model:

- `INIT_SYSID` is still a legacy maintenance action that writes `MAV_SYS_ID`
  directly in the action pipeline instead of going through the newer shared
  PX4 parameter service surface
- operators may want PX4 firmware/build identity beside parameter operations,
  but MDS should not guess or hardcode that from mixed sources

**Solution:**

- migrate `INIT_SYSID` onto the shared PX4 parameter write path when the action
  pipeline audit is active, but keep it as a maintenance workflow, not a second
  overlapping runtime control surface inside the main parameter table
- only add firmware/build identity to the PX4 Parameters page after there is a
  clean vehicle-served source, ideally PX4 component metadata / autopilot
  version semantics cached by vehicle identity

**Likely touch points:**

- `actions.py`
- `src/drone_setup.py`
- `src/px4_params/service.py`
- `app/dashboard/drone-dashboard/src/pages/Px4ParametersPage.js`
- future hardware-grade metadata cache / vehicle identity services

- add-drone/remove-drone or deeper follow-up package generation from the current airborne state
- richer retask / fault-injection SITL drills beyond the validated findings-aware launch-control path

**Solution:** Revisit after the current findings checkpoint is merged into the active QuickScout stream:

- add planner/control seams for mid-mission reassignment only after the operator workflow is explicit
- add later media attachment/upload on top of the now-stable evidence reference model
- promote deeper retask and fault-injection SITL scenarios once the next control slice is stable

**Likely touch points:**

- `gcs-server/sar/{schemas,service,store,routes}.py`
- `app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js`
- `app/dashboard/drone-dashboard/src/components/sar/*`
- `tools/sitl_plans/*`
- `tools/validate_quickscout_runtime.py`
- `tools/validate_quickscout_runtime.py` and the checked-in `quickscout_runtime` / `quickscout_multi_runtime` plans if mission-batch launch identity or a true resume adapter is introduced

---

## TODO 7: Harder simultaneous mixed-mission and fault-injection SITL plans

**Priority:** Medium
**Status:** Deferred — the checked-in `integrated_mixed_mode` and `advanced_operator_regression` plans are now validated; this TODO remains only for the harder next tier

**Problem:** The reusable SITL validation platform now covers the core deterministic acceptance gate plus the validated mixed-mode leader-override path, but it still does not encode the harder next-tier operator scenarios we want later: simultaneous mixed mission families on one fleet, command supersession under heavier load, delayed triggers across subgroups, and deliberate failure/fallback drills.

**Solution:** Add explicit advanced JSON plan examples and, where needed, new validator helpers for:

- simultaneous mixed-mode partial-fleet exercises
- command override and supersession stress cases
- precision-move-to-precision-move override from each drone's then-current local state
- late-command / delayed-trigger timing checks
- optional fault-injection drills that remain deterministic enough for repeatable acceptance use

**Files to modify:**
- `tools/run_sitl_validation_suite.py` — add or document stable advanced plan patterns
- `tools/validate_*.py` — add bounded helper hooks only when a scenario cannot be expressed cleanly as a plan
- `docs/guides/sitl-validation-platform.md` — document advanced plan recipes and acceptance boundaries
- `docs/guides/sitl-comprehensive.md` — link the advanced validation path once it is stable

---

## TODO 8: Audit the DroneSetup / actions.py / runner pipeline after precision-move rollout

**Priority:** Medium
**Status:** Deferred — wait until Precision Move stabilizes under broader operator/SITL use

**Problem:** Precision Move landed on the new typed action-runner seam, but the wider action pipeline still needs one deliberate audit so older immediate actions, subprocess launch rules, runtime payload handling, and future MCP/manual/CLI entrypoints all converge cleanly on the same execution model.

**Solution:** Review the full action pipeline and normalize:

- `DroneSetup` mission handler responsibilities
- `actions.py` CLI/runtime adapter responsibilities
- runner lifecycle hooks and payload loading
- progress/error reporting seams
- future MCP / manual-CLI entrypoint ergonomics

**Files to revisit:**
- `src/drone_setup.py`
- `actions.py`
- `src/action_runners/*`
- `src/drone_communicator.py`
- related command-reporting docs/tests

---

## TODO 9: Modernize dashboard dependencies after Precision Move

**Priority:** Medium
**Status:** Deferred — surfaced during Hetzner validation for the Precision Move UI slice

**Problem:** `npm ci` in the dashboard still surfaces several deprecated CRA-era dependencies and the audit result still reports known vulnerabilities. This did not block the Precision Move feature, but it is real maintenance debt.

**Solution:** Plan a controlled frontend dependency modernization pass that reduces deprecated packages and vulnerability backlog without destabilizing the operator UI.

**Files to revisit:**
- `app/dashboard/drone-dashboard/package.json`
- `app/dashboard/drone-dashboard/package-lock.json`
- related build/test tooling docs

---

## TODO 10: Evaluate true continuous manual-control mode separately from Precision Move

**Priority:** Medium
**Status:** Deferred — keep Precision Move on discrete audited step commands for now

**Problem:** Operators asked for an RC-like steer mode, but a true continuous offboard-control stream has different safety, supervision, logging, MCP/API, and link-loss behavior than discrete Precision Move steps. Folding that into the same first implementation would blur two different operator contracts.

**Solution:** Keep `Precision Move` as the discrete local-relative repositioning action with `Planned Move` and `Live Jog` surfaces. Revisit continuous manual-control as a separate feature only after we define:

- explicit authority/arming gates
- link-loss and timeout behavior
- continuous-stream ownership and override semantics
- telemetry/progress visibility expectations
- MCP/manual/CLI/operator-console usage rules

**Files to revisit:**
- `src/action_runners/precision_move.py`

---

## TODO 11: Hardware-grade PX4 parameter metadata discovery and caching

**Priority:** Medium
**Status:** Deferred — current PX4 Parameters v1 is correct for SITL and managed local-runtime deployments

**Problem:** The current PX4 parameter workspace uses vehicle values plus the best metadata available in the current runtime. In SITL and managed companion environments, the generated PX4 `parameters.json` catalog is available locally and is the strongest metadata source. On real hardware fleets, the long-term best-practice source should be vehicle-served PX4 metadata via the MAVLink Component Metadata / MAVLink FTP path, cached by firmware identity or metadata CRC.

**Solution:** Add a hardware-grade metadata resolver layer that:

- requests PX4 component metadata from the connected vehicle when supported
- downloads and caches parameter metadata by CRC / firmware identity
- prefers that cached vehicle-served metadata over local build artifacts
- keeps official PX4 docs links as operator-reference fallback only, not as the machine-readable authority
- preserves the current local-catalog path for SITL and controlled embedded deployments

**Files to revisit:**
- `src/px4_params/catalog.py`
- `src/px4_params/service.py`
- `src/px4_param_models.py`
- `docs/px4-parameters.md`
- future GCS-side metadata cache storage/docs once the hardware path is implemented
- `src/command_contract.py`
- `app/dashboard/drone-dashboard/src/components/PrecisionMoveDialog.js`
- future manual-control/MCP docs and validators

---

## TODO 12: Named bootstrap profiles and fleet automation assets

**Priority:** Medium
**Status:** Deferred — node bootstrap, candidate announce, and Fleet Enrollment are now canonical, but named preset files and automation assets are not yet first-class repo resources

**Problem:** The companion bootstrap and enrollment workflow is now coherent, but operators and automation still assemble provisioning inputs from CLI args, environment variables, and external inventory tooling. There is not yet one checked-in preset system for repeatable fleet classes such as:

- `netbird_managed`
- `static_local`
- `manual_router`
- customer-specific repo / branch defaults

**Solution:** Add a bootstrap-profile layer on top of the current canonical scripts instead of introducing a second provisioning path. Likely assets:

- `resources/bootstrap_profiles/`
- documented JSON/YAML schema for profile values
- examples for Ansible inventory / vault-backed usage
- optional `--profile` support in `mds_node_init.sh`

This is post-v1 hardening, not missing core functionality.

---

## TODO 13: mavlink-anywhere integration review and automation polish

**Priority:** Medium
**Status:** Deferred — current MDS bootstrap already integrates with `mavlink-anywhere`, but the external repo has not yet been reviewed and tightened as part of this enrollment redesign

**Problem:** The companion bootstrap depends on `mavlink-anywhere` for the recommended real-hardware routing path. The MDS side is now cleaner, but the cross-repo automation, docs, and machine-friendly integration seams have not been fully audited yet.

**Solution:** Review the `mavlink-anywhere` repo as a follow-up and improve only where it materially helps MDS deployment:

- cleaner non-interactive install/config flow
- clearer outputs for AI/automation/MCP use
- docs alignment with `mds_node_init.sh`
- optional tagging/release guidance if real changes are made there

---
