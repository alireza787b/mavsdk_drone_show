# Runtime Config Sources

This guide is the source of truth for where MDS runtime configuration lives.

Use it whenever there is ambiguity between:

- repo files such as `deployment/defaults.env`, `config.json`, `swarm.json`, or `src/params.py`
- GCS host runtime files such as `/etc/mds/gcs.env`
- node runtime files such as `/etc/mds/local.env`
- SITL launch-time environment variables

For how those layers should propagate across a fleet, and how secrets should be
handled separately from normal desired state, see
[Fleet Sync And Secrets](fleet-sync-and-secrets.md).

## Ownership Model

| Concern | Real source of truth | Notes |
|--------|-----------------------|-------|
| Real fleet membership | `config.json` | GCS-side repo file |
| Real swarm topology | `swarm.json` | GCS-side repo file |
| Repo-owned deployment defaults | `deployment/defaults.env` | Git-tracked repo/branch/GCS-address fallback layer |
| Runtime mode | `MDS_MODE=real|sitl` | Canonical mode selector for both GCS and nodes |
| GCS API port | `MDS_GCS_API_PORT` | Defaults to `5030` from `deployment/defaults.env` |
| Dashboard port | `MDS_DASHBOARD_PORT` / `DASHBOARD_PORT` | Defaults to `3030` |
| Drone API port | `MDS_DRONE_API_PORT` | Defaults to `7070` |
| SITL Docker image | `MDS_DOCKER_IMAGE` or `MDS_DEFAULT_DOCKER_IMAGE` | Host override first; otherwise git-tracked deployment default |
| SITL fleet membership | `config_sitl.json` | Selected when `MDS_MODE=sitl` |
| SITL swarm topology | `swarm_sitl.json` | Selected when `MDS_MODE=sitl` |
| GCS host runtime overrides | `/etc/mds/gcs.env` | Repo/branch/auth/launcher behavior for the GCS host |
| Node runtime overrides | `/etc/mds/local.env` | `MDS_HW_ID`, `MDS_MODE`, GCS routing, repo/branch/auth/connectivity overrides for that node |
| Node identity metadata | `/etc/mds/node_identity.json` | Canonical structured node identity/reporting metadata |
| Fallback runtime policy | `src/params.py` | Runtime policy and final code defaults only |

## Effective Precedence

### Python runtime on a node

`src/params.py` preloads `/etc/mds/local.env` into `os.environ` only for keys that
are not already set. That means the effective order is:

1. process environment
2. `/etc/mds/local.env`
3. `deployment/defaults.env`
4. code defaults

### Node announce URL resolution

`mds_node_announce.sh` resolves the GCS API URL in this order:

1. explicit `--gcs-api-url`
2. `MDS_GCS_API_BASE_URL` in process env
3. `MDS_GCS_API_BASE_URL` in `/etc/mds/local.env`
4. `MDS_GCS_IP` plus the default API port (`5030`)

### Node heartbeat runtime identity

Nodes should send the canonical runtime mode to GCS on heartbeat / announce:

- `runtime_mode=real`
- `runtime_mode=sitl`

GCS now uses that declaration as the primary mixed-mode intake fence. This is
intentional:

- safer than inferring mode from IPs, ports, or container naming
- cheap enough to send on every heartbeat
- operator-visible in heartbeat status and GCS Runtime diagnostics

Compatibility note:

- legacy nodes that do not yet send `runtime_mode` are still accepted during
  rollout
- full mixed-mode protection is strongest once every node runtime has been
  updated to declare its mode explicitly

### Connectivity backend resolution

Companion nodes resolve connectivity ownership in this order:

1. process env `MDS_CONNECTIVITY_BACKEND`
2. `/etc/mds/local.env`
3. `deployment/defaults.env`
4. fallback `none`

When `MDS_CONNECTIVITY_BACKEND=smart-wifi-manager`, these companion-node values
also apply:

- `MDS_SMART_WIFI_MANAGER_MODE`
- `MDS_SMART_WIFI_MANAGER_IMPORT_MODE`
- `MDS_SMART_WIFI_MANAGER_REPO_URL`
- `MDS_SMART_WIFI_MANAGER_REF`
- `MDS_SMART_WIFI_MANAGER_INSTALL_DIR`
- `MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN`
- `MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE`

