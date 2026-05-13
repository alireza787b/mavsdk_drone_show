# Git Sync System

## Architecture Overview

The MDS git sync system uses git as the transport mechanism to keep code and configuration synchronized between the GCS (Ground Control Station) server and the drone fleet.

For the higher-level fleet propagation model, secret boundaries, and what
should change once versus per node, see
[Fleet Sync And Secrets](../guides/fleet-sync-and-secrets.md).

```
GCS Server
  - SSH write-back mode (read + write)
  - HTTPS read-only mode (read only)
    |
    v
Git repository (central source of truth)
    |
    v
Drones / SITL (pull latest configured branch)
  - Real drones: SSH (via update_repo_ssh.sh)
  - SITL containers: HTTPS or SSH-compatible git sync at startup
```

## Access Model

| Role | Protocol | Access | Script / Path |
|------|----------|--------|---------------|
| GCS Server | SSH | Read + Write (push) | `gcs-server/utils.py` `git_operations()` |
| GCS Server | HTTPS | Read only unless external credentials are configured | `gcs-server/utils.py` `git_operations()` |
| Real Drones | SSH | Read only (pull) | `tools/update_repo_ssh.sh` |
| SITL Containers | HTTPS or SSH-compatible git remote | Read only by default (pull/reset) | `multiple_sitl/startup_sitl.sh` `update_repository()` |

## Recommended Auth Topology

Use the runtime auth model below unless you have a specific reason to do
otherwise:

- Official public repo:
  - GCS, drones, and SITL can use plain HTTPS without secrets.
- Private customer repo, GCS host:
  - make the GCS the only write-capable runtime.
  - acceptable today: one repo-scoped SSH deploy key with write access on the
    target customer repo.
  - better long-term at scale: a centrally managed machine-user token or
    GitHub App installation token exposed to the runtime as a file-backed
    secret.
- Private customer repo, drones:
  - keep drones read-only only.
  - prefer `MDS_GIT_AUTH_TOKEN_FILE` for non-interactive HTTPS read access.
  - use `MDS_GIT_SSH_KEY_FILE` only as a fallback when HTTPS token auth is not
    available.
- Private customer repo, disposable SITL:
  - keep SITL read-only only.
  - inject read credentials at runtime or image-prep time; never bake them
    into the final image.

Rules:

- do not put raw credentials inside `MDS_REPO_URL`
- do not reuse the GCS write credential on drones
- keep `/etc/mds/gcs.env` and `/etc/mds/local.env` limited to secret file paths
  and runtime repo selection, not secret values
- for private HTTPS read paths, prefer file-backed tokens over raw env values so
  tokens are not exposed in command arguments

## Current Behavior Versus Planned Fleet Behavior

What exists today:

- repo/branch/channel intent can be git-tracked
- nodes can pull that desired state automatically
- host-local runtime files render the effective runtime for each host
- node read credentials can be file-backed and local-only
- post-sync connectivity reconciliation already exists for optional external
  backends such as Smart Wi-Fi Manager
- post-sync managed MAVLink Anywhere runtime reconciliation now exists for the
  external MAVLink routing tool checkout, install state, and dashboard service
- rendered systemd unit updates are now syntax-validated before install so a bad
  service template does not replace a working node unit
- coordinator restarts are now queued only when the synced change affects the
  live node runtime (for example runtime code, coordinator unit, or Python
  requirements), instead of restarting all services unconditionally

Fleet Ops now owns the operator mutation path for drone sync and sidecar
profile reconcile. Git sync, Smart Wi-Fi profile reconcile, and MAVLink endpoint
policy reconcile all require dry-run first and explicit confirmation second.

## Sync Trigger Paths

| Trigger | When | What Happens |
|---------|------|-------------|
| Boot service | Drone startup | `update_repo_ssh.sh` runs via systemd service |
| Fleet Ops sync dry-run/apply | Operator-initiated | `POST /api/v1/fleet/git-sync/dry-run` previews targets, then `POST /api/v1/fleet/git-sync/apply` sends `UPDATE_CODE` (Mission 103) only to confirmed eligible drones |
| UI "Save & Commit" button | Config/swarm save | `git_operations()` commits + pushes on GCS |
| UI "Commit Mission Outputs" | Swarm Trajectory review | creates a local git commit, and only pushes when `MDS_GIT_AUTO_PUSH=true` |
| UPDATE_CODE command | GCS command | Drone runs `actions.py --action=update_code` which calls `update_repo_ssh.sh` |

