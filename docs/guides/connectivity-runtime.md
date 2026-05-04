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
| `MDS_INTERNET_CHECK_ENABLED` | Enable low-rate node internet reachability reporting |
| `MDS_INTERNET_CHECK_HOST` | Internet reachability target, default `1.1.1.1` |
| `MDS_INTERNET_CHECK_PORT` | Optional TCP port; keep `0` for ICMP ping |
| `MDS_INTERNET_CHECK_INTERVAL_SEC` | Minimum seconds between internet probes |
| `MDS_INTERNET_CHECK_TIMEOUT_SEC` | Per-probe timeout |
| `MDS_CONNECTIVITY_BACKEND` | Node backend: `none` or `smart-wifi-manager` |
| `MDS_SMART_WIFI_MANAGER_MODE` | Node Smart Wi-Fi mode |
| `MDS_SMART_WIFI_MANAGER_IMPORT_MODE` | Node profile import mode |
| `MDS_SMART_WIFI_MANAGER_REPO_URL` | Node sidecar source repo override |
| `MDS_SMART_WIFI_MANAGER_REF` | Node sidecar release/tag/branch override |
| `MDS_SMART_WIFI_MANAGER_INSTALL_DIR` | Node sidecar install directory |
| `MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN` | Node sidecar dashboard listen address |
| `MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE` | `repo:<path>` or `file:<path>` profile source |

Do not store Wi-Fi passwords in public repositories. Smart Wi-Fi Manager
supports inline passwords and password-file references. Recommended policy:

- public repo or public demo: never commit real SSIDs/passwords; use
  placeholders or node-local profile files.
- private fleet repo: a repo-owned Smart Wi-Fi profile may contain inline
  passwords if the repo access policy is acceptable for the operator; roll it
  out through Fleet Ops + Sync + reconcile.
- highest-security fleet: commit SSIDs and use node-local password files so the
  repo does not contain credentials.

Ad-hoc field credentials can also be applied node-local through the Smart Wi-Fi
dashboard. That is safer while recovering one board, but it is not a fleet-wide
source of truth until the profile is intentionally committed to the private repo.

## Rollout Workflow

1. Set fleet defaults in `deployment/defaults.env`.
2. Bootstrap or sync real nodes so they receive `/etc/mds/local.env`.
3. If using Smart Wi-Fi Manager, import or update the private fleet profile in
   Fleet Ops.
4. Run Sync + reconcile for the target drones.
5. Confirm Fleet Ops shows matching desired/applied profile hashes and healthy
   sidecar status.

For an existing field node, enable Smart Wi-Fi Manager only while a known-good
management path is still available, such as Ethernet or a stable NetBird route.
Start with `MDS_SMART_WIFI_MANAGER_MODE=observe` when you only need the
dashboard and status. Move to `manage` after the profile is verified so a bad
SSID/password cannot strand the node.

To make the node dashboard reachable from a NetBird-connected operator
machine, use a non-loopback listen address:

```bash
MDS_CONNECTIVITY_BACKEND=smart-wifi-manager
MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN=0.0.0.0:9080
```

If Fleet Ops shows the dashboard icon as local-only, the node is probably still
reporting `127.0.0.1:9080`; use SSH tunneling or change the listen address
through the node-local env workflow.

## Transport And Internet Reporting

Heartbeat network metadata distinguishes:

- Wi-Fi (`wlan*`/NetworkManager Wi-Fi)
- Ethernet (`eth*`, `en*`)
- USB modem / HiLink 4G (`usb*`, or USB-backed `enx*` Ethernet devices)
- cellular/GSM (`wwan*`, `ppp*`, NetworkManager GSM)
- VPN/NetBird (`wt*`, `tun*`)

The dashboard uses the default route to label the primary link. Huawei E3372
HiLink-style dongles normally appear to Linux as USB Ethernet (`usb0` or
`enx...`) and should be reported as `4G USB`, not as the wired airframe Ethernet
port.

Use NetworkManager route metrics for transport priority instead of custom
routing scripts:

- Ethernet on the bench: lower metric, for example `100`
- Wi-Fi field router: medium metric, for example `200`
- USB 4G fallback: higher metric, for example `900`

Smart Wi-Fi Manager decides which Wi-Fi SSID to join. NetworkManager route
metrics decide which active transport carries traffic when Ethernet, Wi-Fi, and
4G are all present.

Nodes also report a cached internet probe. Keep the default low-rate ICMP check
or set `MDS_INTERNET_CHECK_PORT` to use a TCP check against an operator-owned
endpoint. The internet probe is diagnostic only; GCS reachability and MAVLink
health remain the flight-control signals.

## Failure Handling

- `none` plus no Smart Wi-Fi service is healthy.
- `smart-wifi-manager` plus missing service is a node setup issue.
- hash mismatch means the node has not applied the current desired profile.
- dashboard links are optional diagnostics; the compliance summary in Fleet Ops
  is the primary operator signal.

Related guides:

- [Fleet Ops](fleet-ops.md)
- [Smart Wi-Fi Manager Dashboard](smart-wifi-manager-dashboard.md)
- [Fleet Sync And Secrets](fleet-sync-and-secrets.md)
- [Runtime Config Sources](runtime-config-sources.md)
