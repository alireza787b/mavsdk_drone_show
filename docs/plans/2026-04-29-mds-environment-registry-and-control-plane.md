# MDS Environment Registry And Control Plane Plan

Date: 2026-04-29
Scope: official MDS first, then private client sync after approval
Status: planning only, no implementation yet

## Executive Summary

Your concern is valid. The auth implementation is documented, but the broader
runtime/environment surface has grown large enough that a new developer,
security reviewer, or field operator will not know the complete vocabulary
without reading many scripts.

Current scan result from the official worktree:

- 234 `MDS_*` / `REACT_APP_*` variables were detected.
- Main buckets:
  - security/auth: 23
  - SITL: 47
  - connectivity: 22
  - MAVLink: 18
  - GCS runtime: 21
  - git/release: 21
  - logging: 14
  - frontend build: 12
  - general/bootstrap/runtime: 56

The immediate problem is not that all 234 are wrong. Many are legitimate
separate scopes. The problem is that MDS does not yet have a machine-readable
registry that says:

- which variable is canonical
- which scope owns it
- whether it is secret, host-local, fleet-default, or build-time
- whether it can be edited from UI
- whether a restart/reconcile is required
- which docs and code paths consume it
- which variables are legacy aliases or deprecated

Recommendation: implement an MDS Environment Registry before building a large
environment editor. The UI should be built from that registry, not from ad-hoc
lists.

## Current Findings

## Auth And Tokens

What is already good:

- `docs/guides/gcs-auth.md` documents the three modes:
  - open demo
  - dashboard login
  - full API auth
- `/etc/mds/gcs.env` is the documented GCS auth source of truth.
- `/etc/mds/auth/*` stores user/token/session/CSRF state locally.
- Passwords are hashed.
- API tokens are hashed and plaintext is shown only once.
- Dashboard login and API token enforcement are separate.
- Full API auth has explicit token provisioning steps for current drones, new
  drones, SITL, field scripts, and agents.
- SSH recovery exists through `tools/mds_auth_admin.py`.

Main remaining gap:

- Auth variables are documented in prose, but not registered in a canonical
  metadata file. That means docs, bootstrap, UI, CLI, tests, and future agent
  tools can drift.

## Environment Variable Sprawl

The current surface is split across:

- `deployment/defaults.env`
- `/etc/mds/gcs.env`
- `/etc/mds/local.env`
- `/etc/mds/node_identity.json`
- `tools/local.env.template`
- `tools/mds_gcs_init_lib/gcs_env_config.sh`
- `tools/mds_node_init.sh`
- `app/linux_dashboard_start.sh`
- `gcs-server/start_gcs_server.sh`
- `src/params.py`
- `src/settings/runtime.py`
- `src/settings/deployment_profile.py`
- SITL scripts in `multiple_sitl/`
- React `.env.example`
- guide docs

This is too many places for humans to audit manually.

## Known Alias / Legacy Risk

Some names are still intentionally accepted for compatibility or launcher
bridging, but should be marked clearly:

- `GCS_PORT` vs `MDS_GCS_API_PORT`
- `DASHBOARD_PORT` vs `MDS_DASHBOARD_PORT`
- `REACT_APP_SERVER_URL` is retired; the dashboard uses browser
  auto-detection or `REACT_APP_MDS_SERVER_URL` for explicit split-host builds.
- `REACT_APP_FLASK_PORT` appears in archived docs and should not be a live
  operator-facing setting.
- `MDS_DEFAULT_*` and non-default equivalents are legitimate but confusing
  without metadata. Example: `MDS_DEFAULT_GCS_API_PORT` is fleet default,
  `MDS_GCS_API_PORT` is host/runtime applied value.

Policy recommendation:

- keep only canonical `MDS_*` names in live docs and UI
- mark older non-`MDS_` aliases as launcher compatibility only
- do not let deprecated aliases appear in the new UI except as read-only
  diagnostics

## External Best-Practice Anchors

The design should align with:

- Twelve-Factor config guidance: deploy-specific config belongs outside code.
  Source: https://www.12factor.net/config
