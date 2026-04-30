# GCS Auth Guide

MDS dashboard/API authentication is optional. The default public-demo posture is
open on the trusted deployment network. Enable auth when the GCS dashboard is
reachable by multiple operators, VPN peers, customer laptops, or any network
that is not fully trusted.

## Security Modes

| Mode | Env | Intended use |
|------|-----|--------------|
| Open demo | `MDS_AUTH_ENABLED=false`, `MDS_API_AUTH_ENABLED=false` | local development, public demo, isolated SITL |
| Dashboard login | `MDS_AUTH_ENABLED=true`, `MDS_API_AUTH_ENABLED=false` | recommended first production step; humans log in, existing drone/API flows keep working |
| Full API auth | `MDS_AUTH_ENABLED=true`, `MDS_API_AUTH_ENABLED=true` | advanced locked-down deployments where drones, agents, and scripts use bearer tokens |

Dashboard login and API bearer-token enforcement are deliberately separate.
This lets a fleet turn on human login without breaking existing companion-node
heartbeats, bootstrap announce calls, or field debugging tools.

## Source Of Truth

Auth configuration belongs in `/etc/mds/gcs.env` on the GCS host:

```bash
MDS_AUTH_ENABLED=true
MDS_API_AUTH_ENABLED=false
MDS_AUTH_USERS_FILE=/etc/mds/auth/users.json
MDS_API_TOKENS_FILE=/etc/mds/auth/api_tokens.json
MDS_AUTH_SESSION_SECRET_FILE=/etc/mds/auth/session_secret
MDS_AUTH_CSRF_SECRET_FILE=/etc/mds/auth/csrf_secret
MDS_AUTH_SESSION_TTL_HOURS=12
MDS_AUTH_SECURE_COOKIES=false
MDS_AUTH_CSRF_ENABLED=true
MDS_AUTH_ALLOWED_CIDRS=
MDS_AUTH_TRUSTED_PROXY_CIDRS=
```

Secret state stays under `/etc/mds/auth/`. The user store contains password
hashes only. API tokens are stored as hashes; plaintext tokens are shown once at
creation time.

Do not commit `/etc/mds/auth/*` or raw passwords/tokens to git.

Auth env keys are also registered in the canonical environment registry:

- registry: `resources/config/mds_env_registry.json`
- reference: [MDS Environment Registry](../reference/mds-environment-registry.md)

The registry records which auth keys are editable, which require GCS restart,
and which values are secrets. Raw token/password values must not be exposed
through the dashboard, API payloads, Docker images, or git-tracked files.

## Bootstrap

Interactive GCS setup asks whether to enable dashboard login and, if enabled,
asks for the first admin username/password:

```bash
sudo ./tools/mds_gcs_init.sh
```

Headless setup can enable auth with a password file:

```bash
printf '%s\n' 'change-this-password' > /root/mds-admin.pass
chmod 600 /root/mds-admin.pass

sudo ./tools/mds_gcs_init.sh \
  --auth \
  --auth-admin-user admin \
  --auth-admin-password-file /root/mds-admin.pass \
  -y
```

For the stricter machine-token mode:

```bash
sudo ./tools/mds_gcs_init.sh --auth --api-auth -y
```

Only enable `--api-auth` after drones, agents, and field scripts have a planned
token distribution path.

## Dashboard UI

When dashboard auth is enabled:

- unauthenticated users see the login page
- the sidebar shows the current signed-in user
- Runtime Admin shows dashboard/API auth posture
- admins can create/disable users and create/revoke API tokens
- signed-in users can open their sidebar profile and change their own password
- viewer users are read-only
- operator users can use normal operator actions but cannot manage auth/runtime administration

If auth is enabled but no admin user exists, the login page shows the SSH
recovery command instead of leaving the operator guessing.

## SSH Recovery CLI

Use the CLI when the browser session is broken, a password is lost, or the first
admin user was not created during bootstrap.

```bash
sudo python3 tools/mds_auth_admin.py status
sudo python3 tools/mds_auth_admin.py add-user admin --role admin
sudo python3 tools/mds_auth_admin.py set-password admin
sudo python3 tools/mds_auth_admin.py disable-dashboard
sudo python3 tools/mds_auth_admin.py enable-dashboard
sudo python3 tools/mds_auth_admin.py rotate-session-secret
```

`status` output intentionally reports posture, users, and token metadata only;
it does not print password hashes or token hashes.

Token examples:

```bash
sudo python3 tools/mds_auth_admin.py create-token \
  --name field-debug \
  --scope readonly \
  --ttl-hours 4

sudo python3 tools/mds_auth_admin.py revoke-token tok_abc123
```

The root `Makefile` provides thin shortcuts:

```bash
make auth-status
make auth-add-user ARGS="admin --role admin"
make auth-enable-api
make auth-disable-api
make auth-create-token ARGS="--name field-debug --scope readonly --ttl-hours 4"
```

Never place passwords or raw tokens directly in shell history. Use the hidden
prompt or a local root-readable password file.

