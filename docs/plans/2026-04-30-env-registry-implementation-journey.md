# Env Registry Implementation Journey

Date: 2026-04-30
Scope: official MDS first
Status: GCS env control plane, UI, and active legacy-env cleanup complete

## Completed

- Added the canonical env registry schema:
  - `resources/config/mds_env_registry.schema.json`
- Added the initial canonical env registry:
  - `resources/config/mds_env_registry.json`
- Added typed registry loader/validator/redaction/coercion:
  - `src/settings/env_registry.py`
- Added shared env-file parser/writer with atomic updates:
  - `src/settings/env_files.py`
- Migrated runtime and deployment-profile parsing to the shared env-file helper.
- Migrated GCS management env persistence to the shared env-file helper.
- Added registry-backed GCS env APIs:
  - `GET /api/v1/system/env/registry`
  - `GET /api/v1/system/env/gcs`
  - `PUT /api/v1/system/env/gcs`
  - `POST /api/v1/system/env/gcs/apply`
- Retired active `GCS_PORT` and `DASHBOARD_PORT` setup/launcher aliases.
- Removed deprecated `Params.GCS_PORT`/Flask-style port aliases.
- Updated docs and route inventory for the new env control-plane API.
- Added the dashboard `Environments` page for GCS-local registry-approved env
  inspection and edits.
- Env edit dialogs now expose registry docs through the standard dashboard
  docs-link component instead of showing raw doc paths as inert text.
- Added GCS env profile export/import UI:
  - exports only editable non-secret GCS values
  - imports only `kind=mds-env-profile`, `scope=gcs`
  - performs a registry API dry-run before showing the confirmation dialog
  - writes through the existing registry-approved GCS env API
- Added frontend route, sidebar entry, docs shortcut, API client bindings, and
  page/service tests for the Environments surface.
- Added `allowed_values` to the GCS env value payload so constrained values
  render as safe selects instead of free-text fields.
- Added read-only node env posture reporting through each drone's canonical
  `GET /api/v1/git/status` payload.
- Added the Environments page `Fleet Nodes` tab for node registry hash,
  identity/local-env presence, runtime mode, and drift counts without exposing
  env values.
- Removed active `.hwID` rcS compatibility helpers and moved the old hw_id/pos_id
  research report into `docs/archives`.
- Removed the active SITL `-s` simulator-mode flag and stale rcS helper naming;
  Docker SITL now exposes one supported simulator path: headless PX4 Gazebo
  Harmonic with launch-time `PX4_PARAM_*` overrides.
- Removed the old `DRONE_BRANCH` repository-sync fallback; repo sync now uses
  CLI arguments, canonical `MDS_BRANCH`, or deployment defaults.
- Removed the stale `run_mavlink_guidance_phase` setup alias; hardware bootstrap
  uses `run_mavlink_setup_phase`.
- Removed active raw token env fallbacks. Git HTTPS auth and GCS API bearer auth
  now use file-based secret references only:
  - `MDS_GIT_AUTH_TOKEN_FILE`
  - `MDS_GCS_API_TOKEN_FILE`
- Tightened heartbeat runtime-mode fencing so nodes must declare canonical
  `runtime_mode=real|sitl`; aliases or missing values are rejected.
- Added a registry docs-link guard and fixed missing env help targets:
  - `docs/guides/connectivity-runtime.md`
  - `docs/guides/logging-system.md`
  - `docs/px4-parameters.md`
- Added an active `MDS_*` reference audit:
  - `resources/config/mds_env_internal_allowlist.json`
  - `tools/audit_mds_env_registry.py`
  - operator/persisted keys must be in the registry
  - process-only launcher/build/test/sidecar internals must be explicitly
    classified in the allowlist
- Added generated env reference documentation:
  - `tools/generate_mds_env_reference.py`
  - `docs/reference/mds-environment-registry.generated.md`
  - pytest now fails if the generated reference table drifts from the registry
- Removed remaining active frontend/backend legacy config islands:
  - dashboard advanced server override is now `REACT_APP_MDS_SERVER_URL`
  - launch/setup scripts migrate and remove stale `REACT_APP_SERVER_URL`
  - removed unused `gcs-server/env_updater.py`
  - removed `GCS_BACKEND` from GCS env generation and launcher exports because
    FastAPI is the only active backend
- Added fleet-node env dry-run planning:
  - `POST /api/v1/system/env/fleet/plan`
  - validates only registry-approved node-scoped editable keys
  - resolves requested or configured target nodes
  - reports per-node registry-hash drift, local-env availability, warnings, and
    restart/apply actions
  - does not mutate drones; node-side apply remains intentionally disabled

## Guardrails Added

- Registry tests fail if `deployment/defaults.env` or `tools/local.env.template`
  reference an `MDS_*` key that is not registered.
- Registry tests fail if any registry entry points to a missing documentation
  file.
- Registry tests fail if active code references an `MDS_*` key that is neither
  registered nor explicitly classified as an internal/process-only variable.
- Registry tests fail if the generated env reference markdown is stale.
- Registry update API rejects:
  - unknown keys
  - node keys sent to the GCS env endpoint
  - raw secret env names that are intentionally not registered
  - non-editable keys