- OWASP Secrets Management: centralize/standardize secrets, track lifecycle
  metadata, avoid broad shared secrets, document rotation/revocation.
  Source: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
- Docker secrets guidance: avoid baking secrets into images and prefer file
  based secret injection where possible. Source:
  https://docs.docker.com/engine/swarm/secrets/
- Docker build secrets guidance: build args/env are inappropriate for build
  secrets because they persist into image metadata. Source:
  https://docs.docker.com/build/building/secrets/
- GitHub token guidance: PATs are user-bound; for long-lived organization
  automation, GitHub Apps are preferred. Source:
  https://docs.github.com/en/enterprise-cloud@latest/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- FastAPI security docs support standard auth primitives, but MDS already uses
  a pragmatic local-session plus bearer-token model suitable for field tooling.
  Source: https://fastapi.tiangolo.com/advanced/security/http-basic-auth/

## Recommended Architecture

## 1. Canonical Env Registry

Add a machine-readable registry, for example:

```text
resources/config/mds_env_registry.schema.json
resources/config/mds_env_registry.json
```

Each entry should include:

```json
{
  "name": "MDS_AUTH_ENABLED",
  "title": "Dashboard auth enabled",
  "scope": "gcs",
  "domain": "security",
  "source_of_truth": "/etc/mds/gcs.env",
  "value_type": "boolean",
  "default": false,
  "secret": false,
  "editable": true,
  "ui_visibility": "operator",
  "restart_required": "gcs",
  "apply_action": "restart_gcs",
  "allowed_values": ["true", "false"],
  "deprecated": false,
  "aliases": [],
  "docs": "docs/guides/gcs-auth.md",
  "consumers": [
    "src/security/auth.py",
    "gcs-server/auth_runtime.py",
    "tools/mds_gcs_init_lib/gcs_env_config.sh"
  ],
  "notes": "Enables dashboard login. Does not require machine API tokens unless MDS_API_AUTH_ENABLED is also true."
}
```

Required metadata fields:

- `name`
- `scope`
- `domain`
- `source_of_truth`
- `value_type`
- `default`
- `secret`
- `editable`
- `restart_required`
- `docs`

Useful optional fields:

- `aliases`
- `deprecated`
- `replacement`
- `allowed_values`
- `min`
- `max`
- `pattern`
- `sensitive_display`
- `apply_action`
- `owner`
- `introduced_in`
- `last_reviewed`

## 2. Env Registry Loader

Add typed Python helpers:

```text
src/settings/env_registry.py
```

Responsibilities:

- load and validate `mds_env_registry.json`
- expose registry entries to FastAPI
- validate env update requests
- generate redacted responses
- identify deprecated or unknown keys in live env files
- classify changes as no-restart, GCS restart, node service restart, sidecar
  reconcile, or unsupported

The registry loader should not replace `src/settings/runtime.py` or
`src/settings/deployment_profile.py` immediately. It should become the metadata
authority those systems reference.

## 3. Env File Parser/Writer

Current management code has `_read_env_assignments` and `_persist_env_updates`
inside `gcs-server/api_routes/management.py`.

Recommendation:

- move env parsing/writing into a reusable module:

```text
src/settings/env_files.py
```

Use it for:

- `/etc/mds/gcs.env`
- `/etc/mds/local.env`
- future node env inspection
- tests

Rules:

- preserve comments where practical
- atomic write
- never write raw secret values returned by UI unless the registry explicitly
  allows it
- prefer `*_FILE` for secrets
- record changed keys and required apply action

## 4. API Design

Add a new API family:

```text
GET  /api/v1/system/env/registry
GET  /api/v1/system/env/gcs
PUT  /api/v1/system/env/gcs
POST /api/v1/system/env/gcs/apply

GET  /api/v1/fleet/env/status
GET  /api/v1/fleet/env/{hw_id}
POST /api/v1/fleet/env/batch-plan
POST /api/v1/fleet/env/batch-apply
```

GCS endpoints:

- show current GCS env values using registry metadata
- redact secrets
- validate updates before write
- return restart/reconcile requirement
- use existing auth/CSRF/admin controls

Fleet endpoints:

- start read-only: show reported node env posture from heartbeat/git-status
  summaries