## Post-Sync Runtime Reconcile

After a successful node pull/reset, `update_repo_ssh.sh` now performs a narrow
runtime reconcile instead of leaving changed units inert or restarting every
service blindly.

Current behavior:

1. compare rendered systemd units against the installed node units
2. validate changed rendered units with `systemd-analyze verify` when available
3. syntax-check changed runtime shell/Python files before any service reconcile runs
4. if any changed runtime path fails validation, hard-reset back to the previous
   known-good commit and report a sync failure while keeping the node on cached code
5. replace only the validated units that actually changed
6. run `systemctl daemon-reload` once if any unit changed
7. refresh enablement links only for units that were already enabled before the update
8. if `daemon-reload` fails after staged unit replacement, restore the previous unit files and reload again
9. re-apply optional connectivity backend state via `tools/reconcile_connectivity.sh`
10. re-apply managed MAVLink Anywhere runtime state via `tools/reconcile_mavlink_runtime.sh`
11. verify or repair the node-local `mavsdk_server` runtime artifact used by
   MAVSDK-backed PX4 params and onboard ULog operations
12. update Python requirements if `requirements.txt` changed
13. schedule a delayed coordinator restart only when the synced revision affects
   the live node runtime

SITL/non-systemd behavior:

- when `MDS_MODE=sitl` or `MDS_SKIP_SYSTEMD_RECONCILE=true`, git sync skips the
  rendered systemd-unit reconcile step
- the sync result records `service_reload_status=skipped`
- Fleet Ops treats that as healthy/not applicable for SITL instead of a
  service failure
- SITL containers still pull/reset code, validate runtime files, and run the
  applicable non-systemd reconcile steps

Important service semantics:

- `coordinator.service`
  - restarted after sync only when runtime-affecting code, its rendered unit, or
    Python requirements changed
  - if the coordinator was already inactive, git sync leaves it stopped instead
    of auto-starting a dormant node runtime unexpectedly
- `git_sync_mds.service`
  - its unit file is updated safely, but the currently running oneshot sync is
    not restarted from inside itself
  - if the unit was already enabled, its enablement links are refreshed after a
    successful daemon reload
  - the new unit applies on the next service invocation
- `led_indicator.service`
  - its unit file can be updated safely
  - if it was already enabled, its enablement links are refreshed after a
    successful daemon reload
  - the new unit applies on the next boot

This keeps the node converged without turning every pull into a blanket restart.

### Operator visibility from node/GCS APIs

The node-local sync runtime summary now reports enough detail for operators and
automation to tell what really happened after a pull:

- `updated_units`
- `service_reload_status`
- `service_reload_message`
- `deferred_unit_actions`
- `coordinator_restart_scheduled`
- connectivity / MAVLink / requirements reconcile outcomes
- `mavsdk_runtime_status` for the node-local `mavsdk_server` artifact

That summary is exposed:

- on the node via `GET /api/v1/git/status`
- on the GCS via aggregated fleet git status

Use it to distinguish:

- unit updates that applied immediately after `daemon-reload`
- unit changes that were rolled back safely
- `git_sync_mds.service` changes that wait for the next invocation
- `led_indicator.service` changes that wait for the next boot
- unit-file changes that could not be applied because the node has not yet
  refreshed controlled sudoers; these appear as
  `service_reload_status=warning` with
  `*.service:manual_unit_update_required`
- coordinator changes that still need manual restart because the service was
  inactive or restart scheduling failed
- MAVSDK runtime repair outcomes such as `present`, `provisioned`, `warning`,
  or `missing_downloader`

By default, git sync attempts a non-destructive `mavsdk_server` repair when the
binary is missing or not executable by running `tools/download_mavsdk_server.sh`
against the current repo path. Set `MDS_SKIP_MAVSDK_RUNTIME_REPAIR=true` only
for controlled lab images where the binary is managed out of band; PX4 params
and MAVSDK-backed onboard ULog operations will remain unavailable if the binary
is absent.

Version ownership for optional sidecars is separate from the MDS Python/systemd
units:

- `smart-wifi-manager`
  - version/ref intent comes from `deployment/defaults.env` plus optional
    `/etc/mds/local.env` overrides
  - git sync does not treat it as an MDS submodule; it re-applies ownership
    through `tools/reconcile_connectivity.sh`
