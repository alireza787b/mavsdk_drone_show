# Runtime Architecture Migration Log

## Purpose

Persistent journey log for the runtime architecture refactor approved on 2026-04-21.

This log exists so implementation slices can be reviewed without relying on chat history.

## Approved Direction

- retire `.hwID` as canonical identity
- retire `real.mode` as canonical mode switch
- introduce canonical:
  - `MDS_HW_ID`
  - `/etc/mds/node_identity.json`
  - `MDS_MODE=real|sitl`
- replace `Params`-centric ownership with typed settings
- keep old markers only as short migration bridges
- official first, private sync only after official verification

## Slice 1

### Scope

- introduce typed settings helpers
- make `MDS_MODE` canonical in code
- make `node_identity.json` part of canonical HW identity resolution
- update bootstrap outputs to emit `MDS_MODE`
- update SITL and GCS runtime launchers to emit/read `MDS_MODE`
- update verification and source-of-truth docs

### Risks acknowledged

- existing `.hwID` and `real.mode` users still exist across SITL/bootstrap/tests
- this slice keeps compatibility reads while shifting canonical ownership

### Exit criteria

- code resolves mode from `MDS_MODE` first
- code resolves HW identity from `MDS_HW_ID` / `node_identity.json` before `.hwID`
- bootstrap emits `MDS_MODE=real`
- SITL emits `MDS_MODE=sitl`
- targeted tests pass

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- added `src/settings/runtime.py` and `src/settings/identity.py`
- made `ConfigLoader.get_hw_id()` resolve canonical identity first
- made `Params` resolve canonical `MDS_MODE` first
- updated bootstrap/local env generation to emit `MDS_MODE=real`
- updated node identity manifest generation to record runtime mode
- updated GCS and SITL launchers to export `MDS_MODE`
- updated verification helpers and operator-facing docs to describe the canonical ownership model
- added targeted tests for canonical env-file-backed mode and identity resolution

Hetzner verification:

- `tests/test_runtime_settings.py`: 6 passed
- `tests/test_drone_config_components.py`: 42 passed
- `tests/test_coordinator.py`: 44 passed
- `tests/test_bootstrap_installers.py`: 30 passed

Residual drift intentionally deferred to the next slice:

- `app/linux_dashboard_start.sh` still owns `real.mode` compatibility-marker handling
- bootstrap tests still assert the current GCS launcher `real.mode` behavior
- SITL image/docs still describe preserving `*.hwID` runtime markers
- compatibility marker creation remains in bootstrap until service/bootstrap ownership is refactored

## Slice 2

### Scope

- move the GCS launcher from `real.mode`-first behavior to canonical `MDS_MODE` ownership
- make `--status` report canonical runtime state after loading `/etc/mds/gcs.env`
- keep `real.mode` only as a mirrored compatibility marker for older runtime paths
- harden test isolation around env-file-backed preload behavior

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- `app/linux_dashboard_start.sh`
  - now resolves runtime mode from `MDS_MODE` first
  - persists requested mode switches back into `/etc/mds/gcs.env` when writable
  - mirrors canonical mode into `real.mode` only as a compatibility marker
  - loads system config before handling `--status`
  - reports runtime mode source and legacy-marker status explicitly
- `src/settings/runtime.py`
  - now clears previously injected local-env keys when switching env-file paths
  - exposes a reset helper for deterministic test isolation
- `tests/conftest.py`
  - now resets the preload layer around each test
- updated launcher regression coverage in `tests/test_bootstrap_installers.py`

Hetzner verification:

- `bash -n app/linux_dashboard_start.sh`
- `bash -n gcs-server/start_gcs_server.sh`
- `tests/test_runtime_settings.py tests/test_drone_config_components.py tests/test_coordinator.py tests/test_bootstrap_installers.py`
- result: 123 passed

Residual drift intentionally deferred to the next slice:

- bootstrap still creates `.hwID` and `real.mode` compatibility markers
- service/bootstrap ownership around install paths and service templates still needs cleanup
- SITL docs and image prep still refer to `*.hwID` runtime preservation

## Slice 29

### Scope

- expose compact node-local `mavlink-anywhere` and Smart Wi-Fi posture through
  the existing node git-status payload
- propagate that posture through the GCS fleet git-status aggregation
- distinguish directly reachable node dashboards from loopback-only bindings so
  operators do not get misleading links

### Checkpoint Result (2026-04-23)

Status: complete

Implemented:

- added shared `src/managed_runtime_status.py` helpers so GCS Runtime Admin and
  node git-status read the same reconcile-status model
- extended the node `GET /api/v1/git/status` response with compact
  `mavlink_runtime` and `connectivity_runtime` summaries
- extended GCS fleet git aggregation to carry those summaries through and
  derive `dashboard_access_mode` / `dashboard_url`
- updated the drone git inspector UI to show compact sidecar posture and only
  render dashboard links when they are actually reachable
- added targeted Python regression coverage for node git status, fleet git
  aggregation, and dashboard access resolution

Verification:

- `tests/test_drone_api_http.py -k git_status`
- `tests/test_gcs_api_http.py -k git_status`
- `tests/test_managed_runtime_status.py`
- `git diff --check`

Residual drift intentionally deferred to the next slice:

- frontend Jest execution in the clean worktree is still blocked by missing
  local `node_modules` on this host
- service-update/reconcile restart policy still needs a dedicated operator-safe
  slice instead of relying only on git-sync side effects

## Slice 30

### Scope

- persist a durable node-local post-sync runtime summary during git sync
- expose that summary through node and GCS git-status payloads
- make service/unit updates and sidecar reconcile outcomes visible without
  scraping logs manually

### Checkpoint Result (2026-04-23)

Status: complete

Implemented:

- `tools/update_repo_ssh.sh` now persists node-local sync runtime state to
  `MDS_GIT_SYNC_STATE_FILE` / `/var/lib/mds/git-sync/last_result.env`
- recorded state now includes:
  - latest sync status
  - updated systemd units
  - coordinator restart scheduling
  - connectivity reconcile result
  - MAVLink runtime reconcile result
  - Python requirements update result
- node `GET /api/v1/git/status` now exposes `git_sync_runtime`
- GCS fleet git aggregation now carries `git_sync_runtime`
- drone git inspector UI now shows the node-local post-sync summary
- added shell regression coverage for the persisted state file plus targeted
  node/GCS Python coverage

Verification:

- `bash -n tools/update_repo_ssh.sh`
- `tests/test_bootstrap_installers.py -k "git_sync_runtime_state_persists_post_sync_summary or post_sync_runtime_restart"`
- `tests/test_drone_api_http.py -k git_status`
- `tests/test_gcs_api_http.py -k git_status`
- `tests/test_managed_runtime_status.py`
- `git diff --check`

Residual drift intentionally deferred to the next slice:

- frontend Jest execution in the clean worktree is still blocked by missing
  local `node_modules` on this host
- GCS still does not own fleet-wide sidecar profile rollout; it only exposes
  visibility and node-local entry points today

## Slice 3

### Scope

- parameterize runtime user, home directory, and install path in the active bootstrap libraries
- render systemd unit templates before install instead of copying raw placeholder templates
- stop the active service reconciliation path from comparing unrendered templates against installed units
- keep compatibility markers in place, but make the bootstrap/service layer host-aware and non-hardcoded

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- `tools/mds_init_lib/common.sh`
  - runtime user/home/install-dir are now derived from `MDS_USER`, `MDS_HOME`, and `MDS_INSTALL_DIR`
- `tools/mds_init_lib/prereqs.sh`
  - runtime user creation and home checks now honor the resolved runtime user/home
- `tools/mds_init_lib/repo.sh`
  - repo SSH paths now resolve from `MDS_HOME`
- service templates
  - `coordinator.service`
  - `git_sync_mds.service`
  - `led_indicator.service`
  - `wifi-manager.service`
  now use runtime placeholders instead of hardcoded `droneshow` and `/home/droneshow/...`
- `tools/mds_init_lib/services.sh`
  - now renders service templates before install
  - runtime-owned sudoers/polkit paths are parameterized
  - unit comparison now occurs against the rendered unit content
- `tools/git_sync_mds/install_git_sync_mds.sh`
  - now renders runtime values for user/home/install-dir
- `tools/update_repo_ssh.sh`
  - service drift checks now render runtime placeholders before comparing against installed units
- regression coverage added for runtime override handling and rendered service installation

Hetzner verification:

- remote shell validation:
  - `tools/mds_init_lib/common.sh`
  - `tools/mds_init_lib/repo.sh`
  - `tools/mds_init_lib/prereqs.sh`
  - `tools/mds_init_lib/services.sh`
  - `tools/git_sync_mds/install_git_sync_mds.sh`
  - `tools/update_repo_ssh.sh`
- remote targeted regression suite:
  - `tests/test_runtime_settings.py`
  - `tests/test_drone_config_components.py`
  - `tests/test_coordinator.py`
  - `tests/test_bootstrap_installers.py`
- result: 125 passed

Residual drift intentionally deferred to the next slice:

- compatibility marker creation still exists in bootstrap (`.hwID`, `real.mode`)
- several non-primary/legacy helper scripts under `tools/` still hardcode `droneshow` or `/home/droneshow`
- docs still need a broader source-of-truth consolidation around deployment profiles, rendered runtime env, and mode/identity migration

## Slice 4

### Scope

- introduce a git-tracked deployment profile default layer shared by Python and shell
- remove duplicate repo/branch/GCS fallback defaults from active runtime/bootstrap code
- extend the same default layer into the active SITL/release helper path

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- added `deployment/defaults.env` as the git-tracked deployment-default source of truth for:
  - default repo slug
  - default SSH/HTTPS repo URLs
  - default branch
  - default real/sitl GCS IP
  - default GCS API port
- added `tools/load_deployment_profile.sh`
  - shared shell loader for repo-tracked deployment defaults
- added `src/settings/deployment_profile.py`
  - typed Python loader for the same git-tracked deployment profile
- updated `src/params.py`
  - repo defaults and mode-specific GCS defaults now come from the deployment profile instead of hardcoded literals
- updated active bootstrap/runtime shell path:
  - `tools/mds_init_lib/common.sh`
  - `tools/mds_init_lib/repo.sh`
  - `tools/mds_gcs_init_lib/gcs_common.sh`
  - `tools/mds_gcs_init_lib/gcs_repo.sh`
  - `tools/mds_gcs_init_lib/gcs_env_config.sh`
  - `tools/update_repo_ssh.sh`
  - `app/linux_dashboard_start.sh`
- updated active SITL/release helpers to use the same deployment defaults:
  - `tools/build_custom_image.sh`
  - `tools/release_sitl_image.sh`
  - `tools/sitl_image_prepare.sh`
  - `tools/mds_git_access_check.sh`
  - `multiple_sitl/startup_sitl.sh`
  - `multiple_sitl/create_dockers.sh`
