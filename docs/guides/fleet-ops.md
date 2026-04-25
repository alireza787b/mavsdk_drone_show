# Fleet Ops

Fleet Ops is the operator surface for node-level maintenance and compliance.
GCS Runtime is for the GCS host; Fleet Ops is for drones.

Use Fleet Ops to answer:

- which drones are online?
- which drones are synced to the GCS commit?
- which drones have healthy read-only git access?
- which drones have healthy MAVLink routing sidecars?
- which drones need connectivity-sidecar attention?
- which selected drones should sync and reconcile now?

Fleet Ops is actionable, but guarded:

- selected-node sync is allowed;
- repo-owned Smart Wi-Fi fleet-profile import is allowed;
- sidecar reconcile is performed through the node sync runtime;
- direct dashboard links are shown only when the node reports a reachable URL;
- raw tokens, private keys, and secret file contents are never shown in browser UI.

## Data Sources

Fleet Ops uses existing GCS APIs:

- `GET /api/v1/git/status`
- `GET /api/v1/fleet/heartbeats`
- `GET /api/v1/fleet/sidecars/connectivity/profile`
- `PUT /api/v1/fleet/sidecars/connectivity/profile`

The git-status payload already includes per-node:

- repo branch and commit
- sync posture against the GCS
- repo access mode
- git auth health
- managed `mavlink-anywhere` status
- connectivity backend status
- sidecar desired/applied config hashes when reported by the node
- latest git-sync runtime summary

## Status Meaning

### Online

Comes from the heartbeat feed. Offline means the last node heartbeat is stale or
not accepted by the active GCS mode fence.

### Synced

Means the node commit matches the GCS commit. A drifted node may still be
running, but it should not be treated as handoff-ready until it has synced.

Fleet Ops also surfaces the latest node-local git-sync runtime summary. If
`service_reload_status=warning` and a deferred action ends in
`manual_unit_update_required`, the repository sync succeeded but the node could
not install an updated systemd unit file with its current controlled sudoers.
Rerun the node installer or refresh sudoers before expecting service unit
changes to apply automatically.

The **Drift** filter covers more than commit mismatch. It includes repository
drift, node-local git-sync runtime warnings, and sidecar desired/applied hash
drift so a synced commit cannot hide an unapplied service or profile update.

### Auth

Shows method and health only. Fleet Ops does not expose raw token values,
private key paths, or local secret paths in normal operator UI.

### MAVLink

For real nodes, this reports managed `mavlink-anywhere` posture when the node
provides it. For SITL, managed `mavlink-anywhere` is not expected because SITL
containers use embedded `mavlink-routerd`.

Fleet Ops treats `config_hash_match=false` as sidecar drift even when the
router service is active. That means the service may be running, but the last
recorded reconcile does not match the current desired sidecar ownership inputs.

### Connectivity

If the fleet policy sets connectivity backend to `none`, Smart Wi-Fi Manager is
not expected and missing service state is not a failure. If a Smart Wi-Fi
backend is configured, service and profile status are shown as node compliance
signals.

When Smart Wi-Fi Manager is configured, Fleet Ops shows the resolved profile
hash plus desired/applied config hashes. Hashes are shortened in the UI for
operator readability; raw profile content and secrets are not displayed.

Fleet Ops can import a repo-owned Smart Wi-Fi profile JSON into:

`deployment/connectivity/smart-wifi-manager/profile.json`

Only do this for private fleet repositories when the profile includes
passwords or customer SSIDs. Public demos should either keep
`MDS_CONNECTIVITY_BACKEND=none`, use placeholder/example profiles, or use a
host-local Smart Wi-Fi profile source outside git.

The import API returns only status, counts, and hashes. It does not echo SSIDs,
passwords, token paths, or raw profile content. After import, use **Sync +
reconcile** to dispatch the normal node git-sync path; real nodes with
`MDS_CONNECTIVITY_BACKEND=smart-wifi-manager` will pull the updated profile and
reconcile their Smart Wi-Fi Manager runtime. SITL nodes and nodes with
connectivity backend `none` report this as not applicable rather than failed.

MAVLink profiles are intentionally not handled as a one-click fleet-wide import
yet. MAVLink input sources often differ by board, serial path, Ethernet
topology, or local safety policy, so Fleet Ops currently shows MAVLink status,
hash drift, and dashboard links while leaving profile authoring to the node or
deployment profile workflow.

## Current Boundaries

Fleet Ops owns drone-side action surfaces:

- selected-node git sync;
- selected-node post-sync sidecar reconcile;
- repo-owned Smart Wi-Fi profile import/status;
- dashboard open links when reachable;
- git auth posture;
- MAVLink and Smart Wi-Fi profile drift visibility.

GCS Runtime remains host-local only: mode switch, GCS restart, GCS update, and
GCS auth health.

## Related Guides

- [Fleet Sync And Secrets](fleet-sync-and-secrets.md)
- [Runtime Config Sources](runtime-config-sources.md)
- [MAVLink Routing Setup](mavlink-routing-setup.md)
- [SITL Control](sitl-control.md)
