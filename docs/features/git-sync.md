# Git Sync System

## Architecture Overview

The MDS git sync system uses git as the transport mechanism to keep code and configuration synchronized between the GCS (Ground Control Station) server and the drone fleet.

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

## Sync Trigger Paths

| Trigger | When | What Happens |
|---------|------|-------------|
| Boot service | Drone startup | `update_repo_ssh.sh` runs via systemd service |
| UI "Sync Drones" button | Operator-initiated | `POST /api/v1/git/sync-operations` sends `UPDATE_CODE` (Mission 103) to drones |
| UI "Save & Commit" button | Config/swarm save | `git_operations()` commits + pushes on GCS |
| UI "Commit Mission Outputs" | Swarm Trajectory review | creates a local git commit, and only pushes when `MDS_GIT_AUTO_PUSH=true` |
| UPDATE_CODE command | GCS command | Drone runs `actions.py --action=update_code` which calls `update_repo_ssh.sh` |

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
- "Sync Now" button triggers `POST /api/v1/git/sync-operations`
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
| Connectivity probe fails inside Docker/SITL | ICMP blocked or `ping` unavailable | The probe is advisory only; `git fetch` is the definitive check |
| Sync accepted but never verified | Runtime command parameter missing or git update failed on drone | Check drone session logs; success is only reported after branch/commit/status match |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/git/status` | GET | Aggregated drone git status + GCS status |
| `/api/v1/git/sync-operations` | POST | Trigger UPDATE_CODE on drones |
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

### Frontend
- `src/components/SyncWarningBanner.js` - Out-of-sync warning banner
- `src/components/ControlButtons.js` - "Sync Drones" button
- `src/components/GitInfo.js` - GCS git info display
- `src/components/DroneGitStatus.js` - Per-drone git status card
- `src/utilities/utilities.js` - URL helpers (`getSyncReposURL`, `getUnifiedGitStatusURL`)

### Configuration
- `src/params.py` - `GIT_REPO_URL`, `GIT_BRANCH`, `GIT_AUTO_PUSH` (overridable via `MDS_REPO_URL`/`MDS_BRANCH`/`MDS_GIT_AUTO_PUSH` env vars or `/etc/mds/gcs.env` and `/etc/mds/local.env`)
- `tools/git_sync_mds/git_sync_mds.service` - Systemd service template (sources `/etc/mds/local.env` for fork config)
- `tools/git_sync_mds/install_git_sync_mds.sh` - Service installer (substitutes user/home at install time)

## Custom Repository Configuration

For custom forks, org repos, or private customer repos, the following override chain applies:

| Component | Config Source | Override Method |
|-----------|-------------|-----------------|
| GCS Python server | `Params.GIT_BRANCH` / `Params.GIT_REPO_URL` / `Params.GIT_AUTO_PUSH` | Set `MDS_BRANCH`/`MDS_REPO_URL`/`MDS_GIT_AUTO_PUSH` in `/etc/mds/gcs.env` |
| Drone boot sync and `UPDATE_CODE` action | `update_repo_ssh.sh` | Set `MDS_REPO_URL`/`MDS_BRANCH` in `/etc/mds/local.env` |
| SITL containers | `startup_sitl.sh` defaults | Export `MDS_REPO_URL`/`MDS_BRANCH` before running `create_dockers.sh` |
| `/api/v1/git/sync-operations` command | Reads `Params.GIT_BRANCH` | Same as GCS Python server |

The GCS launcher sources `/etc/mds/gcs.env` on startup. Drone boot sync and dashboard-triggered `UPDATE_CODE` both load `/etc/mds/local.env`, so hardware repo/branch selection stays aligned across boot-time and operator-triggered sync.

Generated SITL provenance files (`.mds_sitl_image_build.env`, `.mds_px4_source_provenance.env`, `.mds_px4_submodules.txt`) are intentionally ignored by git-status reporting. They are runtime metadata, not operator changes, and should not cause false out-of-sync warnings.

If you are validating a fix that changes the drone-side sync runtime itself, recreate existing SITL containers once so they boot with the corrected updater before you rely on operator-triggered `Sync Now` for later revisions.

For the end-to-end customer/private repo workflow, see [Custom Repo Workflow](../guides/custom-repo-workflow.md).