- `mavlink-anywhere`
  - version/ref/install intent comes from `deployment/defaults.env` plus
    optional `/etc/mds/local.env` overrides
  - git sync does not restart a random router unit blindly; it re-applies the
    managed external runtime contract through `tools/reconcile_mavlink_runtime.sh`

Validation and rollback coverage:

- rendered node units:
  - `tools/coordinator.service`
  - `tools/git_sync_mds/git_sync_mds.service`
  - `tools/led_indicator/led_indicator.service`
- runtime shell helpers:
  - any changed `*.sh` path outside docs/tests/frontend-only trees
- runtime Python files:
  - any changed `*.py` path outside docs/tests/frontend-only trees

If validation fails after the pull/reset:

- the node rolls the repo back to the previous commit
- the sync returns a structured failure result
- the node keeps running the last known-good runtime instead of applying the bad revision
- the LED stays in the non-critical `GIT_FAILED_CONTINUING` state rather than escalating to
  a hard fault, unless rollback itself fails

If a rendered unit update succeeds on disk but `systemctl daemon-reload` fails:

- the node restores the previous unit files from staged backups
- it reruns `systemctl daemon-reload` against the restored units
- it keeps running the prior service policy instead of leaving partially applied
  unit changes behind

If a rendered unit is valid but the current node user cannot write it into
`/etc/systemd/system`:

- the repo sync still succeeds
- the node records `service_reload_status=warning`
- the affected unit is recorded as `manual_unit_update_required`
- rerun the node installer or refresh controlled sudoers before expecting
  systemd unit-file changes to apply automatically

The companion installer configures controlled sudoers for optional runtime
reconcile helpers:

- `tools/reconcile_mavlink_runtime.sh`
- `tools/reconcile_connectivity.sh`

## Connectivity Profile Sync

When a node sets `MDS_CONNECTIVITY_BACKEND=smart-wifi-manager`, the git sync
path also reconciles the optional external connectivity backend after each
successful repo update.

Supported profile sources:

- `repo:deployment/connectivity/smart-wifi-manager/profile.json`
- `file:/absolute/path/to/profile.json`

The runtime flow is:

1. `update_repo_ssh.sh` reloads `/etc/mds/local.env`
2. it runs `tools/reconcile_connectivity.sh apply`
3. `reconcile_connectivity.sh` checks the effective profile hash
4. the external `smart-wifi-manager` config helper only re-applies when the
   profile or mode changed

This preserves git-driven fleet rollout without embedding Wi-Fi runtime logic
inside MDS core services.

Repo-driven rollout for Smart Wi-Fi Manager now covers two separate concerns:

- tool version/channel intent in `deployment/defaults.env`
- tool configuration intent in `config/fleet-profiles/smart-wifi-manager/config.json`

Fleet Ops shows `Profile missing` when the node is configured for
Smart Wi-Fi Manager but the repo-owned profile source is absent. That is not a
service crash by itself; it means the fleet has not committed/imported the
profile source that nodes should reconcile.

## Managed MAVLink Runtime Sync

When a node uses a Fleet Ops MAVLink policy mode such as `fleet-merge`, the git
sync path also reconciles the external `mavlink-anywhere` runtime after each
successful repo update.

Current ownership split:

- tool version/channel intent:
  - `deployment/defaults.env`
  - optional node override in `/etc/mds/local.env`
- node-specific router profile:
  - `/etc/mavlink-router/main.conf`
  - generated by bootstrap or explicit operator reconfiguration
- optional dashboard exposure:
  - local host/service state managed by `reconcile_mavlink_runtime.sh`

What the managed reconcile does today:

1. resolve the desired `mavlink-anywhere` repo URL, git ref, install dir, and
   dashboard policy from the deployment profile plus `/etc/mds/local.env`
2. clone or fast-forward the managed checkout to the desired ref
3. install `mavlink-router` only when the binary is missing
4. keep the dashboard installed/up to date when dashboard management is enabled
5. leave node-specific UART/UDP router input settings alone unless bootstrap or
   the operator intentionally reconfigures them

This means MDS now owns the external tool version/channel safely, without
pretending every node in the fleet must share the same UART device or FC input
profile.

## Auto-Commit on Config Save

When `GIT_AUTO_PUSH` is enabled, saving configuration, swarm data, or imported show assets via the dashboard automatically:

1. Stages all changes
2. Commits with a descriptive message (e.g., `config: update config.json via dashboard (10 drones updated)`)
3. Rebases on top of remote changes
4. Pushes to origin

The commit result (hash or error) is returned to the frontend and displayed in a toast notification or import summary.