- updated docs and templates so runtime source-of-truth guidance now explicitly includes `deployment/defaults.env`
- added tests for:
  - deployment profile parsing
  - `Params` using deployment profile defaults
  - shell/common loader integration
  - repo verification moving away from `params.py`-based warnings

Local verification:

- shell validation for all touched shell entrypoints passed
- targeted local regression suite:
  - `tests/test_runtime_settings.py`
  - `tests/test_drone_config_components.py`
  - `tests/test_coordinator.py`
  - `tests/test_bootstrap_installers.py`
- result: 129 passed

Hetzner verification:

- remote shell validation for all touched shell entrypoints passed
- same targeted remote regression suite passed
- result: 129 passed

Residual drift intentionally deferred to the next slice:

- compatibility markers still exist:
  - `.hwID`
  - `real.mode`
- older wrapper/install/helper scripts that run outside the primary in-repo bootstrap path still need cleanup or explicit archival treatment
- docs still need a tighter operator-facing explanation of:
  - deployment profile vs rendered host env
  - what is safe to change in git vs what remains host-local

## Slice 5

### Scope

- make the public bootstrap wrappers align with the new deployment-profile model
- remove wrapper-level assumptions that the repo name is always `mavsdk_drone_show`
- make wrapper help/output accurately reflect runtime-user and install-dir overrides
- update operator docs so the wrapper behavior matches the implemented bootstrap surface

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- updated `tools/install_companion.sh`
  - local-checkout execution now derives repo fallback behavior from `deployment/defaults.env`
  - repo-path normalization now uses the deployment-profile repo basename instead of hardcoding `mavsdk_drone_show`
- updated `tools/install_mds_node.sh`
  - wrapper defaults now derive from deployment profile:
    - repo URL
    - branch
    - repo directory basename
  - default install path now tracks the resolved repo basename instead of assuming `/home/<user>/mavsdk_drone_show`
  - help output now surfaces:
    - `MDS_USER`
    - `MDS_INSTALL_DIR`
    - dynamic bootstrap URLs derived from the active deployment profile
- updated `tools/install_gcs.sh`
  - wrapper defaults now derive from deployment profile:
    - repo URL
    - branch
    - repo directory basename
  - default install path now tracks the resolved repo basename instead of assuming `~/mavsdk_drone_show`
  - help output now surfaces the effective default install path
- updated operator docs:
  - `docs/guides/mds-init-setup.md`
  - `docs/guides/gcs-setup.md`
  - both guides now explain wrapper-level `MDS_USER` / `MDS_INSTALL_DIR` overrides and that local-checkout wrapper execution reads `deployment/defaults.env`
- extended test coverage for wrapper behavior:
  - profile-derived repo basename changing the default install dir
  - explicit runtime-user/install-dir environment overrides

Local verification:

- shell validation passed for:
  - `tools/install_companion.sh`
  - `tools/install_mds_node.sh`
  - `tools/install_gcs.sh`
- targeted local regression suite:
  - `tests/test_runtime_settings.py`
  - `tests/test_drone_config_components.py`
  - `tests/test_coordinator.py`
  - `tests/test_bootstrap_installers.py`
- result: 132 passed

Hetzner verification:

- synced worktree to:
  - `root@204.168.181.45:/tmp/mds_runtime_arch_phase1_remote/`
- remote shell validation passed for:
  - `tools/install_companion.sh`
  - `tools/install_mds_node.sh`
  - `tools/install_gcs.sh`
- same targeted remote regression suite passed
- result: 132 passed

Residual drift intentionally deferred to the next slice:

- compatibility markers still remain in the runtime/bootstrap path:
  - `.hwID`
  - `real.mode`
- several legacy/non-primary helper scripts outside the active wrapper/bootstrap path still need explicit retirement or archival treatment
- docs still need the broader final consolidation that will replace `params.py` language with the final typed-settings/runtime-authority model once the compatibility bridge is removed

## Slice 6

### Scope

- normalize runtime repo authority so bootstrap/update paths follow the requested repo URL instead of inheriting whatever remote already exists
- surface repo-authority drift in GCS verification and launcher status output
- document that `/etc/mds/gcs.env` and `/etc/mds/local.env` own runtime repo authority, while `origin` is derived state

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- updated `tools/mds_init_lib/repo.sh`
  - added explicit checkout-remote reconciliation for nodes
  - node update flow now follows the requested runtime repo URL instead of blindly reusing the existing `origin`
  - node update flow now persists the effective repo URL/branch back into bootstrap state
  - repo shorthand normalization now uses the deployment-profile repo basename instead of hardcoded `mavsdk_drone_show`
- updated `tools/mds_gcs_init_lib/gcs_repo.sh`
  - added explicit checkout-remote reconciliation for the GCS repo
  - clone/update now exports the effective repo URL/branch back into shell state
  - GCS fork shorthand now uses the deployment-profile repo basename instead of hardcoded `mavsdk_drone_show`
- updated `tools/mds_gcs_init_lib/gcs_verify.sh`
  - repository verification now displays:
    - configured repo URL
    - actual `origin` remote
    - repo-authority match/mismatch
    - repo access mode
    - auto-push mode
  - mismatches now produce an explicit warning instead of remaining implicit
- updated `app/linux_dashboard_start.sh`
  - `--status` now displays:
    - configured repo URL
    - actual `origin` remote
    - repo-authority status
    - repo access mode
    - git auto-push mode
- updated `docs/guides/runtime-config-sources.md`
  - clarified that `/etc/mds/gcs.env` and `/etc/mds/local.env` are the canonical runtime repo authority, while `origin` is derived state that must be reconciled
- extended bootstrap tests for:
  - node repo remote reconciliation
  - GCS repo remote reconciliation
  - launcher / verification surfacing repo authority fields

Local verification:

- shell validation passed for:
  - `tools/mds_init_lib/repo.sh`
  - `tools/mds_gcs_init_lib/gcs_repo.sh`
  - `tools/mds_gcs_init_lib/gcs_verify.sh`
  - `app/linux_dashboard_start.sh`
- focused bootstrap regression:
  - `tests/test_bootstrap_installers.py`
  - result: 39 passed
- targeted local regression suite:
  - `tests/test_runtime_settings.py`
  - `tests/test_drone_config_components.py`
  - `tests/test_coordinator.py`
  - `tests/test_bootstrap_installers.py`
  - result: 134 passed

Hetzner verification:

- synced worktree to:
  - `root@204.168.181.45:/tmp/mds_runtime_arch_phase1_remote/`
- remote shell validation passed for the same four shell entrypoints
- same targeted remote regression suite passed
- result: 134 passed

Live auth audit captured during this slice:

- `CM4-01`
  - `/etc/mds/local.env` points at the public official repo over HTTPS
  - no MDS deploy key is currently present under `/home/droneshow/.ssh`
- Hetzner GCS
  - `/etc/mds/gcs.env` currently says HTTPS + token-file runtime authority
  - live `origin` is still SSH to the Catch-A-Drone repo
  - this is exactly the kind of drift now surfaced by the new status/verify output

Residual drift intentionally deferred to the next slice:

- compatibility markers still remain:
  - `.hwID`
  - `real.mode`
- auth strategy is still operationally mixed:
  - deploy keys
  - token files
  - repo remote transport choices
- long-term GitHub App standardization is still a policy/docs/automation slice, not yet the enforced default implementation

## Slice 7

### Scope

- retire `.hwID` and `real.mode` from the active node bootstrap and SITL launch
  paths
- make the canonical runtime identity/mode explicit in execution paths:
  - `MDS_HW_ID`
  - `MDS_MODE`
  - `/etc/mds/local.env`
  - `/etc/mds/node_identity.json`
- document the intended auth topology for public, private GCS, drones, and
  private SITL

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- updated `tools/mds_init_lib/identity.sh`
  - removed active `.hwID` / `real.mode` creation from node bootstrap
  - existing drone ID discovery now uses canonical sources:
    - `/etc/mds/local.env`
    - `/etc/mds/node_identity.json`
- updated `tools/mds_init_lib/verify.sh`
  - hardware-ID verification now checks canonical sources only
  - runtime-mode verification now warns when `MDS_MODE` is missing instead of
    treating `real.mode` as pass
  - summary reporting no longer depends on `.hwID`
- updated `multiple_sitl/create_dockers.sh`
  - each container now receives `MDS_HW_ID=<drone_id>`
  - removed the per-container runtime-dir mount used only for `.hwID`
- updated `multiple_sitl/startup_sitl.sh`
  - startup now requires canonical `MDS_HW_ID`
  - removed `wait_for_hwid()` from the active path
  - runtime repo cleanup no longer preserves `*.hwID`
- updated `tools/sitl_image_prepare.sh`
  - removed `.hwID` cleanup as a first-class runtime concern
- updated active operator docs:
  - `docs/guides/mds-init-setup.md`
  - `docs/guides/runtime-config-sources.md`
  - `docs/guides/advanced-sitl.md`
  - `docs/guides/sitl-custom-release-workflow.md`
  - `docs/guides/sitl-comprehensive.md`
- updated `docs/features/git-sync.md`
  - documented the intended auth topology:
    - public official via HTTPS/no secret
    - private GCS as the only write-capable runtime
    - drones and disposable SITL as read-only only
- extended bootstrap tests for:
  - canonical verify path without `.hwID`
  - SITL launcher text asserting `MDS_HW_ID` injection and no `.hwID` copy path

Local verification:

- shell validation passed for:
  - `tools/mds_init_lib/identity.sh`
  - `tools/mds_init_lib/verify.sh`
  - `multiple_sitl/startup_sitl.sh`
  - `multiple_sitl/create_dockers.sh`
  - `tools/sitl_image_prepare.sh`
- targeted local regression suite:
  - `tests/test_runtime_settings.py`
  - `tests/test_drone_config_components.py`
  - `tests/test_coordinator.py`
  - `tests/test_bootstrap_installers.py`
  - result: 135 passed

Hetzner verification:

- synced worktree to:
  - `root@204.168.181.45:/tmp/mds_runtime_arch_phase1_remote/`
- remote shell validation passed for the same five shell entrypoints
- same targeted remote regression suite passed
- result: 135 passed

Residual drift intentionally deferred to the next slice:

- Python/runtime helpers still retain compatibility bridges:
  - `MDS_SIM_MODE`
  - `real.mode`
  - `*.hwID`
- several compatibility tests still intentionally cover those bridges
- archived research and historical docs still mention the old markers

## Slice 8

### Scope

- remove the remaining active runtime compatibility bridges from Python and the
  GCS launcher:
  - `MDS_SIM_MODE`
  - `real.mode`
  - `*.hwID`