### GCS backend runtime

`gcs-server/start_gcs_server.sh` sources `/etc/mds/gcs.env` before launching the
backend. Those exported values take precedence over repo fallback defaults in
`deployment/defaults.env` and `src/params.py`.

The dashboard **GCS Runtime** page edits this same host-local configuration.
For a mode change, the operator may either:

1. save the host config and then apply the restart, or
2. use the single **Save + restart** action when draft changes are present.

Both paths schedule the canonical launcher restart. Do not restart random
backend/frontend processes manually as the primary mode-switch workflow.

`git_sync_mds.service` now follows the same host-aware precedence:

1. `/etc/mds/gcs.env`
2. `/etc/mds/local.env`
3. `$HOME/.config/mds/env`

That ordering lets the GCS host follow `/etc/mds/gcs.env` while still letting
real companion nodes use `/etc/mds/local.env` as their canonical runtime
authority. If a host deliberately has both files, `/etc/mds/local.env`
overrides `/etc/mds/gcs.env`.

GCS bootstrap now also installs/reconciles `git_sync_mds.service` after
writing `/etc/mds/gcs.env`, so the service inherits the same precedence model
on a fresh host instead of depending on a later manual install step.

`MDS_REPO_URL` in `/etc/mds/gcs.env` and `/etc/mds/local.env` is the canonical
runtime repo authority for that host. The checkout remote (`git remote get-url
origin`) is derived state and must be reconciled to match the configured
runtime repo URL; it is not a second source of truth.

## What Not To Do

Do not use `src/params.py` as the normal place to store:

- a node’s hardware ID
- a deployment-specific GCS IP
- the default repo URL or default branch for a customer fleet
- a fleet connectivity backend or Wi-Fi profile source
- customer-specific host secrets or token file paths
- day-2 operational runtime changes

The following retired markers are no longer read by the active runtime path:

- `.hwID`
- `real.mode`
- `MDS_SIM_MODE`

Do not expect Fleet Enrollment to rewrite swarm topology automatically.

- enrollment updates `config.json`
- swarm relationships still live in `swarm.json`

## Recommended Operator Workflow

### Real hardware

1. bootstrap the GCS host and write `/etc/mds/gcs.env`
2. bootstrap each node and write `/etc/mds/local.env`
3. use Fleet Enrollment to add real nodes into `config.json`
4. manage swarm relationships through `swarm.json` or the GCS swarm UI/APIs
5. commit repo-wide repo/branch/network default changes in `deployment/defaults.env`
6. if you intentionally want repo-driven Wi-Fi rollout, commit
   `deployment/connectivity/smart-wifi-manager/profile.json` in a private fleet repo
   or import that profile from Fleet Ops and then run **Sync + reconcile**
7. keep private read credentials in local secret files; do not put them in git

### SITL

1. use `config_sitl.json` and `swarm_sitl.json`
2. export `MDS_REPO_URL`, `MDS_BRANCH`, and optional auth env vars before launch when needed
3. use `deployment/defaults.env` for repo-wide defaults and process env for temporary overrides
4. avoid editing `src/params.py` just to point SITL at a different repo or branch
5. keep `MDS_MODE=sitl` in the SITL runtime so git sync skips real-node systemd
   unit reconciliation and reports that step as `skipped`, not failed

## Practical Rule

If the change is:

- host-specific -> `/etc/mds/gcs.env`, `/etc/mds/local.env`, or `/etc/mds/node_identity.json`
- fleet/swarm membership -> `config*.json` / `swarm*.json`
- repo-wide deployment defaults -> `deployment/defaults.env`
- repo-owned optional connectivity profile -> `deployment/connectivity/smart-wifi-manager/profile.json`
- runtime policy -> typed settings / code defaults (`src/params.py` remains the transition shim until the typed settings rollout is complete)

For Smart Wi-Fi Manager specifically:

- tool version/channel intent belongs in `deployment/defaults.env`
- tool configuration intent belongs in `deployment/connectivity/smart-wifi-manager/profile.json`
- host-specific exceptions belong in `/etc/mds/local.env`

For the fleet-scale propagation model and operator rules, see
[Fleet Sync And Secrets](fleet-sync-and-secrets.md).