For fresh GCS installs that stay on the default HTTPS/read-only repository path, the installer now writes `MDS_GIT_AUTO_PUSH=false` into `/etc/mds/gcs.env`. That keeps demo and evaluation setups from attempting write-back they cannot perform. SSH/fork installs keep auto-push enabled.

A 30-second timeout protects against network hangs during fetch/pull/push operations.

When `MDS_GIT_AUTO_PUSH=false`, the dedicated Swarm Trajectory commit endpoint still allows a **local** git commit on the GCS for traceability, but it now skips pull/push entirely and reports that write-back is disabled for this deployment. That keeps read-only/demo stacks honest instead of pretending a repo push happened.

## Monitoring: Git Status Polling

1. GCS polls each drone's `GET /api/v1/git/status` endpoint (via `BackgroundServices._poll_git_status()` async task in `app_fastapi.py`)
2. Results are aggregated and transformed into `DroneGitStatus` objects
3. Available via:
   - REST: `GET /api/v1/git/status` (includes `gcs_status` field for GCS repo status)
   - WebSocket: `/ws/git-status` (same transformed structure, 5-second interval)
4. Frontend shows:
   - Per-drone sync status in `DroneGitStatus` component
   - GCS repo info in `GitInfo` component (uses `GET /api/v1/git/status`)
   - Warning banner (`SyncWarningBanner`) on all pages when drones are out of sync

## Sync Warning Banner

An amber warning banner appears on all dashboard pages when any drones are out of sync with GCS:

```
[warning] X of Y drones out of sync with GCS  [Sync Now]  [x]
```

- Auto-dismisses when all drones sync
- Re-appears if new drones go out of sync
- Operator can manually dismiss (non-blocking)
- "Sync Now" opens Fleet Ops; Fleet Ops uses `/api/v1/fleet/git-sync/dry-run`
  followed by `/api/v1/fleet/git-sync/apply`
- the backend now waits for real repo convergence before reporting success, so a green toast means the drone repos actually matched the GCS revision instead of only accepting the command
- when no explicit target list is provided, the sync path prefers drones with recent heartbeats so an active SITL session does not get polluted by offline config entries from other slots

## Structured Sync Results

Both `update_repo_ssh.sh` and `startup_sitl.sh` output a machine-parseable result line:

```
GIT_SYNC_RESULT={"success":true,"branch":"main-candidate","commit":"abc1234","message":"feat: example commit","duration":5}
```

This is parsed by `actions.py` for logging and status tracking.

## Error States and Recovery