- update active mission/action entrypoints and operator docs so they describe
  the canonical runtime identity/mode model only
- keep historical/archived references as history, but stop active runtime code
  from honoring the old markers

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- updated `src/settings/runtime.py`
  - `resolve_runtime_mode()` now reads only canonical `MDS_MODE`
  - invalid `MDS_MODE` values now warn and default to `sitl`
  - removed active `MDS_SIM_MODE` and `real.mode` fallback behavior
- updated `src/settings/identity.py`
  - removed active `*.hwID` / `MDS_HWID_DIR` fallback behavior
  - hardware identity now resolves only from:
    - explicit argument
    - `MDS_HW_ID`
    - `/etc/mds/node_identity.json`
- updated `src/params.py`
  - no longer passes a legacy mode-marker path into runtime resolution
- updated the active GCS launcher:
  - `app/linux_dashboard_start.sh`
  - removed `real.mode` sync/reporting from the live launcher path
  - status output now reports canonical runtime mode only
- updated active operator/runtime-facing code comments and descriptions:
  - `src/drone_config/__init__.py`
  - `src/drone_communicator.py`
  - `drone_show_src/utils.py`
  - `actions.py`
  - `smart_swarm.py`
  - `swarm_trajectory_mission.py`
- updated active operator docs/templates:
  - `tools/local.env.template`
  - `docs/guides/config-json-format.md`
  - `docs/guides/runtime-config-sources.md`
- updated regression coverage:
  - removed tests that expected `.hwID` / `real.mode` / `MDS_SIM_MODE`
  - added coverage for canonical default-to-sitl behavior and canonical
    identity missing-state behavior

Local verification:

- shell validation passed for:
  - `app/linux_dashboard_start.sh`
- targeted local regression suite:
  - `tests/test_runtime_settings.py`
  - `tests/test_drone_config_components.py`
  - `tests/test_coordinator.py`
  - `tests/test_bootstrap_installers.py`
- result: 134 passed

Hetzner verification:

- synced worktree to:
  - `root@204.168.181.45:/tmp/mds_runtime_arch_phase1_remote/`
- remote shell validation passed for:
  - `app/linux_dashboard_start.sh`
- same targeted remote regression suite passed
- result: 134 passed

Residual drift intentionally deferred to the next slice:

- archived and research docs still mention retired markers for historical
  context
- compatibility-only helper tooling still exists outside the active runtime
  path (for example legacy SITL rcS patch helpers)
- WiFi manager is still embedded as a mandatory MDS service and is the next
  architectural slice to replace

## Slice 9

### Scope

- replace the embedded in-repo WiFi manager with an optional external
  connectivity backend model based on public `smart-wifi-manager`
- keep core MDS services independent of Wi-Fi management
- preserve git-driven fleet rollout for optional connectivity profiles through a
  clean reconcile hook instead of an embedded service

### Checkpoint Result (2026-04-21)

Status: complete

Implemented:

- extended `deployment/defaults.env` and `tools/load_deployment_profile.sh`
  with canonical connectivity defaults:
  - `MDS_DEFAULT_CONNECTIVITY_BACKEND`
  - `MDS_DEFAULT_SMART_WIFI_MANAGER_*`
- added a new bootstrap/runtime connectivity module:
  - `tools/mds_init_lib/connectivity.sh`
- added a standalone reconcile helper reused by bootstrap, git sync, and
  recovery:
  - `tools/reconcile_connectivity.sh`
- updated `tools/mds_node_init.sh`
  - new connectivity CLI flags
  - new `connectivity` phase inserted before verification
  - Smart Wi-Fi Manager selection is now explicit rather than implied
- updated `tools/mds_init_lib/identity.sh`
  - canonical `MDS_CONNECTIVITY_BACKEND` is now rendered into `/etc/mds/local.env`
  - node identity manifest now records connectivity backend metadata
- updated `tools/mds_init_lib/services.sh`
  - removed embedded `wifi-manager.service` from core `SERVICE_ORDER`
  - core MDS services now rely on `network-online.target`
  - sudoers now authorize optional Smart Wi-Fi Manager reconcile/restart paths
- updated `tools/git_sync_mds/git_sync_mds.service`
  - removed `After=wifi-manager.service`
- updated `tools/update_repo_ssh.sh`
  - removed embedded WiFi-manager service update logic
  - added `check_connectivity_updates()` calling
    `tools/reconcile_connectivity.sh apply`
- updated `tools/recovery.sh`
  - optional Smart Wi-Fi Manager status/log/reset handling
  - removed hardcoded `droneshow` home assumption for network reset paths
- updated `tools/mds_init_lib/verify.sh`
  - new connectivity backend reporting
  - optional Smart Wi-Fi Manager health reporting
  - verification guidance now points operators to the canonical reconcile path
- removed the dead embedded WiFi-manager payload from the repo:
  - `tools/wifi-manager/*`
- added repo-side connectivity profile example:
  - `deployment/connectivity/smart-wifi-manager/profile.example.json`
- updated active docs/templates:
  - `tools/local.env.template`
  - `docs/features/git-sync.md`
  - `docs/guides/runtime-config-sources.md`
  - `docs/guides/mds-init-setup.md`
  - `docs/guides/raspberry-pi-services.md`
  - `docs/guides/led-status-guide.md`
- extended regression coverage for:
  - wrapper help surfacing connectivity flags
  - deployment profile connectivity defaults
  - `setup_local_env()` connectivity rendering
  - connectivity reconcile helper repo-profile application
  - git sync optional connectivity reconciliation
  - service order no longer referencing embedded WiFi-manager

Local verification:

- shell validation passed for:
  - `tools/mds_node_init.sh`
  - `tools/mds_init_lib/connectivity.sh`
  - `tools/reconcile_connectivity.sh`
  - `tools/update_repo_ssh.sh`
  - `tools/recovery.sh`
- targeted local regression suite:
  - `tests/test_bootstrap_installers.py`
  - `tests/test_runtime_settings.py`
  - `tests/test_coordinator.py`
  - `tests/test_drone_config_components.py`
- result: 138 passed

Hetzner verification:

- synced worktree to:
  - `root@204.168.181.45:/tmp/mds_runtime_arch_phase1_remote/`
- remote shell validation passed for the same five shell entrypoints
- remote targeted regression suite passed after creating a temporary isolated
  venv under `/tmp/mds_runtime_arch_phase1_remote/.venv-test/`
- result: 138 passed

Residual drift intentionally deferred to the next slice:

- official worktree still contains the broader runtime-architecture migration
  as one uncommitted checkpoint and must be committed/pushed before private sync
- the private/client repo still needs the official generic connectivity/runtime
  convergence applied cleanly
- Arnaud hardware workflow still needs the downstream official->private sync
  before real-node 0-100 bootstrap/enrollment validation resumes

## Slice 10

Goal:

- make Smart Wi-Fi Manager lifecycle management truly repo-driven by moving the
  external tool install/update path into `tools/reconcile_connectivity.sh`
- keep `deployment/defaults.env` authoritative for the fleet-wide Smart Wi-Fi
  Manager repo/ref channel
- avoid freezing nodes on copied defaults inside `/etc/mds/local.env`

Implemented:

- updated deployment defaults and loader:
  - added `MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS`
  - bumped default Smart Wi-Fi Manager ref to `v2.1.0`
- updated `tools/mds_init_lib/connectivity.sh`
  - removed one-time bootstrap clone/install logic
  - added support for optional host-local `MDS_SMART_WIFI_MANAGER_REPO_URL`
    and `MDS_SMART_WIFI_MANAGER_REF` overrides
  - fixed local-env persistence so repo/ref defaults remain repo-owned unless a
    host explicitly overrides them
- updated `tools/reconcile_connectivity.sh`
  - now sources `tools/load_deployment_profile.sh`
  - resolves effective Smart Wi-Fi Manager repo URL/ref
  - ensures the external runtime checkout matches the desired ref
  - runs `install.sh` with the matching `--dashboard-version`
  - includes repo/ref in the connectivity state hash
  - reports repo/ref in `status`
- updated node identity reporting:
  - `tools/mds_init_lib/identity.sh` now records Smart Wi-Fi Manager repo URL
    and ref when present as host-local overrides
- updated active docs/templates:
  - `deployment/defaults.env`
  - `tools/load_deployment_profile.sh`
  - `tools/local.env.template`
  - `docs/guides/runtime-config-sources.md`
  - `docs/features/git-sync.md`
- extended regression coverage for:
  - deployment loader exporting Smart Wi-Fi Manager repo URL defaults
  - reconcile helper installing/configuring against deployment-profile repo/ref
  - local-env persistence keeping repo/ref in the defaults layer unless
    explicitly overridden

Local verification:

- shell validation passed for:
  - `tools/mds_init_lib/connectivity.sh`
  - `tools/reconcile_connectivity.sh`
  - `tools/load_deployment_profile.sh`
- targeted local regression suite:
  - `tests/test_bootstrap_installers.py`
  - `tests/test_runtime_settings.py`
  - `tests/test_coordinator.py`
  - `tests/test_drone_config_components.py`
- result: 139 passed

Hetzner verification:

- synced worktree to:
  - `root@204.168.181.45:/tmp/mds_runtime_arch_phase1_remote/`
- remote shell validation passed for the same shell entrypoints
- recreated a temporary isolated venv under:
  - `/tmp/mds_runtime_arch_phase1_remote/.venv-test/`
- remote targeted regression suite passed
- result: 139 passed

Residual drift after this slice:

- official repo still needs this slice committed and pushed
- private repo still needs the clean official convergence applied and verified
- hardware/bootstrap validation should resume only after that convergence

## Slice 11

Goal:

- make private GitHub SSH auth a first-class runtime/bootstrap configuration for
  both GCS and companion nodes
- remove the last hardcoded bootstrap assumption that only one legacy SSH key
  path exists for GCS or node provisioning
- keep runtime git-sync, bootstrap wrappers, and rendered env files aligned

Implemented:

- updated GCS bootstrap/init flow:
  - `tools/install_gcs.sh` now accepts `--git-ssh-key-file`
  - `tools/mds_gcs_init.sh` now accepts and exports
    `--git-ssh-key-file`
  - `tools/mds_gcs_init_lib/gcs_repo.sh` now resolves the SSH key path from
    `MDS_GIT_SSH_KEY_FILE` and only generates the default managed key when no
    explicit key file was supplied
  - `tools/mds_gcs_init_lib/gcs_env_config.sh` now persists
    `MDS_GIT_SSH_KEY_FILE` into `/etc/mds/gcs.env`
