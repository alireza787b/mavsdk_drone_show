# Fleet Ops

Fleet Ops is the operator surface for node-level maintenance and compliance.
GCS Runtime is for the GCS host; Fleet Ops is for drones.

Use Fleet Ops to answer:

- which drones are online?
- which drones are synced to the GCS commit?
- which drones have healthy read-only git access?
- which drones have healthy MAVLink routing sidecars?
- which drones need connectivity-sidecar attention?
- which selected drones should dry-run, sync, reconcile, or change sidecar
  policy now?

Fleet Ops is actionable, but guarded:

- selected-node sync is dry-run first, then confirmed apply;
- Smart Wi-Fi and MAVLink profile reconcile are dry-run first, then confirmed
  apply;
- sidecar policy mode changes are dry-run first, then confirmed apply;
- direct dashboard links are shown only when the node reports a reachable URL;
- local-only sidecar dashboards remain visible as disabled diagnostic icons;
- raw tokens, private keys, and secret file contents are never shown in browser UI.

A dry-run is the operator preview step for any fleet mutation. It resolves the
selected drones, verifies presence/eligibility, reads current node posture, and
returns the exact sync/reconcile/policy plan without writing files, restarting
services, changing Wi-Fi, changing MAVLink routes, or changing sidecar policy.
Apply is a separate confirmed action against the reviewed plan.

## Data Sources

Fleet Ops uses existing GCS APIs:

- `GET /api/v1/git/status`
- `GET /api/v1/fleet/heartbeats`
- `GET /api/v1/fleet/git-sync`
- `POST /api/v1/fleet/git-sync/dry-run`
- `POST /api/v1/fleet/git-sync/apply`
- `GET /api/v1/fleet/sidecars`
- `GET /api/v1/fleet/sidecars/{sidecar}`
- `GET /api/v1/fleet/sidecars/{sidecar}/baseline`
- `POST /api/v1/fleet/sidecars/{sidecar}/reconcile/dry-run`
- `POST /api/v1/fleet/sidecars/{sidecar}/reconcile/apply`
- `POST /api/v1/fleet/sidecars/{sidecar}/policy/dry-run`
- `POST /api/v1/fleet/sidecars/{sidecar}/policy/apply`

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
The node also reports normalized sidecar contract fields when available:
`tool`, `mode`, `service_state`, `installed_ref`, `desired_hash`,
`applied_hash`, `local_hash`, `drift_state`, `profile_summary`, and
`last_apply_result`. These are safe status fields; they do not contain Wi-Fi
passwords, tokens, serial secrets, or raw profile contents.

### Connectivity

If the fleet policy sets connectivity backend to `none`, Smart Wi-Fi Manager is
not expected and missing service state is not a failure. If a Smart Wi-Fi
backend is configured, service and profile status are shown as node compliance
signals.

`Profile missing` means the sidecar is installed/reported, but the repo-owned
fleet profile source configured for that node does not exist on the node
checkout. For private fleets, commit a sanitized or approved private baseline at
`config/fleet-profiles/smart-wifi-manager/config.json`, then use Fleet Ops
Wi-Fi profile dry-run/apply. For public demos, keep the backend `none`, use
sanitized placeholder profiles, or use a host-local profile source outside git.

When Smart Wi-Fi Manager is configured, Fleet Ops shows the resolved profile
hash plus desired/applied config hashes. Hashes are shortened in the UI for
operator readability; raw profile content and secrets are not displayed.

Fleet Ops Wi-Fi profile controls live at `/fleet-ops/wifi`. The table shows
drone, presence, service state, installed ref, mode, profile source, desired
hash, local/applied hash, drift state, profile count, dashboard link, and last
apply result. Baseline, node detail, promote-draft, reconcile, and policy-mode
changes are all dialog-based.

`local_extra` drift in Wi-Fi `fleet-merge` means the node has local profiles in
addition to the repo baseline. Fleet Ops keeps those profiles because they may
be field/emergency connectivity. To make a connected drone the new baseline,
open its redacted node summary, promote a sanitized reference draft, review the
draft with the operator, commit the approved baseline to
`config/fleet-profiles/smart-wifi-manager/config.json`, then run reconcile
dry-run and apply for selected drones. Do not copy raw passwords from node
profiles into docs, tickets, public repos, or screenshots.

Fleet Ops MAVLink profile controls live at `/fleet-ops/mavlink` and use the
same operator model. The fleet baseline owns shared endpoint policy; hardware
source settings such as UART device, baud, UDP input source, and PX4 port stay
node-local unless an operator deliberately changes them through node-local
MAVLink Anywhere tooling.

Promote Draft generates a sanitized reference draft only. It does not replace a
repo baseline or alter any node profile.

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
- Smart Wi-Fi and MAVLink profile table/status;
- Smart Wi-Fi and MAVLink profile reconcile dry-run/apply;
- sidecar policy mode dry-run/apply;
- dashboard open links when reachable;
- git auth posture;
- MAVLink and Smart Wi-Fi profile drift visibility.

Fleet Ops does not currently own GCS host runtime changes. GCS Runtime remains
the single source of truth for host mode switching, GCS restart, GCS update,
GCS auth status, and local sidecar runtime diagnostics.

## Related Guides

- [Fleet Sync And Secrets](fleet-sync-and-secrets.md)
- [Runtime Config Sources](runtime-config-sources.md)
- [Smart Wi-Fi Manager Dashboard](smart-wifi-manager-dashboard.md)
- [MAVLink Routing Setup](mavlink-routing-setup.md)
- [SITL Control](sitl-control.md)
