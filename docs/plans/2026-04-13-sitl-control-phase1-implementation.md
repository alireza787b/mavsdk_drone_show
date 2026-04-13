# SITL Control Phase 1 Implementation

Date: 2026-04-13

## Summary

Implemented the first official `System -> SITL Control` page and its backend
supervisor API in the clean official worktree.

Phase 1 scope:

- Docker-backed host/image/instance inventory
- tracked lifecycle mutations
  - reconcile fleet
  - restart one instance
  - remove one instance
- instance log tail endpoint
- responsive dashboard page with beginner defaults and folded advanced fields

Explicitly out of scope in V1:

- browser shell / host bash
- generic Docker admin
- image build / publish

## Key Design Decisions

1. The browser talks only to typed GCS endpoints.
2. The backend reuses the canonical `multiple_sitl/create_dockers.sh` launcher.
3. Lifecycle mutations are tracked as MDS operations instead of raw shell jobs.
4. Custom image selection is allowed, but defaults stay beginner-safe.
5. Terminal access remains deferred.

## Code Added

Backend:

- `src/sitl_control_models.py`
- `src/sitl_control_service.py`
- `gcs-server/api_routes/sitl_control.py`
- route registration in `gcs-server/app_fastapi.py`

Frontend:

- `src/services/sitlControlService.js`
- `src/pages/SitlControlPage.js`
- `src/styles/SitlControlPage.css`
- route wiring in `App.js`
- menu entry in `SidebarMenu.js`

Tests:

- `tests/test_sitl_control_service.py`
- `tests/test_gcs_sitl_control_routes.py`
- `src/services/sitlControlService.test.js`
- `src/pages/SitlControlPage.test.js`
- route inventory updated in `tests/test_api_route_inventory.py`

## Additional Fixes Found During Live Validation

### 1. CRA dev-server proxy drift

The dashboard already uses absolute API URLs from `apiConfig`, so the old
`package.json` `proxy` entry was unnecessary. On Hetzner that stale proxy value
caused webpack-dev-server to generate an invalid `allowedHosts` config and the
dashboard refused to start.

Fix:

- removed the stale dashboard `proxy` entry

### 2. CRA dev-server memory pressure

The dashboard dev server hit Node heap exhaustion on the Hetzner VPS.

Fix:

- raised the dashboard dev-server heap via the `start` script:
  `NODE_OPTIONS=--max-old-space-size=4096`

### 3. `start_gcs_server.sh` mode drift

The launcher was documented and used like an executable script, but the file
mode in git was not executable.

Fix:

- restored executable mode for `gcs-server/start_gcs_server.sh`

### 4. Route test harness drift

The initial route tests used `TestClient(app)` and hit a FastAPI/anyio
lifespan deadlock unrelated to SITL Control itself.

Fix:

- rewrote the route behavior tests to invoke the registered async route
  endpoints directly

## Validation

### Local focused tests

- backend:
  - `tests/test_sitl_control_service.py`
  - `tests/test_gcs_sitl_control_routes.py`
  - `tests/test_api_route_inventory.py::test_gcs_business_route_inventory`
  - result: `11 passed`
- frontend:
  - `src/services/sitlControlService.test.js`
  - `src/pages/SitlControlPage.test.js`
  - result: `7 passed`

### Live Hetzner validation

Validated against the temporary official runtime tree:

- backend health: passed
- SITL Control policy/host/images/instances: passed
- dashboard `/sitl-control` render: passed
- reconcile to `3`: passed
- restart `drone-1`: passed
- remove `drone-3`: passed
- reconcile back to `3`: passed
- telemetry convergence back to `3/3 ready`: passed

## Remaining Boundary

Still intentionally deferred:

- browser shell / terminal access
- image build/publish controls
- production static build stabilization beyond the SITL Control scope

This checkpoint is the first official live-validated SITL Control V1 slice.
