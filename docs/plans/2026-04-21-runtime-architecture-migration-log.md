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