- GCS env API redacts secret values and reports stale unknown keys separately.

## Tests

Focused tests passed:

```bash
python3 -m pytest \
  tests/test_env_registry.py \
  tests/test_env_files.py \
  tests/test_runtime_settings.py \
  tests/test_gcs_management_routes.py \
  tests/test_api_route_inventory.py

python3 -m pytest \
  tests/test_bootstrap_installers.py::test_configure_gcs_env_rewrites_stale_ports \
  tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_optional_auth_and_first_admin

python3 tools/audit_frontend_ui.py --strict

python3 -m pytest \
  tests/test_runtime_settings.py \
  tests/test_heartbeat_runtime_mode.py \
  tests/test_gcs_management_routes.py \
  tests/test_env_registry.py \
  tests/test_gcs_auth_client.py

python3 -m pytest \
  tests/test_env_registry.py \
  tests/test_env_files.py \
  tests/test_runtime_settings.py \
  tests/test_heartbeat_runtime_mode.py \
  tests/test_gcs_auth_client.py \
  tests/test_mds_git_access_check.py \
  tests/test_gcs_management_routes.py \
  tests/test_bootstrap_installers.py::test_sitl_launchers_use_canonical_mds_hw_id_without_runtime_hwid_files \
  tests/test_env_status.py \
  tests/test_gcs_git_routes.py::test_git_status_exposes_read_only_node_env_posture \
  tests/test_api_route_inventory.py

python3 tools/audit_frontend_ui.py --strict

git diff --check

python3 tools/audit_mds_env_registry.py
```

Latest focused result: `49 passed`; frontend UI audit and `git diff --check`
both passed.

Additional focused result after profile import/export and docs-link guard:
`7 passed` for env registry and GCS env update routes; frontend UI audit and
`git diff --check` both passed.

Additional focused result after active-env audit guard: `python3
tools/audit_mds_env_registry.py` passed with `85` registered active keys, `139`
classified internal keys, and `0` unclassified keys.

Additional focused result after fleet env dry-run planning: `53 passed` for
the env registry, env files, runtime settings, heartbeat runtime-mode fencing,
GCS auth client, git access check, GCS management routes, SITL launcher identity
guard, node env status, git-status env posture, and API route inventory suite.
The inventory guard now includes `POST /api/v1/system/env/fleet/plan`.

Hetzner frontend validation passed from an isolated validation copy:

```bash
cd /root/mds_validation_env_20260430/app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watchAll=false \
  src/services/gcsApiService.test.js \
  src/pages/EnvironmentsPage.test.js
npm run build
```

Result: `39 passed`; production build completed. The CRA bundle-size warning is
known for the current dashboard bundle and is not caused by this env slice.

Frontend Jest was authored for the new page and service bindings, but not run
in this clean workspace because `react-scripts` is not installed here. Run it on
the Hetzner validation host:

```bash
cd app/dashboard/drone-dashboard
npm test -- --runInBand --watchAll=false \
  src/services/gcsApiService.test.js \
  src/pages/EnvironmentsPage.test.js
```

## Remaining Slices

- Sync the official release state into the client repo after local focused
  validation passes.

## 2026-05-01 Slice: Single-Node Fleet Env Repair

The Fleet Nodes tab is no longer only a posture summary. Selecting a reachable
node now opens a GCS-proxied, PX4-parameter-style local env inspector/editor.

Implemented:

- drone API `GET /api/v1/system/env`
- drone API `PUT /api/v1/system/env`
- GCS proxy `GET /api/v1/system/env/fleet/nodes/{hw_id}`
- GCS proxy `PUT /api/v1/system/env/fleet/nodes/{hw_id}`
- selected-node env list/edit/import/export in `/environments`
- docs updates for runtime config, GCS API, drone API, and registry reference
- deferred sidecar auth/subnet TODO for `mavlink-anywhere` and
  `smart-wifi-manager`

Policy retained:

- raw secret env values stay redacted and non-editable
- single-node edits are for field repair/staging
- bulk fleet env mutation stays dry-run only; durable changes belong in the
  repo/bootstrap source of truth

Focused validation:

```bash
python3 -m py_compile \
  src/settings/env_status.py \
  src/drone_api_server.py \
  gcs-server/api_routes/management.py \
  gcs-server/schemas.py

python3 -m pytest \
  tests/test_env_status.py \
  tests/test_drone_api_http.py::TestNodeEnvironment \
  tests/test_gcs_management_routes.py::test_management_router_registers_expected_routes \
  tests/test_gcs_management_routes.py::test_management_router_proxies_single_node_env \
  tests/test_gcs_management_routes.py::test_management_router_proxies_single_node_env_update -q

git diff --check
```

Result: focused backend/env tests passed. Frontend validation passed on Hetzner:

```bash
cd /root/mds_validation_env_20260501/app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watchAll=false \
  src/services/gcsApiService.test.js \
  src/pages/EnvironmentsPage.test.js
npm run build
```

Result: `39 passed`; production build completed. The CRA bundle-size warning
remains known dashboard maintenance debt, not a regression from this slice.