- updated companion-node bootstrap/init flow:
  - `tools/install_mds_node.sh` now accepts `--git-ssh-key-file`
  - `tools/mds_node_init.sh` now accepts and exports
    `--git-ssh-key-file`
  - `tools/mds_init_lib/repo.sh` now resolves the SSH key path from
    `MDS_GIT_SSH_KEY_FILE` and only generates the default managed key when no
    explicit key file was supplied
  - `tools/mds_init_lib/identity.sh` now persists `MDS_GIT_SSH_KEY_FILE` into
    `/etc/mds/local.env`
- tightened direct-init GCS behavior:
  - non-interactive SSH bootstrap no longer silently flips to HTTPS when the
    SSH key is missing or unauthorized; it now fails with a clear remediation
    path
- updated operator docs:
  - `docs/guides/gcs-setup.md`
  - `docs/guides/mds-init-setup.md`
- extended regression coverage for:
  - wrapper help text advertising `--git-ssh-key-file`
  - wrapper/runtime git commands honoring the configured SSH key file
  - GCS env persistence of `MDS_GIT_SSH_KEY_FILE`
  - node local-env persistence of `MDS_GIT_SSH_KEY_FILE`

Local verification:

- shell validation passed for:
  - `tools/install_gcs.sh`
  - `tools/mds_gcs_init.sh`
  - `tools/mds_gcs_init_lib/gcs_repo.sh`
  - `tools/mds_gcs_init_lib/gcs_env_config.sh`
  - `tools/install_mds_node.sh`
  - `tools/mds_node_init.sh`
  - `tools/mds_init_lib/repo.sh`
  - `tools/mds_init_lib/identity.sh`
- targeted local regression suite:
  - `tests/test_bootstrap_installers.py`
  - `tests/test_runtime_settings.py`
  - `tests/test_coordinator.py`
  - `tests/test_drone_config_components.py`
- result: 146 passed

Hetzner verification:

- synced worktree to:
  - `root@204.168.181.45:/tmp/mds_runtime_arch_phase1_remote/`
- remote shell validation passed for the same shell entrypoints
- recreated the temporary isolated venv under:
  - `/tmp/mds_runtime_arch_phase1_remote/.venv-test/`
- remote targeted regression suite passed
- result: 146 passed

Residual drift after this slice:

- official repo still needs this slice committed and pushed
- private repo still needs the clean official convergence applied and verified
- the clean private GCS bootstrap on Hetzner still needs to be retried with the
  existing working SSH key file

## Slice 12

Goal:

- unblock the live private GCS launcher after the clean Hetzner bootstrap
- remove the last dangling call to the retired `real.mode` compatibility-marker
  helper from the active launcher path

Implemented:

- updated `app/linux_dashboard_start.sh`
  - removed the stale `sync_runtime_compatibility_marker` call
  - kept canonical runtime mode ownership on `MDS_MODE` plus
    `/etc/mds/gcs.env`
- extended regression coverage:
  - `tests/test_bootstrap_installers.py` now asserts the launcher no longer
    references `sync_runtime_compatibility_marker`

Verification:

- local shell validation and targeted bootstrap/runtime suite rerun after the
  change
- follow-up live proof target:
  - restart the private Hetzner GCS successfully in `--real --prod` mode

Residual drift after this slice:

- official/private repos still need this tiny launcher fix committed and pushed
- Hetzner `/opt/mds` still needs a repo refresh before the live GCS can start

## Slice 13

Goal:

- unblock private HTTPS bootstrap/runtime sync on real boards where `/tmp`
  cannot execute the generated Git askpass helper
- keep the credential model file-based and non-interactive without falling back
  to broad write credentials on nodes

Implemented:

- updated bootstrap/runtime Git askpass helpers to use per-user cache/runtime
  paths instead of `/tmp`
  - `tools/install_mds_node.sh`
  - `tools/mds_init_lib/repo.sh`
  - `tools/install_gcs.sh`
  - `tools/mds_gcs_init_lib/gcs_repo.sh`
  - `tools/update_repo_ssh.sh`
  - `tools/mds_git_access_check.sh`
- adjusted bootstrap regression coverage to assert the new
  `.cache/mds-runtime` helper paths instead of `/tmp`

Verification:

- shell validation passed for every changed script
- targeted bootstrap/runtime auth regression suite passed:
  - `tests/test_bootstrap_installers.py` → 52 passed
  - `tests/test_mds_git_access_check.py` → 3 passed
- live proof target after commit:
  - rerun private-token bootstrap on `CM4-02`

Residual drift after this slice:

- official/private repos still need this askpass-path fix committed and pushed
- `CM4-02` private bootstrap must be retried against the new code
- the temporary read-only token used for this validation should be rotated after
  the test because it was pasted into chat

## Slice 14

Goal:

- consolidate the operator/agent explanation of fleet desired state versus
  host-local runtime versus secrets
- remove ambiguity around how large fleets should sync normal config without
  re-touching node credentials
- make the bootstrap/auth/runbook docs point to one canonical guidance layer

Implemented:

- added canonical guide:
  - `docs/guides/fleet-sync-and-secrets.md`
- updated cross-links and operator guidance in:
  - `docs/README.md`
  - `docs/guides/runtime-config-sources.md`
  - `docs/features/git-sync.md`
  - `docs/guides/custom-repo-workflow.md`
  - `docs/guides/headless-automation.md`
- updated headless automation examples so they:
  - prefer `mds_node_init.sh` over ad hoc pre-bootstrap git reset flows
  - show local token-file usage for private repo nodes
  - call out structured `--report-json` / `--announce-report-json` for
    automation and AI-agent use

Verification:

- manual doc review against current runtime/auth implementation completed
- link-path grep verified the new canonical guide is referenced from the main
  entry points above

Residual drift after this slice:

- official/private repos still need this doc-only slice committed and pushed
- Smart Wi-Fi Manager fleet-profile integration is still a planned next slice,
  not a live Arnaud-board capability yet
- hardware convergence remains blocked on private token approval from the
  Catch-A-Drone org

## Slice 15

Goal:

- expose the cleaned runtime/config ownership directly in the GCS so operators
  can see the active mode, repo/profile defaults, and runtime docs without
  guessing from scripts alone
- make the runtime state visible to future UI/admin slices without re-reading
  bootstrap files manually

Implemented:

- added backend runtime status route:
  - `GET /api/v1/system/runtime-status`
- added response schemas for runtime docs, fleet defaults, and runtime status
- surfaced deployment-profile connectivity and MAVLink defaults in the runtime
  status payload
- added the frontend Runtime Admin page and sidebar mode pill so the current
  host mode is always visible in the dashboard
- corrected route inventory docs/tests to match the live SITL and swarm-state
  API surface

Verification:

- official/private backend verification passed for the runtime-admin slice:
  - `183 passed`

Residual drift after this slice:

- runtime control actions (self-update, mode switch, tool profile rollout) are
  still planned follow-on slices
- git-sync still needed post-pull safety rails so a bad runtime revision could
  be fetched successfully even though later reconcile would fail

## Slice 16

Goal:

- prevent a pulled runtime revision from partially applying broken shell,
  Python, or rendered systemd changes to a node
- keep nodes on the last known-good runtime when a bad commit reaches the sync
  path

Implemented:

- added post-sync validation helpers in `tools/update_repo_ssh.sh` for:
  - changed runtime shell helpers (`bash -n`)
  - changed runtime Python files (`python3 -m py_compile`)
  - changed rendered node unit templates (`systemd-analyze verify` when
    available)
- added rollback to the previous repo revision when post-sync validation fails
- kept rollback failures non-destructive:
  - successful rollback now reports a structured sync failure while leaving the
    LED in `GIT_FAILED_CONTINUING`
  - hard-fault escalation is reserved for rollback failure or other truly fatal
    exits
- documented the new post-sync validation/rollback behavior in
  `docs/features/git-sync.md`
- added regression coverage for:
  - invalid changed shell helper
  - invalid changed Python runtime file
  - invalid rendered service template
  - non-critical rollback failure-result semantics

Verification:

- shell validation passed:
  - `bash -n tools/update_repo_ssh.sh`
- targeted bootstrap/runtime regression coverage passed:
  - `tests/test_bootstrap_installers.py -k "post_sync_validation or exit_with_failure_result or runtime_git_sync_reconciles_managed_mavlink_runtime"`
- full official runtime/backend verification passed:
  - `tests/test_bootstrap_installers.py`
  - `tests/test_git_sync.py`
  - `tests/test_runtime_settings.py`
  - `tests/test_gcs_management_routes.py`
  - `tests/test_gcs_api_http.py`
  - `tests/test_api_route_inventory.py`
  - total: `187 passed`

Residual drift after this slice:

- private repo still needs the same verified guardrail slice cherry-picked and
  re-verified
- runtime control plane work (self-update, explicit mode switch, external tool
  profile orchestration) remains the next planned implementation area

## Slice 17

Goal:

- extend Runtime Admin beyond raw repo/mode posture so operators can see the
  actual local runtime health for git auth, managed mavlink-anywhere, and
  Smart Wi-Fi Manager before mutation controls are added

Implemented:

- expanded deployment-profile parsing to include the Smart Wi-Fi Manager default
  mode, import mode, install dir, dashboard listen address, and profile path
- extended `GET /api/v1/system/runtime-status` with:
  - resolved git auth health summary/issues
  - managed mavlink-anywhere runtime status
  - connectivity backend runtime status
- reused the existing reconcile status helpers as the runtime-admin status
  source instead of inventing a second parallel source of truth
- updated Runtime Admin frontend state/page contract so the operator view can
  surface:
  - auth health summary/issues
  - live mavlink-anywhere runtime/service posture
  - live Smart Wi-Fi Manager runtime/service posture
  - repo links for the external tool runtimes
- added/updated backend tests for the richer runtime-status payload

Verification:

- official backend/runtime verification passed:
  - `tests/test_bootstrap_installers.py`
  - `tests/test_git_sync.py`
  - `tests/test_runtime_settings.py`
  - `tests/test_gcs_management_routes.py`
  - `tests/test_gcs_api_http.py`
  - `tests/test_api_route_inventory.py`
  - total: `187 passed`

Residual drift after this slice:

- private repo still needs the same runtime-tool-status slice cherry-picked and
  re-verified
- frontend tests for the Runtime Admin UI updates remain deferred to the
  frontend-capable environment because Node installs are intentionally avoided
  on this host
- runtime mutation controls (self-update, explicit mode switch, controlled
  external tool profile rollout) remain the next implementation area

## Slice 18

Goal:

- harden post-sync unit-file application so node service updates remain safe
  even when `daemon-reload` or enablement refresh fails

Implemented:

- made the post-sync service update path respect `MDS_SYSTEMD_DIR` so it can be
  exercised safely in isolated test environments
- staged rollback backups for changed rendered unit files before replacing the
  installed node units
