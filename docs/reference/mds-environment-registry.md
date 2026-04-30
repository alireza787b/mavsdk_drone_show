# MDS Environment Registry

The MDS environment registry is the canonical source for active environment
variable metadata.

## Files

| File | Purpose |
|---|---|
| `resources/config/mds_env_registry.json` | Active registry entries |
| `resources/config/mds_env_registry.schema.json` | JSON schema for the registry shape |
| `resources/config/mds_env_internal_allowlist.json` | Explicit list of active process-only `MDS_*` variables that are not operator-editable |
| `src/settings/env_registry.py` | Typed loader, validation, redaction, and value coercion |
| `src/settings/env_files.py` | Shared `.env` parser and atomic writer |
| `tools/audit_mds_env_registry.py` | Repository audit that fails on unregistered and unclassified active `MDS_*` references |
| `tools/generate_mds_env_reference.py` | Generates the markdown registry table from JSON |

## Policy

- Active operator-facing keys use canonical `MDS_*` names.
- Operator-editable or persisted runtime keys must be represented in
  `mds_env_registry.json`.
- Process-only launcher, build, test, and sidecar internals must be represented
  in `mds_env_internal_allowlist.json` with a reason.
- Raw secret values are not registry entries and are not accepted through
  environment APIs.
- Secret files are represented by path variables such as `*_FILE`.
- `GCS_PORT` and `DASHBOARD_PORT` are retired from active setup and launcher paths.
- `MDS_GIT_AUTH_TOKEN` and `MDS_GCS_API_TOKEN` are intentionally unsupported;
  use `MDS_GIT_AUTH_TOKEN_FILE` and `MDS_GCS_API_TOKEN_FILE`.
- `MDS_HW_ID` is never batch-applied because it is unique per node.
- Node-wide batch apply must use dry-run planning before mutation.
- No active `MDS_*` key may be left undocumented by both the registry and the
  internal allowlist.

## Generated Reference

The key table is generated from `resources/config/mds_env_registry.json`:

- [Generated MDS Environment Registry](mds-environment-registry.generated.md)

Regenerate or check it during review:

```bash
python3 tools/generate_mds_env_reference.py --write
python3 tools/generate_mds_env_reference.py --check
```

## API

The GCS exposes registry-backed inspection endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/system/env/registry` | Return registry metadata |
| `GET` | `/api/v1/system/env/gcs` | Return current GCS env posture |
| `PUT` | `/api/v1/system/env/gcs` | Persist registry-approved GCS env updates |
| `POST` | `/api/v1/system/env/gcs/apply` | Restart the GCS when persisted env changes require it |
| `POST` | `/api/v1/system/env/fleet/plan` | Dry-run node-scoped env rollout plan without mutating drones |

Mutation is intentionally limited to GCS-local keys. Fleet nodes report env
posture through their canonical `GET /api/v1/git/status` payload, which the GCS
already polls for Fleet Ops. `POST /api/v1/system/env/fleet/plan` validates
node-scoped updates against the same registry and returns a per-node dry-run
plan. Actual node mutation remains blocked until node-side identity-safe apply
APIs exist.

## Dashboard

The dashboard exposes the same GCS-local control surface at:

```text
/environments
```

Use this page for host-local, registry-approved GCS variables and read-only
fleet-node env posture. The GCS Host tab shows the loaded registry hash, env
file path, unknown or retired keys, and restart-sensitive values. The Fleet
Nodes tab shows registry hash, local env presence, identity presence, runtime
mode, and key-count/drift summaries without exposing values.

Operator rules:

- Use `GCS Runtime` for mode switching and controlled runtime updates.
- Use `Environments` for typed GCS env inspection and small approved edits.
- Use `Fleet Ops` for drone-node sync, git posture, and sidecar posture.
- Do not put raw secrets in env values; reference secret files instead.

## Recovery

If the dashboard auth or env UI is unavailable, recover through SSH:

```bash
sudo editor /etc/mds/gcs.env
sudo python3 tools/mds_auth_admin.py list-users
sudo python3 tools/mds_auth_admin.py reset-password admin
```

After changing restart-sensitive GCS env values, relaunch through the canonical
dashboard launcher.
