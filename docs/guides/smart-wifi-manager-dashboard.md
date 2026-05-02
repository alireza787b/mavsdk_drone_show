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
2. In **Known Profiles**, click **Add Profile**.
3. Fill:
   - `ID`: short stable name, for example `field-router`
   - `SSID`: exact Wi-Fi network name
   - `Priority`: higher wins, for example `100` for primary
   - `Password`: leave blank for open or existing stored password; enter a new
     password only when you intend to store it on this node
   - `Password File`: preferred production option when secrets are managed as
     local files
4. Click **Save Config**.
5. Click **Trigger Scan**.
6. Confirm **Live Status** shows the expected current SSID or a clear warning.

Blank password fields preserve an already stored inline password for existing
profiles. Use **Remove Profile** only after confirming the node has another
reachable management path.

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
