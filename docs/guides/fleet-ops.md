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
- local-only sidecar dashboards remain visible as disabled diagnostic icons;
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

### Presence

Fleet Ops uses the canonical GCS presence contract from
`GET /api/v1/fleet/heartbeats`. Do not infer liveness from old git status
records; those are diagnostic records and can outlive a disconnected node.

Presence states:

- `never_seen`: configured/reporting identity exists, but this GCS runtime has no accepted heartbeat or telemetry evidence.
- `live`: heartbeat or telemetry is fresh enough for operator action.
- `recently_lost`: link dropped inside the short grace window; monitor for recovery.
- `stale`: link is older than the recent-loss window but not yet long-offline.
- `offline`: link has exceeded the stale threshold.
- `blocked`: link is live, but readiness/preflight blocks operation.

The thresholds are registry-backed GCS env keys:

- `MDS_PRESENCE_RECENT_LOSS_SEC`
- `MDS_PRESENCE_STALE_SEC`
- `MDS_PRESENCE_LONG_OFFLINE_SEC`

### Synced

Means the node commit matches the GCS commit. A drifted node may still be
running, but it should not be treated as handoff-ready until it has synced.

Fleet Ops also surfaces the latest node-local git-sync runtime summary. If
`service_reload_status=warning` and a deferred action ends in
`manual_unit_update_required`, the repository sync succeeded but the node could
not install an updated systemd unit file with its current controlled sudoers.
Rerun the node installer or refresh sudoers before expecting service unit
changes to apply automatically.

For SITL containers, `service_reload_status=skipped` is expected. SITL does not
own real-node systemd units inside the git-sync path, so Fleet Ops treats that
state as healthy/not applicable rather than drift.

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

## Dashboard Links

Fleet Ops only opens a node sidecar dashboard when the node reports a direct
URL or a non-loopback listen address such as `0.0.0.0:9070` or
`0.0.0.0:9080`. A listen address such as `127.0.0.1:9070` is treated as
local-only and appears as a disabled icon with a tooltip. This avoids giving
operators broken NetBird links while still showing that the sidecar exists.

For a one-off diagnostic session, use SSH port forwarding or temporarily set a
node-local dashboard listen value, then run node sync/reconcile:

```bash
MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN=0.0.0.0:9070
MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN=0.0.0.0:9080
```

Do not expose sidecar dashboards on untrusted networks. Prefer NetBird, a local
field LAN, or a future GCS proxy surface.

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