- refreshed enablement links only for units that were already enabled before a
  successful unit update
- restored the previous unit files automatically when `systemctl daemon-reload`
  failed after staged replacement
- documented the refined service-update semantics in `docs/features/git-sync.md`
- added backend/bootstrap tests covering:
  - enablement refresh after a successful unit update
  - rollback to previous unit files after a `daemon-reload` failure

Verification:

- official backend/runtime verification passed:
  - `tests/test_bootstrap_installers.py`
  - `tests/test_git_sync.py`
  - `tests/test_runtime_settings.py`
  - `tests/test_gcs_management_routes.py`
  - `tests/test_gcs_api_http.py`
  - `tests/test_api_route_inventory.py`

Residual drift after this slice:

- private repo still needs the same post-sync unit-rollback slice cherry-picked
  and re-verified
- runtime mutation controls (self-update, explicit mode switch, controlled
  external tool profile rollout) remain the next implementation area

## Slice 19

Goal:

- replace the old `PUT /api/v1/system/gcs-config` persistence stub with a safe
  host-local write path for the canonical GCS runtime mode surface

Implemented:

- added safe `gcs-config` persistence for the narrow host-local subset only:
  - `mode` / `sim_mode` -> `MDS_MODE`
  - `git_auto_push` -> `MDS_GIT_AUTO_PUSH`
- made the route update `/etc/mds/gcs.env` atomically instead of pretending a
  save occurred without writing anything
- added explicit operator warnings for unsupported fields such as `gcs_port`
  and `acceptable_deviation` so host-local config mutation does not quietly
  turn into a second conflicting fleet-config path
- extended `GET /api/v1/system/gcs-config` and
  `GET /api/v1/system/runtime-status` to report:
  - running mode
  - configured mode
  - configured git auto-push state
  - whether a restart is required because the running process differs from the
    persisted host config
- updated API/changelog docs to match the new truthful contract

Verification:

- official backend/runtime verification passed:
  - `tests/test_bootstrap_installers.py`
  - `tests/test_git_sync.py`
  - `tests/test_runtime_settings.py`
  - `tests/test_gcs_management_routes.py`
  - `tests/test_gcs_api_http.py`
  - `tests/test_api_route_inventory.py`

Residual drift after this slice:

- private repo still needs the same host-local `gcs-config` persistence slice
  cherry-picked and re-verified
- Runtime Admin still needs the actual mutation UX layered on top of the now
  truthful backend persistence surface
- controlled restart/apply semantics for full GCS self-update remain a later
  slice; this slice only persists config and reports restart-required status

## Slice 20

Goal:

- close the mixed SITL/REAL contamination gap by fencing heartbeats on declared
  runtime mode and add explicit Runtime Admin apply/restart semantics on top of
  the host-local `gcs-config` persistence surface

Implemented:

- made nodes send canonical `runtime_mode` on heartbeat so GCS does not need to
  infer SITL/REAL posture from IPs, ports, or container naming
- updated heartbeat intake so GCS:
  - normalizes common runtime-mode aliases
  - rejects heartbeats whose declared mode does not match the active GCS mode
  - stores accepted `runtime_mode` values in heartbeat/network snapshots
  - still accepts legacy nodes with no `runtime_mode`, while warning that mixed
    mode protection remains weaker until those nodes are updated
- added `POST /api/v1/system/gcs-config/apply` as the explicit host-local apply
  path:
  - compares running vs configured mode / git auto-push posture
  - schedules a controlled relaunch through the canonical launcher only when
    drift exists
  - debounces repeated restart requests
  - warns when SITL instances are still running during a switch back to real
    mode
- replaced the old read-only Runtime Admin page with actual host-local mutation
  controls for:
  - mode switch
  - git auto-push switch
  - save host-local config
  - apply controlled restart
- updated API/operator docs so Runtime Admin, heartbeat mode fencing, and the
  operator restart semantics are documented from the same source of truth

Verification:

- official backend/runtime verification passed:
  - `tests/test_heartbeat_runtime_mode.py`
  - `tests/test_gcs_management_routes.py`
  - `tests/test_gcs_api_http.py`
  - `tests/test_api_route_inventory.py`
- frontend unit tests for the new Runtime Admin controls were added, but local
  execution remains deferred on this host because the clean worktree does not
  have dashboard dependencies installed and the current checkpoint intentionally
  avoids introducing a fresh Node install on this machine

Residual drift after this slice:

- Mission Config drone cards still infer displayed runtime posture from local
  serial/network heuristics instead of using the same declared `runtime_mode`
  that the backend heartbeat fence now trusts

## Slice 21

Goal:

- make the operator-facing drone cards show the same runtime-mode truth that
  the backend now enforces, so mixed SITL/REAL posture is not corrected in the
  backend but still misrepresented in the UI

Implemented:

- added runtime-mode normalization to Mission Config drone cards so common node
  aliases such as `hardware`, `production`, `sim`, and `simulation` collapse
  into canonical `real|sitl`
- made the runtime badge prefer `heartbeatData.runtime_mode` over legacy local
  inference, while still falling back safely for older nodes that do not yet
  declare mode
- changed the badge wording from ambiguous `Hardware` to explicit `REAL`
- updated the link/runtime inspector so the detailed runtime row reflects the
  same effective mode and indicates whether that posture was declared by the
  node heartbeat or inferred locally
- added focused frontend regression coverage so a SITL-shaped local profile
  with a heartbeat-declared `real` mode renders as REAL instead of silently
  drifting back to the old inferred label

Verification:

- static clean-worktree review of:
  - `app/dashboard/drone-dashboard/src/components/DroneConfigCard.js`
  - `app/dashboard/drone-dashboard/src/components/DroneConfigCard.test.js`
- frontend execution remains deferred on this host because neither the clean
  worktree nor the root checkout currently has dashboard dependencies
  installed, and this checkpoint continues to avoid a fresh Node install on
  the current machine

Residual drift after this slice:

- Runtime Admin and the wider dashboard still need stronger always-visible mode
  affordances beyond Mission Config cards
- frontend verification for this slice still needs to be rerun on the
  designated host with dashboard dependencies available

## Slice 22

Goal:

- make current GCS runtime posture visible at the shell level, not only inside
  Runtime Admin or Mission Config, so operators can still see REAL/SITL status
  when the sidebar is collapsed or mobile navigation is closed

Implemented:

- added a shared `RuntimeModeBadge` component for shell/runtime surfaces
- replaced the old expanded-sidebar-only mode pill with the shared badge
- made the collapsed desktop sidebar keep a compact REAL/SITL badge visible
  beneath the shell icon
- added a matching mobile shell badge beside the navigation toggle so current
  runtime posture stays visible even when the sidebar drawer is closed
- surfaced restart-required drift in the shell badge itself instead of keeping
  that warning exclusive to Runtime Admin
- added focused sidebar regression coverage for expanded and collapsed shell
  rendering

Verification:

- static clean-worktree review of:
  - `app/dashboard/drone-dashboard/src/App.js`
  - `app/dashboard/drone-dashboard/src/App.css`
  - `app/dashboard/drone-dashboard/src/components/SidebarMenu.js`
  - `app/dashboard/drone-dashboard/src/components/RuntimeModeBadge.js`
  - `app/dashboard/drone-dashboard/src/components/SidebarMenu.test.js`
  - `app/dashboard/drone-dashboard/src/styles/SidebarMenu.css`
  - `app/dashboard/drone-dashboard/src/styles/RuntimeModeBadge.css`
- clean-worktree `git diff --check`: passed
- frontend execution remains deferred on this host because dashboard
  dependencies are still not installed locally

Residual drift after this slice:

- mobile shell badge integration is covered by static review, but full browser
  execution still needs to be rerun on the designated dashboard-validation host
- other views can still benefit from stronger mode-context cues, but the shell
  layer now keeps current posture visible without opening Runtime Admin

## Slice 23

Goal:

- lock the git-sync post-update service contract down with focused tests and
  operator-facing wording, so future runtime changes do not quietly regress
  into blanket restarts or accidental dormant-service activation

Implemented:

- added focused shell regression coverage for:
  - `git_sync_mds.service` unit updates reloading and re-enabling safely
    without trying to restart the currently running sync job
  - coordinator restart scheduling when a post-sync runtime restart is needed
    and the coordinator is active
  - leaving the coordinator intentionally stopped when it is inactive at the
    moment post-sync reconcile runs
- tightened `tools/local.env.template` wording to use the canonical
  `coordinator.service` unit name
- expanded `docs/features/git-sync.md` so it now states explicitly that:
  - inactive coordinator runtimes stay stopped after sync
  - `git_sync_mds.service` unit updates apply on the next invocation instead of
    self-restarting from inside the running sync
  - external `smart-wifi-manager` and `mavlink-anywhere` ownership is versioned
    through deployment/defaults plus local env overrides and reconciled by
    dedicated helpers rather than treated as MDS submodules

Verification:

- focused shell/bootstrap verification passed:
  - `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "git_sync_service_unit_updates_do_not_restart_running_sync or post_sync_runtime_restart_schedules_coordinator_when_active or post_sync_runtime_restart_keeps_inactive_coordinator_stopped"`

Residual drift after this slice:

- broader service/bootstrap policy is now clearer, but GCS self-update and
  optional sidecar fleet-control UX are still later slices
- frontend/dashboard presentation for node-local sidecar policy remains a
  separate runtime-admin/fleet-ops slice

- private repo still needs the same heartbeat-fencing / Runtime Admin apply
  slice mirrored and re-verified
- full self-update UX remains a later slice; this one covers host-local apply
  for mode and git auto-push only
- once every node runtime is updated to declare `runtime_mode`, mixed-mode
  protection will be fully explicit instead of partially compatibility-backed

## Slice 24

Goal:

- surface node git auth posture directly in the existing fleet git-status
  contract so operators can see whether a node is likely to sync successfully
  without exposing token/key file paths or inventing a second node-management
  endpoint

Implemented:

- extended `functions/git_manager.get_local_git_report()` so node git status
  now classifies:
  - repo access mode (`ssh_key`, `https_token_file`,
    `https_public_or_read_only`, `custom_or_unknown`)
  - auth health status / summary / issues for read-only sync posture
- kept the node contract path-based only internally:
  - token/key readability still influences health
  - local secret file paths are not emitted in fleet-facing payloads
- extended drone API git-status responses and GCS git-status aggregation
  schemas/routes to pass the new auth posture fields through end-to-end
- updated the dashboard git card so expanded details now show:
  - access mode
  - auth summary
  - auth issues when present
- added a visible auth warning banner on git cards when node auth posture is
  warning/error instead of hiding that state only inside raw API payloads
- added focused backend regression coverage for:
  - healthy HTTPS token-file node access
  - broken SSH-key node access
  - drone API exposure of the new fields
  - GCS git-status passthrough of node auth posture