| Error | Cause | Recovery |
|-------|-------|----------|
| Push timeout | Network issue | GCS retries on next save; check connectivity |
| Push permission denied / auth failure | Missing SSH key or non-interactive token | Add verified write credentials or disable `MDS_GIT_AUTO_PUSH` |
| Push rejected (non-fast-forward) | Remote diverged | Pull and resolve conflicts |
| HTTPS remote detected | GCS using HTTPS | Switch to SSH remote for push access |
| Merge conflict on rebase | Concurrent edits | Auto-resolved: abort rebase, reset, retry |
| Fetch timeout on drone | Network issue | Graceful degradation: drone continues with cached code |
| Post-sync runtime validation failure | Pulled revision contains invalid runtime shell, Python, or rendered unit changes | Node rolls back to previous commit, reports sync failure, and continues on cached runtime |
| SITL repo access preflight fails | Missing read-only token/key, wrong branch, or private repo without auth | Fix `MDS_REPO_URL`, `MDS_BRANCH`, `MDS_GIT_AUTH_TOKEN_FILE`, or `MDS_GIT_SSH_KEY_FILE`; see Custom SITL Auth Guide |
| Connectivity probe fails inside Docker/SITL | ICMP blocked or `ping` unavailable | The probe is advisory only; `git fetch` is the definitive check |
| Sync accepted but never verified | Runtime command parameter missing or git update failed on drone | Check drone session logs; success is only reported after branch/commit/status match |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/git/status` | GET | Aggregated drone git status + GCS status |
| `/api/v1/fleet/git-sync` | GET | Fleet Ops sync posture |
| `/api/v1/fleet/git-sync/dry-run` | POST | Preview selected sync targets without mutation |
| `/api/v1/fleet/git-sync/apply` | POST | Confirm a dry-run and dispatch UPDATE_CODE to eligible drones |
| `/api/v1/git/sync-operations` | POST | Deprecated compatibility route; returns failure guidance and does not dispatch UPDATE_CODE |
| `/ws/git-status` | WebSocket | Real-time git status stream |

## Files

### GCS Server
- `gcs-server/utils.py` - `git_operations()`: commit, rebase, push with timeout
- `gcs-server/git_status.py` - Shared data store (`git_status_data_all_drones`), `check_git_sync_status()`
- `gcs-server/app_fastapi.py` - REST/WebSocket endpoints, canonical git sync route, async git polling (`BackgroundServices`)
- `gcs-server/schemas.py` - Pydantic models for git status data
- `gcs-server/config.py` - `get_gcs_git_report()`: returns GCS repo branch/commit/status (used by `GET /api/v1/git/status`)
- `functions/git_manager.py` - `get_local_git_report()`, `get_remote_git_status()`

### Drone Side
- `src/drone_api_server.py` - `GET /api/v1/git/status` endpoint
- `src/drone_communicator.py` - preserves runtime mission fields like `update_branch` and `reboot_after_params` so operator-triggered sync/param actions execute with the intended payload
- `actions.py` - `update_code()` action handler
- `tools/update_repo_ssh.sh` - SSH-based git sync script (production)

### SITL
- `multiple_sitl/startup_sitl.sh` - `update_repository()` with retry/jitter
- `tools/mds_git_access_check.sh` - host-side repo/branch/auth preflight before SITL container launch or image prep

### Frontend
- `src/components/SyncWarningBanner.js` - Out-of-sync warning banner that links operators to Fleet Ops
- `src/components/ControlButtons.js` - Fleet Ops sync entry point
- `src/components/GitInfo.js` - GCS git info display
- `src/components/DroneGitStatus.js` - Per-drone git status card
- `src/utilities/utilities.js` - shared URL helpers such as `getUnifiedGitStatusURL`

### Configuration
- `src/params.py` - fallback runtime policy only
- `deployment/defaults.env` - repo-owned deployment defaults (repo/branch/GCS/connectivity defaults)
- `tools/git_sync_mds/git_sync_mds.service` - Systemd service template (sources `/etc/mds/local.env` for fork config)
- `tools/git_sync_mds/install_git_sync_mds.sh` - Service installer (substitutes user/home at install time)
- `tools/reconcile_connectivity.sh` - optional connectivity backend apply/reconcile helper

## Custom Repository Configuration

For custom forks, org repos, or private customer repos, the following override chain applies:

| Component | Config Source | Override Method |
|-----------|-------------|-----------------|
| GCS Python server | `Params.GIT_BRANCH` / `Params.GIT_REPO_URL` / `Params.GIT_AUTO_PUSH` | Set `MDS_BRANCH`/`MDS_REPO_URL`/`MDS_GIT_AUTO_PUSH` in `/etc/mds/gcs.env` |
| Drone boot sync and `UPDATE_CODE` action | `update_repo_ssh.sh` | Set `MDS_REPO_URL`/`MDS_BRANCH` in `/etc/mds/local.env` |
| SITL containers | `startup_sitl.sh` defaults | Export `MDS_REPO_URL`/`MDS_BRANCH` and optional read-only `MDS_GIT_AUTH_TOKEN_FILE` or `MDS_GIT_SSH_KEY_FILE` before running `create_dockers.sh` |
| Fleet Ops git-sync apply | Reads `Params.GIT_BRANCH` | Same as GCS Python server |

The GCS launcher sources `/etc/mds/gcs.env` on startup. Drone boot sync and dashboard-triggered `UPDATE_CODE` both load `/etc/mds/local.env`, so hardware repo/branch selection stays aligned across boot-time and operator-triggered sync.

Generated SITL provenance files (`.mds_sitl_image_build.env`, `.mds_px4_source_provenance.env`, `.mds_px4_submodules.txt`) are intentionally ignored by git-status reporting. They are runtime metadata, not operator changes, and should not cause false out-of-sync warnings.

If you are validating a fix that changes the drone-side sync runtime itself, recreate existing SITL containers once so they boot with the corrected updater before you rely on operator-triggered `Sync Now` for later revisions.

For the end-to-end customer/private repo workflow, see [Custom Repo Workflow](../guides/custom-repo-workflow.md).
For SITL/private image authentication rules, see [Custom SITL Auth Guide](../guides/custom-sitl-auth.md).
For the fleet-default versus host-local model, see [Fleet Sync And Secrets](../guides/fleet-sync-and-secrets.md).