- later: fetch node env details through a controlled drone API endpoint
- batch apply should generate a plan first and require explicit confirmation

Do not let the GCS browser directly edit arbitrary env keys on every drone as a
first version. That is high-risk. Start with registry-approved keys and a
reviewed apply plan.

## 5. Node Env Reporting

Add a node-side status endpoint or heartbeat extension that reports:

- node `hw_id`
- runtime mode
- env file path
- env registry version/hash
- known key values, redacted by registry
- unknown keys
- deprecated keys
- required restart/reconcile actions
- last applied generation

Secrets must report only:

- configured: yes/no
- file path present: yes/no
- file readable by runtime user: yes/no
- health summary

Never return plaintext secret values.

## 6. UI: MDS Environments Page

Yes, an MDS Environments page is a good idea, but only after the registry exists.

Recommended IA:

- Runtime Admin remains for GCS host summary and restart/update actions.
- Fleet Ops remains for fleet-node sync/sidecar posture.
- New page: `Environments`
  - tab 1: GCS Host
  - tab 2: Fleet Nodes
  - tab 3: Batch Plan
  - tab 4: Registry / Deprecated Keys

UX should follow the PX4 Parameters page pattern:

- searchable grouped table
- metadata-aware descriptions
- default/current/effective/source columns
- edit drawer/dialog, not dense inline editing
- badges for restart/reconcile required
- import/export profile
- batch plan before apply
- strong warning for `hw_id`, repo URL, branch, auth, and secret-related keys

Beginner-safe defaults:

- common safe fields editable
- dangerous fields locked behind advanced mode
- secrets never shown
- `*_FILE` values can be edited only by admins and shown as paths/health, not
  contents

Operator-friendly actions:

- export current GCS env snapshot
- export selected drone redacted env snapshot
- import/merge profile
- dry-run batch apply
- apply to selected drones
- restart/reconcile affected services
- open related docs

## 7. Import / Export Profiles

Profile format should not be raw `.env`.

Use structured JSON:

```json
{
  "version": 1,
  "kind": "mds-env-profile",
  "scope": "node",
  "name": "private-fleet-node-defaults",
  "entries": {
    "MDS_MODE": "real",
    "MDS_BRANCH": "main",
    "MDS_MAVLINK_MANAGEMENT_MODE": "managed"
  },
  "secret_refs": {
    "MDS_GIT_AUTH_TOKEN_FILE": "/root/.mds/keys/customer_git_read_token"
  }
}
```

Validation rules:

- reject duplicate keys
- warn if profile includes `MDS_HW_ID`
- warn if profile changes repo/branch
- block raw token values unless explicitly using a secure local-only flow
- show diff before apply

## 8. Documentation Model

Add:

```text
docs/reference/mds-environment-registry.md
docs/guides/mds-environments-page.md
docs/guides/env-profile-import-export.md
```

Then update:

- `docs/guides/runtime-config-sources.md`
- `docs/guides/gcs-auth.md`
- `docs/guides/fleet-sync-and-secrets.md`
- `docs/guides/mds-init-setup.md`
- `docs/guides/headless-automation.md`
- `docs/guides/operator-makefile.md`
- API docs index

Long-term rule:

- docs should reference registry-generated tables where possible
- live docs should not manually duplicate huge variable tables
- archived docs can remain archived but must not be linked as active operator
  guidance

## 9. Security Rules

Auth/token variables:

- keep `MDS_AUTH_ENABLED` and `MDS_API_AUTH_ENABLED` host-local in
  `/etc/mds/gcs.env`
- keep user/token/session state in `/etc/mds/auth`
- keep node API bearer token paths in `/etc/mds/local.env`
- keep token contents in root-only files such as `/root/.mds/keys/gcs_api_token`
- never put raw tokens in git, React build env, Docker images, or visible API
  payloads

UI:

- only admin role can edit auth/env values
- operator/viewer may see redacted status only
- CSRF required for browser mutations
- bearer tokens for API/agent mutation paths

## 10. Implementation Phases

## Phase 0: Confirm Scope

No code beyond this plan.

Decision needed:

- approve building the registry and Environments page
- decide whether the first UI version is GCS-only or GCS plus read-only fleet
  node view

Recommendation:

- implement registry + GCS editor + read-only fleet env posture first
- defer destructive node batch apply until the registry and reporting are stable

## Phase 1: Registry Foundation

Deliverables:

- `resources/config/mds_env_registry.schema.json`
- `resources/config/mds_env_registry.json`
- `src/settings/env_registry.py`
- registry validation tests
- initial registry covering:
  - auth/security variables
  - repo/branch/git auth variables
  - GCS mode/ports
  - node identity/GCS API token variables
  - MAVLink Anywhere variables
  - Smart Wi-Fi variables
  - SITL critical variables

Acceptance:

- every variable in `/etc/mds/gcs.env` template is in registry
- every variable in `tools/local.env.template` is in registry
- registry test fails when a documented env key is missing metadata

## Phase 2: Shared Env File Utilities

Deliverables:

- `src/settings/env_files.py`
- replace duplicate env parser/writer in management route
- tests for comments, atomic write, redaction, invalid keys

Acceptance:

- existing Runtime Admin mode switch still works
- no regression in auth env write/read

## Phase 3: GCS Env API

Deliverables:

- `/api/v1/system/env/registry`
- `/api/v1/system/env/gcs`
- `/api/v1/system/env/gcs` update endpoint
- `/api/v1/system/env/gcs/apply`
- admin-only enforcement
- docs URLs in errors

Acceptance:

- can inspect GCS env with metadata
- can edit safe registry-approved keys
- secrets are redacted
- restart requirement is explicit

## Phase 4: Environments UI, GCS First

Deliverables:

- new `Environments` page
- GCS Host tab
- metadata table, search/group/filter
- edit dialog
- import/export redacted profile
- doc links

Acceptance:

- no raw secret value in DOM/API response
- mobile layout remains usable
- no large always-visible text blocks
- uses design tokens and Operator primitives

## Phase 5: Fleet Node Read-Only Env Posture

Deliverables:

- node env status summary in heartbeat/git status or a lightweight node API
- Fleet Nodes tab in Environments page
- unknown/deprecated/missing key posture
- secret health only as booleans/status, never values

Acceptance:

- operator can see whether each node has expected env registry version/hash
- offline nodes do not generate false warnings
- SITL nodes are classified separately from real hardware nodes

## Phase 6: Batch Plan, Then Apply

Deliverables:

- import env profile
- dry-run plan for selected drones
- show affected keys, risks, restart requirements
- apply only registry-approved non-secret or secret-reference keys
- reconcile/restart action surfaced after apply

Acceptance:

- no accidental `MDS_HW_ID` overwrite across fleet
- duplicate or conflicting keys blocked
- real/SITL mixed-mode guardrails enforced
- audit log records who applied what and when

## Phase 7: Docs And Agent Guidance

Deliverables:

- generated registry reference doc
- update setup/auth/sync guides
- MCP/AI-agent guidance section:
  - how to query registry
  - how to perform dry-run env updates
  - how to avoid secrets
  - how to recover via SSH

Acceptance:

- new developer starts from one reference page
- security reviewer can see all auth/token variables in one place
- operator can follow UI or CLI path without conflicting instructions

## Phase 8: Private Sync And Live Validation

Deliverables:

- official commit/tag/release first
- cherry-pick/sync to private repo
- deploy to Hetzner
- test dashboard auth stays enabled
- verify board 2 sync unaffected
- verify SITL mode unaffected

## What Not To Do

- Do not build a free-form `.env` editor first.
- Do not expose secret values in browser responses.
- Do not allow batch setting `MDS_HW_ID`.
- Do not let deprecated aliases become first-class UI options.
- Do not make node env batch apply happen without a dry-run plan.
- Do not move secret contents into git-tracked profiles.

## Recommendation

Proceed with Phase 1 and Phase 2 first.

Reason:

- they reduce confusion without changing runtime behavior
- they create the metadata foundation for the UI
- they let tests catch future env drift
- they make auth/token documentation auditable by experts

After that, build the GCS-only Environments page, then add read-only fleet node
posture. Batch apply should be last, not first.