Verification:

- focused backend verification passed:
  - `python3 -m pytest --no-cov tests/test_git_manager.py -k "get_local_git_report"`
  - `python3 -m pytest --no-cov tests/test_drone_api_http.py -k "test_get_git_status"`
  - `python3 -m pytest --no-cov tests/test_gcs_api_http.py -k "test_get_git_status"`

Residual drift after this slice:

- frontend execution for the updated git card remains deferred on this host
  until dashboard dependencies are restored on the designated validation host
- auth posture is now visible per node, but fleet-wide auth remediation and
  Runtime Admin self-update/apply controls remain later slices

## Slice 25

Goal:

- make the SITL-to-REAL mode-switch edge case explicit before restart by
  surfacing local SITL inventory in runtime status and warning operators that
  those containers are fenced, not auto-stopped, after a REAL restart

Implemented:

- extended `/api/v1/system/gcs-config` and `/api/v1/system/runtime-status` with
  `sitl_instance_count`
- reused the existing SITL control inventory path so Runtime Admin no longer
  has to wait for the apply call to reveal that local SITL containers still
  exist
- updated Runtime Admin to:
  - show the detected local SITL container count in Runtime Controls
  - raise a pre-restart warning banner when the effective configured mode is
    REAL and local SITL containers are still present
  - give operators a direct link to `SITL Control`
  - keep the operational notes explicit that REAL mode does not auto-stop local
    SITL containers
- added focused backend regression coverage for:
  - config/runtime status exposure of SITL inventory
  - restart/apply semantics staying intact with the new field
- added focused frontend test coverage for the warning path, pending execution
  on the designated dashboard-validation host

Verification:

- focused backend verification passed:
  - `python3 -m pytest --no-cov tests/test_gcs_management_routes.py -k "gcs_config or runtime_status"`
  - `python3 -m pytest --no-cov tests/test_gcs_api_http.py -k "test_get_gcs_config or test_get_runtime_status or test_apply_gcs_config_schedules_restart"`
- clean-worktree `git diff --check`: passed
- frontend Runtime Admin changes were statically reviewed in:
  - `app/dashboard/drone-dashboard/src/hooks/useGcsRuntimeStatus.js`
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.js`
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.test.js`
  - `app/dashboard/drone-dashboard/src/styles/RuntimeAdminPage.css`

Residual drift after this slice:

- Runtime Admin now warns about local SITL leftovers, but full self-update UX
  and central sidecar fleet-control remain later slices
- frontend execution for the new Runtime Admin warning path still needs to run
  on the designated dashboard-validation host once dependencies are restored

## Slice 26

Goal:

- give operators a direct GCS-local inspection path into managed sidecars from
  Runtime Admin without pretending MDS already has a full fleet-wide sidecar
  control plane

Implemented:

- added a small frontend helper that derives browser-safe GCS-local dashboard
  URLs from configured listen addresses such as `0.0.0.0:9070`
- updated Runtime Admin so the GCS-local `mavlink-anywhere` and Smart Wi-Fi
  cards now expose:
  - repo link
  - service status pills
  - direct `Open local dashboard` entry points when a dashboard listen address
    is present
- made the operator boundary explicit in the page copy:
  - these links are GCS-local only
  - node-local sidecar dashboards are not centrally proxied yet
  - node-side overrides still belong to bootstrap/defaults plus node-local
    runtime env until a later fleet-control slice exists
- extended Runtime Admin frontend tests to cover local dashboard link rendering

Verification:

- clean-worktree `git diff --check`: passed
- frontend changes were statically reviewed in:
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.js`
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.test.js`

Residual drift after this slice:

- local dashboard entry points now exist for the GCS host, but node-side
  sidecar control/profile rollout remains a later fleet-control slice
- frontend execution for this slice still needs the designated
  dashboard-validation host because dependencies are not installed locally here

## Slice 27

Goal:

- turn the raw GCS git report into an explicit update-readiness contract for
  Runtime Admin so operators can see whether a safe fast-forward update is even
  possible before any self-update mutation path is exposed

Implemented:

- added a typed `repo_sync_status` block to Runtime Admin status with:
  - current branch / commit / tracking branch / remote
  - ahead / behind counts
  - working tree status
  - resolved update posture (`up_to_date`, `ready_to_fast_forward`,
    `blocked_dirty`, `divergent`, `local_ahead`, `no_tracking_branch`)
  - operator-facing summary
  - `fast_forward_update_available`
- updated Runtime Admin to show:
  - repo sync state
  - tracking branch
  - update summary
  - an explicit note when a controlled fast-forward update is available but the
    mutation UX is still intentionally deferred
- extended Runtime Admin frontend tests to cover the new summary path

Verification:

- focused backend verification passed:
  - `python3 -m pytest --no-cov tests/test_gcs_management_routes.py -k "runtime_status"`
  - `python3 -m pytest --no-cov tests/test_gcs_api_http.py -k "test_get_runtime_status"`
- clean-worktree `git diff --check`: passed
- frontend changes were statically reviewed in:
  - `app/dashboard/drone-dashboard/src/hooks/useGcsRuntimeStatus.js`
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.js`
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.test.js`

Residual drift after this slice:

- operators can now see update readiness clearly, but no GCS self-update
  mutation endpoint/button exists yet
- the next step is to audit whether the existing repo-update tooling can be
  safely reused as a fast-forward-only GCS self-update path with restart
  protection

## Slice 28

Goal:

- add a constrained, restart-safe GCS self-update path without turning Runtime
  Admin into a generic repo mutation surface

Implemented:

- added a canonical `POST /api/v1/system/runtime-update` route for the GCS host
- added a dedicated `tools/gcs_fast_forward_update.sh` helper instead of
  reusing the broader node-oriented `update_repo_ssh.sh`
- made the backend fetch and re-evaluate repo sync posture before every update
  decision
- blocked the self-update path when:
  - the GCS already has unapplied host-local runtime changes
  - the checkout is dirty / ahead / divergent / missing an upstream
  - the fetched diff touches blocked surfaces such as:
    - `app/`
    - `tools/`
    - dependency manifests like `package.json`, `requirements*.txt`,
      `pyproject.toml`
- updated Runtime Admin to expose:
  - an `Update GCS` action
  - explicit hint text describing the narrow allowed update scope
  - success/error notices from the new update route
- updated operator docs so `gcs-setup.md` now explains the constrained update
  contract and the cases that still require manual update handling

Verification:

- focused backend verification passed:
  - `python3 -m pytest --no-cov tests/test_gcs_management_routes.py -k "runtime_update or gcs_config or runtime_status"`
  - `python3 -m pytest --no-cov tests/test_gcs_api_http.py -k "runtime_update or gcs_config or runtime_status"`
  - `python3 -m pytest --no-cov tests/test_api_route_inventory.py -k "gcs"`
- shell syntax verification passed:
  - `bash -n tools/gcs_fast_forward_update.sh`
- clean-worktree `git diff --check`: passed
- frontend changes were statically reviewed in:
  - `app/dashboard/drone-dashboard/src/services/gcsApiService.js`
  - `app/dashboard/drone-dashboard/src/services/gcsApiService.test.js`
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.js`
  - `app/dashboard/drone-dashboard/src/pages/RuntimeAdminPage.test.js`
  - `app/dashboard/drone-dashboard/src/styles/RuntimeAdminPage.css`

Residual drift after this slice:

- the GCS self-update path is intentionally limited to runtime-safe
  fast-forward updates; dependency/frontend/launcher changes still require the
  manual path
- a future slice can broaden update automation only after dependency and
  frontend rebuild/restart semantics are explicitly versioned and reconciled
- 2026-04-23: Surfaced runtime posture in the shared dashboard chrome. Sidebar/mobile header now expose running mode, configured-mode drift, and restart-pending cues without requiring operators to open Runtime Admin first.
- 2026-04-23: Hardened node post-sync service reconcile handling. Git sync state now records unit reload outcomes and deferred apply actions, and fatal service reconcile failures abort the sync flow instead of continuing silently.

## Slice 31

Goal:

- fix live git-sync unit self-update validation so rendered `*.service` files
  can be verified and applied during post-sync reconcile instead of being
  skipped with a false invalid-unit error

Implemented:

- changed post-sync rendered-unit temp file allocation to use a `.service`
  suffix before running `systemd-analyze verify`
- added a focused regression test that proves the validator receives a
  `*.service` path, matching the live failure mode seen during board and GCS
  self-update

Verification:

- `bash -n tools/update_repo_ssh.sh`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "git_sync_service_template_validation_uses_service_suffix or git_sync_service_template_omits_no_new_privileges or post_sync_runtime_restart or git_sync_runtime_state_persists_post_sync_summary"`

Residual drift after this slice:

- live GCS and both boards still need one more reconcile pass so the repaired
  git-sync unit update path actually lands on the running systems
- after that live apply, the remaining work returns to the planned runtime
  admin and fleet sidecar control slices rather than bootstrap repair

## Slice 32

Goal:

- remove the remaining config-authority split where `git_sync_mds.service`
  still behaved like a node-only runtime path even on the GCS host

Implemented:

- added `/etc/mds/gcs.env` as a first-class git-sync runtime env source
- updated `git_sync_mds.service` to load:
  - `/etc/mds/gcs.env`
  - `/etc/mds/local.env`
  - `$HOME/.config/mds/env`
- updated `update_repo_ssh.sh` to preload those env files in the same order,
  so GCS and node invocations follow one host-aware precedence model
- added regression coverage for:
  - service template env ordering
  - runtime env precedence (`gcs.env -> local.env -> user env`)
- corrected GCS/custom-repo docs so they no longer imply boot-time git sync is
  driven only by node-style `local.env`

Verification:

- `bash -n tools/update_repo_ssh.sh`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "git_sync_service_template or git_sync_runtime_env_prefers_local_over_gcs_and_user_env or post_sync_runtime_restart or git_sync_runtime_state_persists_post_sync_summary"`
- `git diff --check`

Residual drift after this slice:

- live GCS still needs one reconciliation pass from the repaired code path so
  its boot-time git sync stops depending on stale host-local env leftovers
- board-side live reconciliation remains blocked on NetBird reachability, not
  on the code path anymore

## Slice 33

Goal:

- finish the GCS git-sync source-of-truth repair by recomputing derived runtime
  paths after env files are loaded, so `MDS_INSTALL_DIR` actually drives
  `REPO_DIR` and sidecar/script paths on live hosts

Implemented:

- added `refresh_derived_runtime_paths()` to `tools/update_repo_ssh.sh`
- after env preload, git sync now recomputes:
  - `REPO_DIR`
  - `LED_CMD`
  - `LOG_FILE`
  - `LOCK_FILE`
  - `USER_ENV_FILE`
  - `GIT_SYNC_STATE_DIR`
  - `GIT_SYNC_STATE_FILE`
- extended the runtime env precedence regression test to prove a GCS-supplied
  `MDS_INSTALL_DIR` updates the effective repo and sidecar paths

Verification:

- `bash -n tools/update_repo_ssh.sh`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "git_sync_runtime_env_prefers_local_over_gcs_and_user_env or git_sync_service_template or post_sync_runtime_restart or git_sync_runtime_state_persists_post_sync_summary"`
- `git diff --check`

