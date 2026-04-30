# Connectivity Runtime

This guide covers the MDS connectivity environment variables used by real
companion nodes. SITL nodes normally report connectivity management as not
applicable.

## Operator Model

MDS treats networking as an optional node-side capability:

- `MDS_CONNECTIVITY_BACKEND=none` means the node uses whatever network the
  operating system already provides.
- `MDS_CONNECTIVITY_BACKEND=smart-wifi-manager` means MDS expects the optional
  Smart Wi-Fi Manager sidecar to manage Wi-Fi profiles and report status.
- Ethernet, cellular, NetBird-only, and manually managed links should use
  `none` unless Smart Wi-Fi Manager is deliberately installed.

Fleet Ops is the dashboard surface for checking node connectivity posture,
profile hash drift, and Smart Wi-Fi dashboard links. GCS Runtime is host-local
and should not be used as the primary place to manage drone Wi-Fi.

## Fleet Defaults

Git-tracked defaults live in `deployment/defaults.env`:

| Variable | Purpose |
|---|---|
| `MDS_DEFAULT_CONNECTIVITY_BACKEND` | Default backend for new nodes |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_SLUG` | Public repo slug used for docs/bootstrap URLs |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS` | Default Smart Wi-Fi Manager source repo |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_REF` | Pinned Smart Wi-Fi Manager release/tag/branch |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_MODE` | Sidecar operating mode, usually `observe` or `manage` |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_IMPORT_MODE` | Profile import behavior, usually `replace` |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_INSTALL_DIR` | Sidecar installation directory |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_DASHBOARD_LISTEN` | Sidecar dashboard listen address |
| `MDS_DEFAULT_SMART_WIFI_MANAGER_PROFILE_PATH` | Repo-owned fleet profile path |

Use fleet defaults for repeatable deployments. Use node-local env values only
for hardware-specific overrides.

## Node-Local Overrides

Node-local values live in `/etc/mds/local.env`:

| Variable | Purpose |
|---|---|
| `MDS_CONNECTIVITY_IP` | Optional connectivity-check target IP |
| `MDS_CONNECTIVITY_PORT` | Optional connectivity-check target port |
| `MDS_CONNECTIVITY_BACKEND` | Node backend: `none` or `smart-wifi-manager` |
| `MDS_SMART_WIFI_MANAGER_MODE` | Node Smart Wi-Fi mode |
| `MDS_SMART_WIFI_MANAGER_IMPORT_MODE` | Node profile import mode |
| `MDS_SMART_WIFI_MANAGER_REPO_URL` | Node sidecar source repo override |
| `MDS_SMART_WIFI_MANAGER_REF` | Node sidecar release/tag/branch override |
| `MDS_SMART_WIFI_MANAGER_INSTALL_DIR` | Node sidecar install directory |
| `MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN` | Node sidecar dashboard listen address |
| `MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE` | `repo:<path>` or `file:<path>` profile source |

Do not store Wi-Fi passwords in public repositories. For private fleets, a
repo-owned Smart Wi-Fi profile can be imported from Fleet Ops, committed to the
private fleet repo, and rolled out through Sync + reconcile. For public demos,
keep the backend as `none` or use placeholder profiles.

## Rollout Workflow

1. Set fleet defaults in `deployment/defaults.env`.
2. Bootstrap or sync real nodes so they receive `/etc/mds/local.env`.
3. If using Smart Wi-Fi Manager, import or update the private fleet profile in
   Fleet Ops.
4. Run Sync + reconcile for the target drones.
5. Confirm Fleet Ops shows matching desired/applied profile hashes and healthy
   sidecar status.

## Failure Handling

- `none` plus no Smart Wi-Fi service is healthy.
- `smart-wifi-manager` plus missing service is a node setup issue.
- hash mismatch means the node has not applied the current desired profile.
- dashboard links are optional diagnostics; the compliance summary in Fleet Ops
  is the primary operator signal.

Related guides:

- [Fleet Ops](fleet-ops.md)
- [Fleet Sync And Secrets](fleet-sync-and-secrets.md)
- [Runtime Config Sources](runtime-config-sources.md)
