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

In `observe` mode Smart Wi-Fi reports and updates policy but does not switch.
In `manage` mode it may switch to the highest-priority reachable known profile.

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

1. Update the private fleet Smart Wi-Fi profile from **Fleet Ops**.
2. Commit/push the private repo change.
3. Run **Sync + reconcile** for the target drones.
4. Confirm Fleet Ops profile hashes match.

Do not store real customer SSIDs or passwords in public repositories.

## Troubleshooting

- Dashboard opens but status is empty: check `smart-wifi-manager.service`.
- Save succeeds but nothing changes: click **Trigger Scan** or wait for the next
  scan interval.
- Node disappears after a bad Wi-Fi change: recover through Ethernet, console,
  cellular, or another known-good link and either disable the bad profile or set
  mode to `observe`.