Residual drift after this slice:

- live GCS still needs one more post-publish reconcile pass so the repaired
  path derivation actually lands on the running host
- board-side live reconciliation remains blocked on NetBird reachability, not
  on this runtime-path logic

## Slice 34

Goal:

- make fresh GCS bootstrap install/reconcile `git_sync_mds.service`
  automatically so `/etc/mds/gcs.env` becomes usable self-update authority
  without a manual follow-up repair

Implemented:

- added `tools/mds_gcs_init_lib/gcs_services.sh`
- inserted `services` into `GCS_PHASES` between `env_config` and `verify`
- added `--skip-services` to `tools/mds_gcs_init.sh`
- wired the new phase to run `tools/git_sync_mds/install_git_sync_mds.sh`
  against the configured install dir with an explicit runtime user/home
- extended GCS verify output to report `git_sync_mds.service` enabled/active
  state
- updated GCS/runtime-config docs to state that service reconcile is part of
  canonical bootstrap

Verification:

- `bash -n tools/mds_gcs_init.sh`
- `bash -n tools/mds_gcs_init_lib/gcs_services.sh`
- `bash -n tools/mds_gcs_init_lib/gcs_verify.sh`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "gcs_common_phase_list_includes_services_before_verify or gcs_init_help_mentions_services_phase_and_skip_flag or run_gcs_services_phase_installs_git_sync_service_with_runtime_paths or verify_gcs_git_sync_service_reports_enabled_and_active"`

Residual drift after this slice:

- live Hetzner GCS still needs one final `main-candidate` fast-forward so the
  new bootstrap path is what the running customer host carries
- board-side live convergence remains blocked on NetBird reachability, not on
  this GCS bootstrap logic

## Slice 35

Goal:

- make `install_git_sync_mds.sh` behave correctly on reruns and remove one more
  hardcoded path that made the installer harder to validate safely

Implemented:

- changed `tools/git_sync_mds/install_git_sync_mds.sh` to `restart` the
  oneshot service instead of `start`, so reruns refresh live sync state instead
  of silently no-oping on an already-active unit
- added `MDS_SYSTEMD_DIR` support to the installer with default
  `/etc/systemd/system`
- created regression coverage proving the installer uses `restart` and does not
  fall back to `start`

Verification:

- `bash -n tools/git_sync_mds/install_git_sync_mds.sh`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "install_git_sync_service_restarts_active_oneshot_unit"`

Residual drift after this slice:

- live boards are still externally offline on NetBird, so board-side runtime
  convergence cannot proceed yet
- the next productive non-blocked work returns to GCS/runtime admin and fleet
  sidecar control slices

## Slice 36

Goal:

- stop mode/apply restarts from forcing unnecessary production React rebuilds
  when the existing frontend bundle is already current

Implemented:

- updated `app/linux_dashboard_start.sh` so frontend build freshness no longer
  relies on the coarse `build/` directory mtime
- introduced an explicit React build marker resolver that prefers:
  - `build/asset-manifest.json`
  - `build/index.html`
- added a generic helper for checking whether `src/`, `public/`, `.env`, or
  version/dependency metadata are newer than the selected build marker
- extended build invalidation checks to cover:
  - `package.json`
  - `package-lock.json`
  - `.env`
  - `VERSION`
  - `public/`
  - `src/`
- added executable regression coverage proving:
  - a newer build marker suppresses rebuild
  - a newer source file still triggers rebuild

Verification:

- `bash -n app/linux_dashboard_start.sh`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "dashboard_start"`
- `git diff --check`

Residual drift after this slice:

- live Hetzner still needs one more launcher rollout to verify the corrected
  build-marker logic on the running private GCS
- board-side live convergence remains externally blocked on NetBird reachability

## Slice 37

Goal:

- remove a real mutable-SITL bootstrap drift where the host repo injects
  canonical `MDS_HW_ID` but older baked images can still boot through a stale
  `startup_sitl.sh`

Implemented:

- changed `multiple_sitl/create_dockers.sh` so startup-script source now tracks
  rollout mode:
  - mutable latest-on-boot (`MDS_SITL_GIT_SYNC=true`) defaults to the
    host-mounted current `startup_sitl.sh`
  - pinned-image runs (`MDS_SITL_GIT_SYNC=false`) stay on the image-baked
    script
- made the launcher forward the resolved
  `MDS_SITL_USE_HOST_STARTUP_SCRIPT` value into each container explicitly so
  runtime inventory can report the active bootstrap source
- extended SITL policy / instance inventory with startup-script source
  reporting
- removed the last dangling `HWID_DIR` shell reference from
  `startup_sitl.sh`, which would otherwise crash the host-mounted bootstrap
  path under `set -u`
- updated SITL docs and env reference to explain the new auto behavior and the
  remaining explicit override path

Verification:

- `bash -n multiple_sitl/create_dockers.sh`
- `python3 -m pytest --no-cov tests/test_sitl_control_service.py -k "startup_script or build_policy"`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "canonical_mds_hw_id"`
- live Hetzner reconcile after rollout should show SITL containers booting from
  the host-mounted current startup path instead of stale baked bootstrap logic

Residual drift after this slice:

- live Hetzner still needs the new private commit fast-forwarded and a fresh
  SITL reconcile to replace containers created under the old baked bootstrap
  path

## Slice 38

Goal:

- make Runtime Admin mode/apply restarts actually deterministic under tmux by
  preventing stale tmux-server environment state from re-injecting an old
  `MDS_MODE`

Implemented:

- updated `app/linux_dashboard_start.sh` to define an explicit tmux runtime env
  allowlist covering:
  - `MDS_MODE`
  - repo/auth/runtime sync env
  - GCS launcher env
  - frontend mode env
- added `sync_tmux_session_environment()` and call it immediately after each
  new tmux session is created, before the backend/frontend commands are sent
- added `build_tmux_runtime_env_prefix()` so the first pane shell also receives
  the current exported values inline, instead of relying on tmux server or pane
  inheritance semantics
- added regression coverage proving the launcher now:
  - pushes current `MDS_MODE` into the tmux session
  - pushes other active runtime env values
  - explicitly unsets absent secrets such as `MDS_GIT_AUTH_TOKEN_FILE` instead
    of letting old tmux-server values leak through
  - emits an inline pane-command prefix with the same runtime env contract

Verification:

