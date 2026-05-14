# Security Policy

MDS authentication is optional so local SITL demos remain easy to run. Shared or
field deployments should enable dashboard login and then decide separately
whether machine API bearer auth is appropriate.

## Supported Security Modes

| Mode | Env | Intended use |
| --- | --- | --- |
| Open demo | `MDS_AUTH_ENABLED=false`, `MDS_API_AUTH_ENABLED=false` | local development, isolated SITL, public demo boxes |
| Dashboard login | `MDS_AUTH_ENABLED=true`, `MDS_API_AUTH_ENABLED=false` | recommended first production step |
| Full API auth | `MDS_AUTH_ENABLED=true`, `MDS_API_AUTH_ENABLED=true` | advanced deployments after drones, SITL, agents, and scripts have tokens |

Do not expose the GCS, Smart Wi-Fi Manager, or MAVLink Anywhere dashboards to a
public network without an explicit auth, VPN, firewall, or reverse-proxy plan.

## Reporting Issues

Report suspected vulnerabilities privately by email:

- `p30planets@gmail.com`

Please include:

- affected commit or release
- deployment mode
- reproduction steps
- logs with secrets redacted

Do not publish raw tokens, Wi-Fi passwords, private keys, NetBird setup keys, or
customer hostnames in public issues.

## Sidecar Hardening Roadmap

Smart Wi-Fi Manager and MAVLink Anywhere currently rely on trusted local/VPN
network exposure by default. Optional sidecar dashboard login, API/mutation
tokens, CIDR allowlists, and Caddy/reverse-proxy deployment are tracked in
`docs/TODO_deferred.md`.

