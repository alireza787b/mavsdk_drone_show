# Smart Wi-Fi Manager Dashboard

Smart Wi-Fi Manager is a node-local sidecar. Use it only on real companion
nodes where `MDS_CONNECTIVITY_BACKEND=smart-wifi-manager`.

## Open The Dashboard

Preferred path:

1. Open **Fleet Ops**.
2. Find the drone row.
3. Click the Wi-Fi icon when it is enabled.

Direct path:

```text
http://<node-netbird-or-local-ip>:9080
```

If the icon is disabled or the URL does not open, check that the node reports
`MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN=0.0.0.0:9080` and that your operator
device can reach the node over the local network or VPN.

Direct browser access to `:9080` is primarily a node-local diagnostic surface.
Smart Wi-Fi Manager deliberately blocks remote mutating requests when no
`SMART_WIFI_MANAGER_API_TOKEN` is configured. That means a remote browser may
load the page but still fail on **Save**, **Remove Profile**, or other changes
with:

```json
{"error":"SMART_WIFI_MANAGER_API_TOKEN is required for remote mutating requests"}
```

That error is a security guard, not a GCS/Simurgh failure. For field recovery,
prefer one of these paths:

1. Use **Fleet Ops Wi-Fi** from the GCS for profile dry-run/apply. The node API
   proxies approved profile operations to the sidecar over node loopback.
2. Use an SSH tunnel for one board so the dashboard sees the request as
   loopback:

   ```bash
   ssh -L 9080:127.0.0.1:9080 <operator>@<node-netbird-ip>
   ```

   Then open `http://127.0.0.1:9080/` on the operator machine.
3. Use direct `http://<node-ip>:9080/` only on a trusted NetBird/local network,
   and only for remote changes after the dashboard client and service are both
   configured to send/accept the mutation token.

## Add Or Update A Wi-Fi Profile

1. Keep a known-good access path active first, such as Ethernet, NetBird, or the
   current Wi-Fi link.
2. Click **Trigger Scan**.
3. If the target SSID appears under **Available Networks**, click **Add** or
   **Add top**. The dashboard opens a profile dialog so you can enter the
   password before the network becomes a known profile. If the SSID does not
   appear, use **Add Profile** under **Known Profiles** and type the SSID
   manually.
4. Fill or review:
   - `ID`: short stable name, for example `field-router`
   - `SSID`: exact Wi-Fi network name
   - `Priority`: higher wins; **Add top** and **Prefer** raise priority above
     the current maximum
   - `Password`: leave blank for open networks or existing stored passwords;
     enter a new password only when you intend to store it on this node
   - `Password File`: preferred production option when secrets are managed as
     local files
5. Click **Save Profile** to store the profile, or **Save & Scan Now** to store
   it and immediately ask the service to re-evaluate networks.
6. Confirm **Live Status** shows the expected current SSID or a clear warning.

The dashboard separates scanned networks from known profiles:

- **Available Networks** are discovery results from the latest scan.
- **Known Profiles** are the only networks the service may join.

This keeps Wi-Fi changes auditable and prevents one-off manual connections that
do not survive reboot or fleet sync.

## Manual Profile Details

If adding manually from **Known Profiles**, fill:

1. `ID`: short stable name, for example `field-router`
2. `SSID`: exact Wi-Fi network name
3. `Priority`: higher wins, for example `100` for primary
4. `Password`: leave blank for open or existing stored password; enter a new
   password only when you intend to store it on this node
5. `Password File`: preferred production option when secrets are managed as
   local files
6. Click **Save Config**.

Blank password fields preserve an already stored inline password for existing
profiles. Use **Remove Profile** only after confirming the node has another
reachable management path.

## Change Priority Or Remove A Profile

- To prioritize a network, click **Up**, click **Down**, or edit the `Priority`
  number and click **Save Config**.
- To raise a scanned network above all others, click **Prefer** or **Add top**,
  save, then trigger a scan.
- To disable a network without deleting it, check `Disabled` and save.
- To remove a network, click **Remove Profile**, save, then trigger a scan.
  Remove only after confirming another management path is active.

In `observe` mode Smart Wi-Fi reports only and does not mutate sidecar profile
state. In `local` mode the node-local dashboard/CLI is authoritative.
`fleet-merge` applies the fleet baseline while preserving local emergency
networks. `fleet-strict` is advanced/lab mode only and requires explicit Fleet
Ops confirmation.

## Legacy Manual Flow

If the node is running an older dashboard without scan-table actions:

1. In **Known Profiles**, click **Add Profile**.
2. Fill:
   - `ID`: short stable name, for example `field-router`
   - `SSID`: exact Wi-Fi network name
   - `Priority`: higher wins, for example `100` for primary
   - `Password`: leave blank for open or existing stored password; enter a new
     password only when you intend to store it on this node
   - `Password File`: preferred production option when secrets are managed as
     local files
3. Click **Save Profile**.
4. Click **Trigger Scan**.
5. Confirm **Live Status** shows the expected current SSID or a clear warning.

The dashboard status panel should not be empty on a healthy install. It should
show the current SSID, scan age, selected target, mode, visible networks, and
known profile list. If those are blank, restart `smart-wifi-manager.service`
and `smart-wifi-manager-dashboard.service`, then re-open the node URL.

## Fleet Rollout

For many drones, prefer the MDS fleet profile workflow:

1. Commit the approved private fleet baseline at
   `config/fleet-profiles/smart-wifi-manager/config.json`.
2. Open **Fleet Ops Wi-Fi**.
3. Dry-run reconcile for selected drones.
4. Confirm apply only after reviewing blocked nodes, drift, and local extras.
5. Confirm Fleet Ops profile hashes match.

Do not store real customer SSIDs or passwords in public repositories.
MDS defaults to merge-style Smart Wi-Fi rollout: the private repo profile is the
fleet baseline, and node-local field networks remain available until an
operator intentionally resets that node profile set.

## Troubleshooting

- Dashboard opens but status is empty: check `smart-wifi-manager.service`.
- Dashboard URL does not open while another sidecar port on the same node works:
  check `smart-wifi-manager-dashboard.service`, confirm it is listening on the
  expected address with `ss -ltnp`, and verify
  `MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN` in `/etc/mds/local.env`.
- Remove/save returns `SMART_WIFI_MANAGER_API_TOKEN is required for remote
  mutating requests`: use Fleet Ops Wi-Fi or an SSH tunnel, or deploy a
  token-aware remote dashboard path. Do not disable this guard for field nodes.
- Save succeeds but nothing changes: click **Trigger Scan** or wait for the next
  scan interval.
- Node disappears after a bad Wi-Fi change: recover through Ethernet, console,
  cellular, or another known-good link and either disable the bad profile or set
  mode to `observe`.