## API And Swagger Docs

With dashboard auth enabled, `/docs`, `/redoc`, and `/openapi.json` require a
valid login session or bearer token. Log in to the dashboard in the same browser,
then open `/docs`.

When full API auth is disabled, machine endpoints used by current companion-node
heartbeats and announce flows remain open:

- `GET /api/v1/origin/bootstrap`
- `POST /api/v1/fleet/heartbeats`
- `POST /api/v1/command-reports/execution-start`
- `POST /api/v1/command-reports/execution-result`
- `POST /api/v1/fleet/candidates/announce`

When full API auth is enabled, scripts and agents must send:

```text
Authorization: Bearer mds_...
```

Browser session mutations use CSRF protection through the `X-MDS-CSRF-Token`
header. The dashboard handles this automatically.

## Drone And SITL Impact

Dashboard login mode does not change drone heartbeat, command report, candidate
announce, or SITL reconciliation behavior.

Full API auth is stricter. Drones, SITL containers, field scripts, and AI agents
must have a bearer token before `MDS_API_AUTH_ENABLED=true` is applied.

MDS intentionally does not auto-approve unknown drones that ask for a token.
That would let an untrusted host on the network request fleet access. The safe
workflow is explicit token provisioning by an admin.

### Current Drones

If only dashboard login is enabled (`MDS_API_AUTH_ENABLED=false`), current
hardware boards and SITL containers continue to work when they reconnect.

Before enabling full API auth for an already-installed drone:

1. Create a scoped token from Runtime Admin, or through SSH:

   ```bash
   make auth-create-token ARGS="--name drone-1 --scope drone --ttl-hours 8760"
   ```

2. Copy the plaintext token once to the drone as root:

   ```bash
   sudo install -d -m 700 /root/.mds/keys
   sudo sh -c 'umask 077; printf "%s\n" "mds_REPLACE_WITH_TOKEN" > /root/.mds/keys/gcs_api_token'
   ```

3. Ensure `/etc/mds/local.env` points to that file:

   ```bash
   MDS_GCS_API_TOKEN_FILE=/root/.mds/keys/gcs_api_token
   ```

4. Restart the drone-side MDS services, or reboot the companion computer.

When the token file exists, heartbeat sender, command reports, origin bootstrap,
and candidate announce calls add:

```text
Authorization: Bearer mds_...
```

### New Drone Bootstrap

For a new drone in a full-API-auth deployment, provide the token as a
root-readable file during bootstrap:

```bash
sudo ./tools/mds_node_init.sh \
  -d 5 \
  --gcs-api-url http://GCS_HOST:5030 \
  --gcs-api-token-file /root/.mds/keys/gcs_api_token \
  -y
```

If full API auth is enabled and a drone has no token, bootstrap/announce does
not create an approval queue. It receives `401 authentication_required`, writes
that into the bootstrap report, and the operator must provision a token or
temporarily disable API auth.

To retry announce after adding a token:

```bash
sudo ./tools/mds_node_announce.sh \
  --gcs-api-url http://GCS_HOST:5030 \
  --gcs-api-token-file /root/.mds/keys/gcs_api_token
```

### SITL Containers

Keep API auth disabled for ordinary public-demo SITL. For private locked-down
SITL, pass a read-only machine token into the container runtime as
`MDS_GCS_API_TOKEN_FILE`, and do not bake raw tokens into the image.
Rotate/revoke SITL tokens after customer demos.

### Enabling Or Disabling API Auth

Changing auth mode through the CLI updates `/etc/mds/gcs.env`. Restart the GCS
launcher after changing dashboard/API auth so the running process uses the new
environment:

```bash
make auth-enable-api
make gcs-stop
make gcs-prod-real
```

Use `make auth-disable-api` and restart the GCS to return machine endpoints to
trusted-network/open mode.

Full API auth should only be enabled when:

- drone bootstrap has received a machine token or equivalent enrollment token
- SITL containers know how to read their token from runtime config
- field scripts and AI agents have their bearer token configured
- the GCS admin can revoke/rotate tokens from Runtime Admin or SSH

## Network Restriction

`MDS_AUTH_ALLOWED_CIDRS` and `MDS_AUTH_TRUSTED_PROXY_CIDRS` are reserved for
network-level hardening. Keep them empty unless the GCS is deployed behind a
known VPN/proxy topology and the deployment has been tested end to end.

For public HTTPS/domain deployments, put MDS behind a maintained reverse proxy
such as Caddy or nginx and set:

```bash
MDS_AUTH_SECURE_COOKIES=true
```

## Operational Checklist

1. Keep auth disabled for quick isolated demos.
2. Enable dashboard login for customer/operator-visible deployments.
3. Create at least one admin and one operator account.
4. Store recovery access through SSH, not browser-only state.
5. Use short-lived tokens for debug and automation.
6. Revoke unused tokens after tests.
7. Enable full API auth only after drone/agent token provisioning is tested.
