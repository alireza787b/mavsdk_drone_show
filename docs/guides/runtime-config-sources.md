# Runtime Config Sources

This guide is the source of truth for where MDS runtime configuration lives.

Use it whenever there is ambiguity between:

- repo files such as `config.json`, `swarm.json`, or `src/params.py`
- GCS host runtime files such as `/etc/mds/gcs.env`
- node runtime files such as `/etc/mds/local.env`
- SITL launch-time environment variables

## Ownership Model

| Concern | Real source of truth | Notes |
|--------|-----------------------|-------|
| Real fleet membership | `config.json` | GCS-side repo file |
| Real swarm topology | `swarm.json` | GCS-side repo file |
| SITL fleet membership | `config_sitl.json` | Selected when `real.mode` is absent |
| SITL swarm topology | `swarm_sitl.json` | Selected when `real.mode` is absent |
| GCS host runtime overrides | `/etc/mds/gcs.env` | Repo/branch/auth/launcher behavior for the GCS host |
| Node runtime overrides | `/etc/mds/local.env` | `MDS_HW_ID`, GCS routing, repo/branch/auth overrides for that node |
| Node identity metadata | `/etc/mds/node_identity.json` | Bootstrap identity/reporting metadata |
| Fallback defaults and runtime policy | `src/params.py` | Only when host env files or explicit process env are absent |

## Effective Precedence

### Python runtime on a node

`src/params.py` preloads `/etc/mds/local.env` into `os.environ` only for keys that
are not already set. That means the effective order is:

1. process environment
2. `/etc/mds/local.env`
3. hardcoded defaults in `src/params.py`

### Node announce URL resolution

`mds_node_announce.sh` resolves the GCS API URL in this order:

1. explicit `--gcs-api-url`
2. `MDS_GCS_API_BASE_URL` in process env
3. `MDS_GCS_API_BASE_URL` in `/etc/mds/local.env`
4. `MDS_GCS_IP` plus the default API port (`5000`)

### GCS backend runtime

`gcs-server/start_gcs_server.sh` sources `/etc/mds/gcs.env` before launching the
backend. Those exported values take precedence over repo fallback defaults in
`src/params.py`.

## What Not To Do

Do not use `src/params.py` as the normal place to store:

- a node’s hardware ID
- a deployment-specific GCS IP
- customer-specific host secrets or token file paths
- day-2 operational runtime changes

Do not expect Fleet Enrollment to rewrite swarm topology automatically.

- enrollment updates `config.json`
- swarm relationships still live in `swarm.json`

## Recommended Operator Workflow

### Real hardware

1. bootstrap the GCS host and write `/etc/mds/gcs.env`
2. bootstrap each node and write `/etc/mds/local.env`
3. use Fleet Enrollment to add real nodes into `config.json`
4. manage swarm relationships through `swarm.json` or the GCS swarm UI/APIs

### SITL

1. use `config_sitl.json` and `swarm_sitl.json`
2. export `MDS_REPO_URL`, `MDS_BRANCH`, and optional auth env vars before launch when needed
3. avoid editing `src/params.py` just to point SITL at a different repo or branch

## Practical Rule

If the change is:

- host-specific -> `/etc/mds/gcs.env` or `/etc/mds/local.env`
- fleet/swarm membership -> `config*.json` / `swarm*.json`
- repo-wide fallback or runtime policy -> `src/params.py`