- `bash -n app/linux_dashboard_start.sh`
- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "dashboard_start"`
- live Hetzner restart/apply validation should now show runtime mode switching
  correctly even when the tmux server has been running for a long time

Residual drift after this slice:

- private repo still needs the same launcher fix promoted and then validated on
  live Hetzner with a real SITL->REAL apply flow

## Slice 39

Goal:

- make leftover local SITL cleanup still possible after the GCS has already
  switched into `REAL` mode, without reopening the full SITL lifecycle surface

Implemented:

- updated `src/sitl_control_service.py` so:
  - reconcile/create/restart/image-release remain simulation-only mutations
  - single-instance remove and batch remove stay allowed even when
    `Params.sim_mode` is false
- updated the SITL Control policy model so the dashboard can distinguish:
  - full SITL lifecycle mode
  - cleanup-only mode
- updated `SitlControlPage` so `REAL` mode now keeps:
  - host summary
  - operations
  - local instance inventory
  - log tails
  - remove actions
  while hiding full lifecycle controls such as reconcile, create, restart, and
  image save
- updated Runtime Admin/operator docs to point operators at cleanup-only SITL
  Control after a `REAL` mode switch

Verification:

- focused SITL control backend tests
- focused SITL control frontend tests
- live Hetzner validation should prove that leftover local SITL containers can
  now be removed after a `REAL` mode switch without falling back to shell

## Slice 40

Goal:

- harden the canonical tmux launcher against intermittent empty-session starts
  observed during live Hetzner validation

Implemented:

- added `tmux_wait_for_pane_ready()` in `app/linux_dashboard_start.sh`
- now pause briefly after:
  - `tmux new-session`
  - `tmux split-window`
  - `tmux new-window`
- added launcher regression coverage proving the combined-pane startup path:
  - waits for pane readiness
  - still sends both backend and frontend launch commands

Verification:

- `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "dashboard_start"`
- live Hetzner validation should no longer strand an empty `MDS-GCS` session
  with no backend/frontend processes after a restart

## Slice 41

Goal:

- close the last mixed-mode runtime proof on live infrastructure by verifying
  that the private GCS can roundtrip `REAL -> SITL -> REAL` without leaking
  heartbeats across modes and without leaving manual SITL cleanup as a shell-only
  recovery path

Implemented:

- validated the live private Hetzner GCS in `REAL` mode with:
  - exactly 2 real hardware heartbeats
  - both nodes synced to the same private `main-candidate` commit as GCS
  - zero SITL containers
- switched the live GCS to `SITL`, reconciled 4 local containers, and verified:
  - 4 SITL heartbeats only
  - zero real-board leakage into the SITL view
  - current private host-mounted startup/bootstrap path in the reconciled
    containers
- switched the same live GCS back to `REAL` while the 4 SITL containers still
  existed and verified:
  - the `REAL` runtime only surfaced the 2 hardware boards
  - leftover SITL instances remained visible only through cleanup-only SITL
    Control inventory
- removed the 4 SITL containers through the cleanup-only API path in `REAL`
  mode and verified:
  - `sitl_instance_count = 0`
  - exactly 2 real hardware heartbeats remain visible
  - node git/auth status remains healthy and `2/2` nodes stay synced

Verification:

- live Hetzner `runtime-status`, `fleet/heartbeats`, `sitl/instances`, and
  `git/status` polling across both mode switches
- live `POST /api/v1/system/sitl/reconcile` to 4 instances
- live `POST /api/v1/system/sitl/instances/actions` batch remove in `REAL`
  cleanup-only mode

## Slice 42

Goal:

- simplify mobile runtime chrome so operators see one authoritative runtime
  indicator in the sidebar, not a second floating badge over the page shell

Implemented:

- removed the standalone mobile Runtime Admin link from the top mobile shell
- kept the sidebar runtime badge visible and clickable in expanded and collapsed
  sidebar states
- removed the verbose expanded-sidebar runtime summary text while preserving the
  Runtime Admin tooltip and the `Apply` attention marker when restart is pending
- changed the mobile sidebar backdrop from a blur overlay to a plain dim overlay
  so the page does not visually smear when the hamburger is opened
- updated focused frontend tests to lock the non-duplicated mobile runtime entry
  and the compact sidebar runtime badge behavior

Verification:

- focused frontend tests on Hetzner passed:
  `npm test -- --runTestsByPath src/App.test.js src/components/SidebarMenu.test.js --watch=false`
- rebuilt the live private frontend bundle on Hetzner and verified:
  - runtime status remains `REAL`
  - `restart_required=false`
  - 2 real hardware nodes online
  - 0 local SITL containers
- captured a mobile sidebar screenshot proving:
  - the backdrop exists
  - the floating mobile runtime link is gone
  - the sidebar-owned compact runtime link remains visible as `REAL`

## Slice 43

Goal:

- correct Runtime Admin scope so it reads as GCS-host administration, not a
  partial fleet-node sidecar manager

Implemented:

- removed the prominent GCS-local `mavlink-anywhere` and Smart Wi-Fi dashboard
  cards from Runtime Admin
- replaced them with a single `Host Capabilities` card that summarizes:
  - local SITL inventory risk
  - git-tracked fleet profile intent
  - desired MAVLink sidecar policy/ref
  - desired connectivity sidecar policy/ref
  - whether optional local GCS diagnostics are present
- removed normal UI display of raw git token and SSH key paths
- kept GCS git access visible as role, access method, health summary, and
  secret posture only
- updated Runtime Admin tests to assert:
  - raw secret/tool paths are not rendered
  - local sidecar dashboard links are not rendered
  - Fleet Ops is named as the per-node compliance surface

Verification:

- passed focused frontend tests on Hetzner as part of Slice 44 verification:
  `npm test -- --runTestsByPath src/App.test.js src/components/SidebarMenu.test.js src/pages/RuntimeAdminPage.test.js --watch=false`

## Slice 44

Goal:

- fix the mobile sidebar regression where the hamburger drawer could look faded
  and feel non-scrollable after the chrome cleanup

Implemented:

- moved mobile shell controls above the modal layer so the close control remains
  reliably reachable
- when the drawer is open, moved the close control outside the drawer edge so it
  cannot cover scrolled navigation rows
- moved the backdrop to the modal-backdrop layer and the sidebar drawer to the
  modal layer, eliminating ambiguous stacking with page content
- rendered the backdrop outside the mobile control wrapper so the control
  wrapper cannot lift the dim overlay above the drawer
- raised the open mobile drawer above the app tooltip/toast layer so sync
  banners and toast surfaces cannot sit over navigation
- made the mobile drawer itself the scroll container with momentum scrolling,
  overscroll containment, and vertical touch handling
- kept mobile nav content non-nested-scroll so operators can drag anywhere on
  the drawer instead of needing to hit only the nav list
- made the light-mode mobile drawer background fully opaque to avoid the drawer
  looking disabled or washed out by the dim page backdrop
- disabled mobile drawer backdrop filtering so page blur cannot visually bleed
  into the drawer surface
- added solid fallback colors behind drawer gradients so no page content can
  visually show through the panel

Verification:

- passed focused frontend tests on Hetzner:
  `npm test -- --runTestsByPath src/App.test.js src/components/SidebarMenu.test.js src/pages/RuntimeAdminPage.test.js --watch=false`
- passed deployed mobile screenshot verification:
  `/tmp/mds_mobile_sidebar_slice44_structural_fix.png`
- verified runtime layering state from headless Chrome:
  drawer `z-index=1090`, backdrop `z-index=1080`, control layer
  `z-index=1092`, backdrop parent `app-container app-mobile`, drawer
  scroll moved from `0` to `240`, and the drawer hit-test returned `nav-item`

## Slice 45

Goal:

- add the missing Fleet Ops surface referenced by Runtime Admin so per-node
  sync, auth, MAVLink sidecar, and connectivity sidecar posture are no longer
  mixed into GCS-host administration

Implemented:

- added a new read-only Fleet Ops route and sidebar entry:
  - `/fleet-ops`
- added a Fleet Ops view model that merges existing:
  - `GET /api/v1/git/status`
  - `GET /api/v1/fleet/heartbeats`
- added summary counters for:
  - online nodes
  - commit sync against GCS
  - git auth health
  - MAVLink sidecar health
  - connectivity not-applicable/healthy state
- added operator tabs for:
  - Overview
  - Access
  - Sidecars
  - Sync
- kept the first slice status-only:
  - no credential editing
  - no sidecar mutation
  - no broad fix-all action
  - no local secret path exposure
- documented the Fleet Ops boundary in `docs/guides/fleet-ops.md`
- corrected the Fleet Ops toolbar accessible region label so the parent
  control group does not collide with the explicit filter select label

Verification:

- passed focused frontend tests on Hetzner:
  `npm test -- --runTestsByPath src/pages/FleetOpsPage.test.js src/utilities/fleetOpsViewModel.test.js src/components/SidebarMenu.test.js --watch=false`
- passed production dashboard build on Hetzner:
  `npm --prefix /opt/mds/app/dashboard/drone-dashboard run build`
- verified deployed `/fleet-ops` returns HTTP 200 from the private runtime
- triggered canonical git sync and verified both real nodes converged to the
  GCS private candidate commit:
  - target commit `54c7cd7762949827451ef21e92889c9ff5411cf3`
  - `synced_count=2`
  - `needs_sync_count=0`
  - `online_count=2`

## Slice 46

Goal:

- add compact sidecar compliance hashes so Fleet Ops can show whether a node's
  desired sidecar ownership/profile inputs match what was last applied

Implemented:

- extended `tools/reconcile_mavlink_runtime.sh status` with:
  - desired config hash
  - applied config hash
  - hash match state
- extended `tools/reconcile_connectivity.sh status` with:
  - desired config hash
  - applied config hash
  - hash match state
  - Smart Wi-Fi profile hash when a profile exists
- extended node and GCS runtime schemas so those fields flow through
  `GET /api/v1/git/status`
- updated Fleet Ops sidecar classification so hash drift is attention-worthy
  even if the process/service is currently active
- added compact desired/applied/profile hash facts to the Sidecars tab
- updated `docs/guides/fleet-ops.md`
- fixed node git-sync hardening issues found during live hardware verification:
  - repo update now schedules coordinator restart when the commit changes
  - coordinator restart has a same-user `SIGKILL` fallback so systemd
    `Restart=on-failure` can recover stale running code even when sudo restart
    cannot complete from inside the coordinator cgroup
  - rendered service-unit validation now uses `.service` temp paths
  - selected GCS git sync no longer leaks `pos_ids` routing metadata into the
    drone command payload
  - unit update permission failures now surface as
    `service_reload_status=warning` plus
    `*.service:manual_unit_update_required`
- updated node installer sudoers so future/rehydrated nodes authorize managed
  `mavlink-anywhere` reconcile through `tools/reconcile_mavlink_runtime.sh`

Verification:

- passed focused backend/sync tests locally:
  - `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "post_sync_runtime_restart or repo_revision_change or git_sync_runtime_state_persists_post_sync_summary"`
  - `python3 -m pytest --no-cov tests/test_bootstrap_installers.py -k "git_sync_service_updates or service_template_validation_uses_service_suffix or service_update_permission_failure"`
  - `python3 -m pytest --no-cov tests/test_gcs_git_routes.py tests/test_gcs_api_http.py -k "git_sync or sync_repos"`
  - `python3 -m py_compile gcs-server/api_routes/git_status.py`
- deployed private candidate to Hetzner in REAL mode
- verified GCS health after each deploy
- verified fleet sync from GCS:
  - both real nodes converged to private candidate
    `42fe3acd7467cababef1a52974647bc98e595ac9`
  - `synced_count=2`
  - `needs_sync_count=0`
  - both nodes online after restart stabilization
  - both nodes expose sidecar desired/applied hash fields through
    `GET /api/v1/git/status`
- verified targeted selected sync works after removing `pos_ids` from drone
  command payload
- verified coordinator restart fallback on both boards:
  - drone 1 restarted at `2026-04-24 17:30:32 CEST`
  - drone 2 restarted at `2026-04-24 17:30:58 CEST`
- current hardware note:
  - existing boards need a node-installer/sudoers refresh before systemd unit
    file changes and managed `mavlink-anywhere` reconcile can apply without
    warning
  - the warning is now explicit in `git_sync_runtime` instead of hidden as
    `not_required`

## Slice 47

Goal:

- tighten the Fleet Ops / Runtime Admin product boundary during the predeploy
  UI audit so operators do not confuse GCS-host controls with drone-node
  maintenance controls

Implemented:

- added compact scope badges:
  - Runtime Admin: `GCS host`
  - Fleet Ops: `Drone nodes`
- added explicit cross-links:
  - Runtime Admin -> Fleet Ops
  - Fleet Ops -> Runtime Admin
- shortened page subtitles to one operator-oriented sentence
- changed Fleet Ops no-selection action summary from `No selection` to
  `All eligible`, matching the actual selected-first/all-eligible sync behavior
- made sidecar dashboard fallbacks more explicit:
  - `Local-only dashboard`
  - `Dashboard off`
  - `No dashboard URL`
- updated focused tests for the new route-link context and visible copy

Verification:

- passed frontend UI audit locally:
  `python3 tools/audit_frontend_ui.py --max-items 120`
- passed whitespace check:
  `git diff --check`
- passed focused frontend tests on Hetzner:
  `CI=true npm test -- --runTestsByPath src/pages/FleetOpsPage.test.js src/pages/RuntimeAdminPage.test.js --watchAll=false`
- passed production dashboard build on Hetzner:
  `npm run build`

## Slice 48

Goal:

- remove Fleet Enrollment's page-local confirmation dialog implementation and
  align enrollment mutations with the shared operator modal primitive

Implemented:

- routed the existing enrollment action wrapper through shared `ConfirmDialog`
  while preserving all domain form content for:
  - accept-as-new
  - replace slot
  - recover node
  - ignore
  - reject
- removed stale Fleet Enrollment modal/backdrop/button CSS and kept only the
  domain-specific dialog body layout
- preserved busy-state behavior, backdrop/Escape blocking through the shared
  primitive, and the existing mutation service calls

Verification:

- passed frontend UI audit locally:
  `python3 tools/audit_frontend_ui.py --max-items 120`
- passed whitespace check:
  `git diff --check`
- passed focused frontend tests on Hetzner:
  `CI=true npm test -- --runTestsByPath src/pages/FleetEnrollmentPage.test.js src/components/ui/OperatorPrimitives.test.js --watchAll=false`
- passed production dashboard build on Hetzner:
  `npm run build`
