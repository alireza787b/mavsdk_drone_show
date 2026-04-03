# API Modernization Blueprint

Date: 2026-04-03
Status: In progress
Owner: API audit / modernization stream

## Purpose

This document is the source of truth for the API cleanup and migration effort across:

- GCS FastAPI HTTP routes
- GCS WebSocket and SSE streams
- drone-side FastAPI HTTP routes
- internal runtime HTTP callbacks between drones and GCS
- frontend API consumption patterns
- future MCP and AI-agent integration

## Why This Work Exists

The current API surface is mixed-generation:

- legacy verb-style routes like `/get-config-data`, `/save-swarm-data`, `/import-show`
- newer domain routes like `/api/logs/*`, `/api/sar/*`, `/api/swarm/trajectory/*`
- historically included unprefixed operational routes like `/health`, `/submit_command`, and `/git-status`
- duplicate or overlapping contracts like `/telemetry` vs `/api/telemetry`, `/heartbeat` vs `/drone-heartbeat`, `/get-network-status` vs `/get-network-info`

The result is workable but hard to extend cleanly, easy to document incorrectly, and not ideal for future MCP / LLM automation.

## Current Inventory Snapshot

As of 2026-04-03:

- GCS FastAPI main app exposes 71 HTTP/WebSocket routes in `gcs-server/app_fastapi.py`
- GCS log router exposes 11 routes under `/api/logs`
- GCS QuickScout router exposes 12 routes under `/api/sar`
- drone API exposes 15 HTTP/WebSocket routes in `src/drone_api_server.py`

Important active consumer groups:

- React dashboard pages and hooks
- frontend service wrappers
- drone runtime callbacks to GCS
- mission runtime code and SITL validation tools

Important migration hazards:

- frontend calls are spread across pages, hooks, utilities, and service files
- route changes without an adapter layer will break working mission flows
- some stale consumers already exist and cannot be treated as active compatibility requirements
- transport, file IO, git side effects, and orchestration are still mixed inside route handlers

## Design Goals

The target API must be:

- modular by subsystem
- versioned
- explicit about canonical vs compatibility routes
- typed where practical
- safe for CI and contract testing
- predictable for future MCP exposure
- usable by browser UI, desktop clients, automation, and LLM agents
- backward-compatible during migration
- ready for authentication and authorization layers even when auth stays disabled in current dev/demo environments
- backed by one current consumer path per domain instead of multiple parallel legacy frontend surfaces

## Naming Standard

Canonical routes will use:

- prefix: `/api/v1/...`
- nouns and subresources instead of `get-*` / `save-*` verbs
- stable plural collections where appropriate
- consistent path structure across GCS and drone services

Legacy routes remain temporarily available as compatibility aliases until the frontend, tooling, and runtime callers have been migrated and verified.

## Contract Standard

Canonical v1 routes should follow these rules:

- read routes return typed resource payloads or typed collection payloads
- mutation routes return explicit operation results with stable identifiers when side effects are asynchronous or multi-step
- errors should converge toward structured problem responses instead of ad hoc strings
- streams should converge on a documented event model instead of subsystem-specific one-offs

## Security and Auth Readiness Rules

Auth remains disabled for current development and demo workflows, but the contract must stay ready for future customer deployments that require it.

Canonical routes and service wrappers should therefore:

- keep clear subsystem boundaries so auth policy can be attached by router/domain later without rewriting every caller
- favor explicit resource IDs, target scopes, and operator intent in request bodies so later policy checks are machine-readable
- preserve stable response metadata and timestamps so future audit/auth layers do not require a second response redesign
- avoid page-owned secret handling or direct URL assembly in the frontend
- document any privileged mutation surfaces clearly so later token/session enforcement can be enabled without guesswork

This work does not enable auth yet. It keeps the API and frontend shape compatible with adding auth cleanly later.

## MCP and AI-Agent Readiness Rules

To support future MCP servers and LLM-based control flows, canonical routes should:

- use stable resource names and predictable JSON shapes
- expose typed metadata and timestamps
- prefer explicit IDs and scopes over UI-specific labels
- separate reads from control mutations
- preserve enough machine-readable context for tool execution, retries, and postmortem analysis

This work should make it straightforward to expose a later MCP layer without inventing a second parallel contract.

## Phase Plan

### Phase 1

- survey current GCS and drone routes
- map codebase consumers
- publish this blueprint
- introduce low-risk canonical `/api/v1/...` aliases for core health, telemetry, heartbeat, and drone control surfaces
- add tests for those aliases

### Phase 2

- centralize frontend API access behind typed service modules
- remove direct page-level ad hoc endpoint usage where practical
- classify stale consumers and dead routes

Phase 2 core checkpoint on 2026-04-03:

- introduced a shared semantic route/service layer in `app/dashboard/drone-dashboard/src/services/gcsApiService.js`
- migrated the highest-traffic dashboard/config/origin/command consumers onto that layer
- added focused frontend service tests and Hetzner-backed production-build validation
- left dynamic swarm-trajectory management routes, logs/SAR shared services, and show-management/download/static-asset URL builders for the next slice

Phase 2 completion checkpoint on 2026-04-03:

- migrated the remaining active frontend API callers in Drone Show import/export/visualization, Custom Show, QuickScout, Mission Details, and Swarm Trajectory onto shared route/service helpers
- centralized remaining log and SAR service route composition behind shared builders and dedicated tests
- removed the dead unrouted `ImportShow` / `FileUpload` path instead of preserving stale frontend compatibility code
- added a shared API error normalizer for page/service mutation flows
- hardened the dashboard build script for the Hetzner Node 22 runtime by setting an explicit heap budget and disabling production sourcemaps

### Phase 3

- extract GCS route domains out of `app_fastapi.py`
- extract drone route domains out of `drone_api_server.py`
- move shared route logic behind service functions instead of handler-local behavior

Phase 3 first checkpoint on 2026-04-03:

- extracted the first coherent GCS route domain into `gcs-server/api_routes/core.py`
- moved health, telemetry, heartbeat, and heartbeat-derived network-status routes behind `create_core_router(...)` while preserving the existing HTTP/WebSocket surface
- kept backend compatibility/patch seams stable by having the extracted router read attributes from the live `app_fastapi` module object at request time instead of capturing handler references during import
- added focused router-level coverage in `tests/test_gcs_core_routes.py`
- revalidated the extracted surface locally and on Hetzner with the combined `test_gcs_core_routes.py` and `test_gcs_api_http.py` batch

Phase 3 second checkpoint on 2026-04-03:

- extracted the configuration routes into `gcs-server/api_routes/configuration.py`
- extracted the Swarm configuration and Smart Swarm reassignment routes into `gcs-server/api_routes/swarm.py`
- moved swarm-cycle validation into that router module instead of leaving it as file-local logic inside `app_fastapi.py`
- preserved the existing live `/get-config-data`, `/save-config-data`, `/validate-config`, `/get-drone-positions`, `/get-trajectory-first-row`, `/get-swarm-data`, `/save-swarm-data`, and `/request-new-leader` routes while keeping the same patchable dependency seam through the live `app_fastapi` module object
- preserved `400` for invalid configuration payload shape instead of flattening that specific contract error into a generic `500`
- updated the extracted mutable-router git paths to use `asyncio.get_running_loop()`
- added focused router-level coverage in `tests/test_gcs_configuration_routes.py` and `tests/test_gcs_swarm_routes.py`
- revalidated the combined extracted-router surface locally and on Hetzner with `test_gcs_configuration_routes.py`, `test_gcs_swarm_routes.py`, `test_gcs_core_routes.py`, and `test_gcs_api_http.py`

Phase 3 third checkpoint on 2026-04-03:

- extracted the Git routes into `gcs-server/api_routes/git_status.py`
- moved `/git-status`, `/sync-repos`, `/ws/git-status`, `/get-gcs-git-status`, and `/get-drone-git-status/{drone_id}` behind `create_git_router(...)`
- kept the sync helper functions and state in `app_fastapi.py` for this slice so the existing patch-driven backend tests can keep the same hook surface while the route layer leaves the monolith
- added focused router-level coverage in `tests/test_gcs_git_routes.py`
- revalidated the combined extracted-router surface locally and on Hetzner with `test_gcs_git_routes.py`, `test_gcs_configuration_routes.py`, `test_gcs_swarm_routes.py`, `test_gcs_core_routes.py`, `test_gcs_api_http.py`, and `test_gcs_api_websocket.py`

Phase 3 fourth checkpoint on 2026-04-03:

- extracted the Origin domain into `gcs-server/api_routes/origin.py`
- moved `/get-origin`, `/set-origin`, `/get-gps-global-origin`, `/elevation`, `/get-origin-for-drone`, `/get-position-deviations`, `/compute-origin`, and `/get-desired-launch-positions` behind `create_origin_router(...)`
- moved the richer origin-domain geometry/report builders into `gcs-server/origin.py`, including the reusable launch-position export payload and deviation-report helpers instead of keeping those calculations embedded in `app_fastapi.py`
- fixed a latent backend bug in `compute_origin_from_drone(...)` by restoring the missing `pyproj` imports, which previously left the compute-origin path vulnerable to runtime failure when exercised outside mocks
- corrected the origin contract so `POST /compute-origin` is now a dry-run compute surface that returns the candidate origin without mutating shared origin state; `POST /set-origin` remains the explicit write path
- corrected the command `auto_global_origin` path so valid `0.0` latitude/longitude origins are preserved instead of being dropped by truthiness checks
- added focused router-level coverage in `tests/test_gcs_origin_routes.py`, added a broad HTTP test for `/compute-origin`, and added a duplicate-method/path guard to `tests/test_api_route_inventory.py`
- revalidated the combined extracted-router surface locally and on Hetzner with `test_gcs_origin_routes.py`, `test_gcs_git_routes.py`, `test_gcs_configuration_routes.py`, `test_gcs_swarm_routes.py`, `test_gcs_core_routes.py`, `test_gcs_api_http.py`, `test_gcs_api_websocket.py`, and `test_api_route_inventory.py`

Phase 3 fifth checkpoint on 2026-04-03:

- extracted the remaining small GCS management/static compatibility cluster into `gcs-server/api_routes/management.py` and `gcs-server/api_routes/static_assets.py`
- moved `/get-gcs-config`, `/save-gcs-config`, `/get-network-info`, and `/static/plots/{filename}` behind router factories that still resolve live dependencies from the `app_fastapi` module object at request time
- corrected the `save-gcs-config` compatibility contract so the endpoint now returns an explicit stub acknowledgement with `success=true`, `persisted=false`, and warnings instead of implying that persistence succeeded
- hardened static plot serving with bounded path resolution instead of direct path joining, which removes the path-traversal risk from the compatibility file-serving surface
- moved the frontend `MissionReadinessCard` static-plot consumer onto the shared `buildStaticPlotUrl(...)` helper so route composition stays single-sourced during backend extraction
- fixed the project test-tooling contract by adding `pytest-timeout` to the `dev` extra and removing the ignored duplicate pytest config from `pyproject.toml`, leaving `pytest.ini` as the single test-config source of truth
- revalidated the extracted-router surface on Hetzner with a validation-only `.venv` built from `python -m pip install -e ".[dev]"`, then ran the combined backend batch plus the dashboard production build successfully

Phase 3 sixth checkpoint on 2026-04-03:

- extracted the remaining Drone Show / Custom Show management routes into `gcs-server/api_routes/show_management.py`
- moved the supporting show-domain helpers out of `app_fastapi.py` into `gcs-server/show_management.py`, while keeping compatibility wrappers on the `app_fastapi` module object so existing patch-driven tests and future auth/MCP wrapping still target one live dependency surface
- preserved the existing live show routes: `/import-show`, `/download-raw-show`, `/download-processed-show`, `/get-show-info`, `/get-custom-show-info`, `/import-custom-show`, `/get-comprehensive-metrics`, `/get-safety-report`, `/validate-trajectory`, `/deploy-show`, `/get-show-plots`, `/get-show-plots/{filename}`, and `/get-custom-show-image`
- corrected multiple show-domain contract issues during extraction:
  - `deploy-show` now accepts standard JSON content-type variants such as `application/json; charset=utf-8`
  - trajectory validation no longer downgrades a safety `FAIL` back to `WARNING` later in the same pass
  - show plot file serving now uses bounded path resolution instead of direct path joins
  - show plot listing no longer creates directories as a side effect when nothing has been generated yet
  - async show handlers now use `asyncio.get_running_loop()` instead of `get_event_loop()`
- added focused router-level coverage in `tests/test_gcs_show_management_routes.py` plus new HTTP regressions for the deploy-header and validation-status fixes
- refreshed the human-facing API doc in `docs/apis/gcs-api-server.md` so the custom-show endpoints and expanded show import response are documented alongside the standard show-management surfaces
- revalidated the extracted-router surface locally and on Hetzner with the combined backend batch, then reran the Hetzner dashboard production build successfully

Phase 3 seventh checkpoint on 2026-04-03:

- extracted the full Swarm Trajectory management surface into `gcs-server/api_routes/swarm_trajectory.py`
- moved `GET /api/swarm/leaders` plus the 14 `/api/swarm/trajectory/*` routes behind `create_swarm_trajectory_router(...)`, while keeping the live dependency seam request-time-bound to the `app_fastapi` module object so existing patch-driven tests and future auth/MCP wrapping still target one current module surface
- preserved the current live route names and binary download behavior instead of starting canonical `/api/v1/...` renames in the same slice
- corrected a real route-layer contract bug during extraction: `process` and `commit` now return `400` for malformed JSON or non-object JSON payloads instead of surfacing those client errors as generic `500`s
- added focused router-level coverage in `tests/test_gcs_swarm_trajectory_routes.py` for route registration, live dependency lookup, runtime policy reads, and the new request-body validation behavior
- removed the stale unused Flask-era `gcs-server/swarm_trajectory_routes.py` file after confirming it was no longer mounted anywhere in the live FastAPI application, leaving the extracted router as the single current Swarm Trajectory route definition in the repo
- revalidated the extracted-router surface locally with the focused swarm-trajectory/inventory batch, locally with the full extracted-router backend batch, and on Hetzner with the same backend batch plus the dashboard production build

Phase 3 eighth checkpoint on 2026-04-03:

- extracted the remaining Commands REST surface into `gcs-server/api_routes/commands.py`
- moved `/submit_command`, `/command/{command_id}`, `/commands/recent`, `/commands/active`, `/commands/statistics`, `/command/{command_id}/cancel`, `/command/execution-result`, and `/command/execution-start` behind `create_command_router(...)`
- kept the live dependency seam request-time-bound to the `app_fastapi` module object so existing patch-driven tests and future auth/MCP wrapping still resolve one current dependency surface during the extraction
- moved the command-only target-telemetry and altitude-budget helpers out of `app_fastapi.py` and into the extracted router module so the command domain keeps its own route-local helper logic
- corrected multiple real command-route contract issues during extraction:
  - `submit_command` now returns `400` for malformed JSON request bodies
  - `submit_command` now returns `400` for non-object JSON bodies instead of failing later with generic server errors
  - `submit_command` now returns `400` when `target_drones` is not an array-like identifier set
  - `submit_command` now returns `400` when an explicit `target_drones` selection matches no configured drones instead of creating an ambiguous zero-target command record
- aligned the helper schemas and human-facing command API docs with the live contract, including the normalized hardware-ID `target_drones` response behavior and the legacy-but-ignored ack fields
- added focused router-level coverage in `tests/test_gcs_command_routes.py` and extended the HTTP regression suite with malformed-JSON and unmatched-target cases
- revalidated the extracted-router surface locally with a focused command batch, locally with the full extracted-router backend batch, and on Hetzner with the same backend batch plus the dashboard production build

After this checkpoint, `gcs-server/app_fastapi.py` no longer contains any business `@app.*` route handlers. The GCS-side route extraction boundary is now complete. The clean next boundary is Phase 4 canonical `/api/v1/...` migration across the extracted GCS domains, while the drone-side monolith extraction remains a separate later Phase 3 track.

### Phase 4

- migrate commands, configuration, origin, swarm, git, and show-management domains to canonical v1 routes
- keep legacy compatibility adapters during rollout

Phase 4 first checkpoint on 2026-04-03:

- introduced canonical v1 aliases for the extracted Commands domain:
  - `POST /api/v1/commands`
  - `GET /api/v1/commands/{command_id}`
  - `GET /api/v1/commands/recent`
  - `GET /api/v1/commands/active`
  - `GET /api/v1/commands/statistics`
  - `POST /api/v1/commands/{command_id}/cancel`
  - `POST /api/v1/command-reports/execution-start`
  - `POST /api/v1/command-reports/execution-result`
- deliberately kept `GET /api/v1/commands/recent` as the canonical list surface for this slice instead of overloading `GET /api/v1/commands`, because the current route-key service layer and request-log classification are path-oriented; this preserves one stable semantic path per frontend service key while still giving command submission the cleaner `POST /api/v1/commands` resource entry point
- migrated the shared frontend GCS service layer onto the canonical v1 command submit/status/recent/active paths, so current operator UI flows stop reinforcing the legacy command URLs
- extended route-inventory and alias guardrails to cover the canonical v1 command surface and updated request-log classification so v1 command polling/callback traffic stays operationally quiet at `DEBUG`
- refreshed the public GCS API doc to present the canonical command routes first while keeping the legacy compatibility paths explicit during rollout
- revalidated this slice locally with focused backend/logging tests and on Hetzner with the same backend batch plus the frontend service Jest slice and production build

After this checkpoint, the next clean Phase 4 boundary is the configuration family: fleet config first, then swarm config/assignment, then origin. That ordering keeps the migration on already-extracted routers with centralized frontend consumers before touching the riskier origin/runtime surfaces, and it sets up cleaner identity semantics (`hw_id` vs `pos_id`) for later MCP-facing configuration tooling.

Phase 4 second checkpoint on 2026-04-03:

- introduced canonical v1 aliases for the fleet configuration surface:
  - `GET /api/v1/config/fleet`
  - `PUT /api/v1/config/fleet`
  - `POST /api/v1/config/fleet/validation`
  - `GET /api/v1/config/fleet/trajectory-start-positions`
  - `GET /api/v1/config/fleet/trajectory-start-positions/{pos_id}`
- migrated the shared frontend GCS service layer onto those canonical fleet-config routes, including `PUT` for config saves and the path-parameter form for per-slot trajectory-start lookups
- deliberately cleaned the canonical per-position trajectory-start payload to `x` / `y` so it matches the fleet trajectory-position collection and stops mixing `x/y` with `north/east` for the same config-derived concept; the legacy query-string route stays intact with its older field names during rollout
- extended route-inventory and alias coverage to the canonical fleet-config surface and added focused router coverage for the canonical path-form trajectory-start route
- revalidated this slice locally with focused configuration/backend/inventory tests and on Hetzner with the same backend batch plus the shared frontend GCS service Jest slice and production build

After this checkpoint, the next clean Phase 4 boundary is swarm configuration and assignment canonicalization, followed by origin once the config-family semantics are stable.

Phase 4 third checkpoint on 2026-04-03:

- introduced canonical v1 routes for the swarm configuration surface:
  - `GET /api/v1/config/swarm`
  - `PUT /api/v1/config/swarm`
  - `PATCH /api/v1/config/swarm/assignments/{hw_id}`
- deliberately made the canonical swarm-config `GET` route return the typed persisted resource shape `{version, assignments}` instead of repeating the older raw-list legacy payload; the legacy `/get-swarm-data` compatibility route stays in place during rollout
- migrated the shared frontend GCS service layer onto the canonical swarm-config resource, including `PUT` saves and centralized list-vs-envelope unwrapping for `Overview`, `Mission Config`, and `Swarm Design`
- migrated active non-frontend callers touched in this boundary onto the canonical swarm-config routes as well, including Smart Swarm runtime refresh/failover reporting, swarm analysis fallback, and the reusable validation scripts
- deliberately chose `PATCH /api/v1/config/swarm/assignments/{hw_id}` instead of a leader-only route name, because the live contract updates the full saved assignment surface (`follow`, offsets, and frame) rather than only the upstream leader reference
- extended route-inventory, router, HTTP, and tooling regression coverage to the canonical swarm-config surface and revalidated the slice locally plus on Hetzner with the focused backend batch, shared frontend GCS service Jest slice, and production build

After this checkpoint, the next clean Phase 4 boundary is origin canonicalization, followed by the remaining git/show-management cleanup and later legacy-route removal once all active callers have been migrated.

Phase 4 fourth checkpoint on 2026-04-03:

- introduced canonical v1 routes for the Origin surface:
  - `GET /api/v1/origin`
  - `PUT /api/v1/origin`
  - `GET /api/v1/origin/bootstrap`
  - `GET /api/v1/navigation/global-origin`
  - `GET /api/v1/origin/elevation`
  - `GET /api/v1/origin/deviations`
  - `POST /api/v1/origin/compute`
  - `GET /api/v1/origin/launch-positions`
- migrated the shared frontend GCS service layer and the active Drone Show runtime/validation callers touched in this slice onto the canonical origin paths, so current operator tooling no longer reinforces the legacy origin URLs
- deliberately made the manual-origin write contract truthful instead of brittle: `PUT /api/v1/origin` now accepts omitted altitude and defaults it to `0.0` MSL, matching the dashboard workflow and keeping the canonical persistence path resilient for future MCP/automation callers
- added a distinct canonical bootstrap resource at `GET /api/v1/origin/bootstrap` instead of implicitly pointing bootstrap consumers at the generic origin-read path, so the origin surface now names that runtime-specific read intent explicitly while the legacy `/get-origin-for-drone` compatibility route remains available
- extended route-inventory, HTTP, router, dashboard-service, and Drone Show validation coverage to the canonical origin surface and revalidated the slice locally plus on Hetzner with the focused backend batch, shared frontend GCS service Jest slice, and production build

After this checkpoint, the next clean Phase 4 boundary is the remaining git/show-management canonicalization, followed by deliberate legacy-route retirement once active callers, docs, and SITL validation all move onto the canonical surface.

Phase 4 fifth checkpoint on 2026-04-03:

- introduced canonical v1 routes for the Git surface:
  - `GET /api/v1/git/status`
  - `POST /api/v1/git/sync-operations`
- migrated the shared frontend GCS service layer and the remaining active hardcoded git-status dashboard caller onto the canonical git routes, leaving one current git contract path for UI polling and sync operations
- deliberately chose `sync-operations` instead of the earlier provisional `sync-jobs` wording, because the live route performs dispatch plus convergence verification synchronously and does not expose a durable background-job resource
- extended route-inventory, HTTP, router, dashboard-service, and request-log classification coverage to the canonical git surface, and kept the deprecated one-off GCS/drone git endpoints explicitly outside the canonical path
- revalidated this slice locally and on Hetzner with the focused backend batch, the shared frontend GCS service Jest slice, and the production dashboard build

After this checkpoint, the next clean Phase 4 boundary is show-management canonicalization. That keeps the remaining compatibility cleanup scoped to one domain before we start deliberate legacy-route retirement.

Phase 4 sixth checkpoint on 2026-04-03:

- introduced canonical v1 routes for the Show Management surface:
  - `POST /api/v1/shows/skybrush/import`
  - `GET /api/v1/shows/skybrush`
  - `GET /api/v1/shows/skybrush/archives/raw`
  - `GET /api/v1/shows/skybrush/archives/processed`
  - `GET /api/v1/shows/skybrush/metrics`
  - `GET /api/v1/shows/skybrush/safety-report`
  - `GET /api/v1/shows/skybrush/validation`
  - `POST /api/v1/shows/skybrush/deployments`
  - `GET /api/v1/shows/skybrush/plots`
  - `GET /api/v1/shows/skybrush/plots/{filename}`
  - `GET /api/v1/shows/custom`
  - `POST /api/v1/shows/custom/import`
  - `GET /api/v1/shows/custom/preview`
- deliberately split the canonical show-management surface by workflow instead of leaving SkyBrush ZIP processing and shared-CSV custom replay behind one vague generic route family; standard imported shows now live under `/api/v1/shows/skybrush/*`, while the specialist shared-CSV path lives under `/api/v1/shows/custom/*`
- deliberately modeled canonical validation as `GET /api/v1/shows/skybrush/validation`, because the live route returns a read-only validation snapshot for the current processed show package even though the legacy compatibility route remains `POST /validate-trajectory`
- migrated the shared frontend GCS service layer onto the canonical show-management routes for imports, metadata reads, plot discovery, archive downloads, and custom preview assets, leaving one current caller path for the active Drone Show dashboard surfaces
- extended route-inventory, HTTP, router, and dashboard-service coverage to the canonical show-management surface and revalidated the slice locally plus on Hetzner with focused backend tests, the shared frontend GCS service Jest slice, and the production build

After this checkpoint, the next clean Phase 4 boundary is deliberate compatibility-route retirement planning for the GCS surface, followed by broader SITL regression coverage on the canonical routes and the later drone-side extraction track.

Phase 4 seventh checkpoint on 2026-04-03:

- introduced `src/gcs_api_routes.py` as a shared canonical route constant module for drone-side runtime and validation tooling consumers
- migrated the remaining real internal callers that still hit legacy GCS compatibility paths onto canonical routes instead of leaving them behind as hidden migration debt:
  - drone execution callbacks now use `POST /api/v1/command-reports/execution-start` and `POST /api/v1/command-reports/execution-result`
  - the direct superseded-pending-command fallback path in `src/drone_api_server.py` now also uses the canonical execution-result route
  - drone bootstrap-origin fetches now use `GET /api/v1/origin/bootstrap`
  - `tools/validate_drone_show_runtime.py` now uses the canonical SkyBrush/custom show routes
  - `tools/test_import_show.html` now posts to the canonical SkyBrush import route
- added focused drone-side regression coverage for the canonical superseded-command callback path and canonical bootstrap-origin fetch, and revalidated the slice locally plus on Hetzner with the shared drone-side `test_drone_setup.py` + `test_drone_api_http.py` batch

After this checkpoint, the next clean Phase 4 boundary is explicit classification of the still-mounted GCS compatibility routes into retire-now, keep-temporarily, or canonicalize-next buckets. The highest-value remaining public legacy cluster is the GCS management/static surface plus a few dead frontend compatibility helpers, not the drone runtime/tooling callers.

Phase 4 eighth checkpoint on 2026-04-03:

- introduced canonical v1 routes for the remaining public management/static GCS surface:
  - `GET /api/v1/system/gcs-config`
  - `PUT /api/v1/system/gcs-config`
  - `GET /api/v1/fleet/network-details`
  - `GET /api/v1/swarm-trajectories/plots/{filename}`
- deliberately modeled GCS runtime settings as a system resource instead of preserving the older action-style naming, so the canonical write path is `PUT /api/v1/system/gcs-config` while the legacy `POST /save-gcs-config` alias remains mounted during rollout
- deliberately split detailed fleet network metadata from the higher-level reachability summary: the detailed heartbeat-derived per-drone metadata now has its own canonical path at `GET /api/v1/fleet/network-details`, distinct from `GET /api/v1/fleet/network-status`
- moved Swarm Trajectory-generated plot assets out of the generic `/static/*` namespace and under `/api/v1/swarm-trajectories/plots/{filename}` so resource ownership is explicit for future auth/MCP policy layers
- migrated the shared frontend GCS service layer onto the canonical management/static routes and removed dead frontend git compatibility helpers instead of carrying them forward as misleading pseudo-compatibility
- extended route-inventory, HTTP, router, and shared dashboard GCS service coverage to the canonical management/static surface and revalidated the slice locally plus on Hetzner with focused backend tests, the shared frontend GCS service Jest slice, and the production build

After this checkpoint, the next clean Phase 4 boundary is no longer new alias creation. It is the deliberate public compatibility-retirement pass: classify remaining legacy routes into remove-now, keep-temporarily, or defer-with-reason buckets, then retire the ones that no longer serve live callers, docs, or SITL workflows.

Phase 4 ninth checkpoint on 2026-04-03:

- retired the deprecated one-off git detail routes:
  - removed `GET /get-gcs-git-status`
  - removed `GET /get-drone-git-status/{drone_id}`
- deliberately treated those endpoints as true retirement candidates instead of “deprecated forever” placeholders because the unified canonical `GET /api/v1/git/status` surface already carries both the aggregated drone status data and the embedded `gcs_status` snapshot
- updated route-inventory, HTTP, and router coverage to assert that those retired endpoints are gone instead of merely marked deprecated
- updated the public GCS/git documentation so current operator and integrator guidance no longer advertises the retired one-off endpoints

After this checkpoint, the remaining compatibility-retirement work is the still-mounted business alias families that have not yet been explicitly removed. Those need domain-by-domain decisions with caller, SITL, and documentation checks before retirement.

Phase 4 tenth checkpoint on 2026-04-03:

- retired the public management/static legacy routes:
  - removed `GET /get-gcs-config`
  - removed `POST /save-gcs-config`
  - removed `GET /get-network-info`
  - removed `GET /static/plots/{filename}`
- deliberately treated that cluster as a safe retirement target because there were no remaining live dashboard, runtime-tooling, or validation-script callers; only compatibility mounts, route-resolver leftovers, and docs/tests remained
- kept the canonical management/static surface:
  - `GET /api/v1/system/gcs-config`
  - `PUT /api/v1/system/gcs-config`
  - `GET /api/v1/fleet/network-details`
  - `GET /api/v1/swarm-trajectories/plots/{filename}`
- updated the shared frontend route resolver to stop recognizing the retired management/static legacy paths, preventing removed backend routes from lingering as frontend pseudo-compatibility

After this checkpoint, the remaining compatibility-retirement work is centered on the larger business alias families: configuration/swarm, origin, show-management, command control, and the versionless Swarm Trajectory surface.

Phase 4 eleventh checkpoint on 2026-04-03:

- retired the GCS configuration/swarm legacy routes:
  - removed `GET /get-config-data`
  - removed `POST /save-config-data`
  - removed `POST /validate-config`
  - removed `GET /get-drone-positions`
  - removed `GET /get-trajectory-first-row`
  - removed `GET /get-swarm-data`
  - removed `POST /save-swarm-data`
  - removed `POST /request-new-leader`
- deliberately treated that family as a safe retirement target because there were no remaining live dashboard, runtime-tooling, or validation-script callers; only compatibility mounts, route-resolver leftovers, request-log noise classification, and docs/tests still referenced the old surface
- kept the canonical configuration/swarm surface:
  - `GET /api/v1/config/fleet`
  - `PUT /api/v1/config/fleet`
  - `POST /api/v1/config/fleet/validation`
  - `GET /api/v1/config/fleet/trajectory-start-positions`
  - `GET /api/v1/config/fleet/trajectory-start-positions/{pos_id}`
  - `GET /api/v1/config/swarm`
  - `PUT /api/v1/config/swarm`
  - `PATCH /api/v1/config/swarm/assignments/{hw_id}`
- updated the shared frontend route resolver, request-log classification, and active operator/developer docs so the retired config/swarm aliases no longer linger as pseudo-compatibility

After this checkpoint, the remaining compatibility-retirement work is centered on the still-mounted origin, show-management, command-control, and versionless Swarm Trajectory legacy families.

Phase 4 twelfth checkpoint on 2026-04-03:

- retired the GCS show-management legacy routes:
  - removed `POST /import-show`
  - removed `GET /download-raw-show`
  - removed `GET /download-processed-show`
  - removed `GET /get-show-info`
  - removed `GET /get-custom-show-info`
  - removed `POST /import-custom-show`
  - removed `GET /get-comprehensive-metrics`
  - removed `GET /get-safety-report`
  - removed `POST /validate-trajectory`
  - removed `POST /deploy-show`
  - removed `GET /get-show-plots`
  - removed `GET /get-show-plots/{filename}`
  - removed `GET /get-custom-show-image`
- deliberately treated that family as a safe retirement target because there were no remaining live dashboard, runtime-tooling, or import-helper callers on the old show URLs; only backend compatibility decorators, route-resolver leftovers, and active docs/tests still referenced them
- kept the canonical show-management surface:
  - `POST /api/v1/shows/skybrush/import`
  - `GET /api/v1/shows/skybrush`
  - `GET /api/v1/shows/skybrush/archives/raw`
  - `GET /api/v1/shows/skybrush/archives/processed`
  - `GET /api/v1/shows/skybrush/metrics`
  - `GET /api/v1/shows/skybrush/safety-report`
  - `GET /api/v1/shows/skybrush/validation`
  - `POST /api/v1/shows/skybrush/deployments`
  - `GET /api/v1/shows/skybrush/plots`
  - `GET /api/v1/shows/skybrush/plots/{filename}`
  - `GET /api/v1/shows/custom`
  - `POST /api/v1/shows/custom/import`
  - `GET /api/v1/shows/custom/preview`
- updated the shared frontend route resolver, public show/operator docs, and schema docstrings so the retired show aliases no longer linger as pseudo-compatibility

After this checkpoint, the remaining compatibility-retirement work is centered on the still-mounted origin, command-control, and versionless Swarm Trajectory legacy families.

Phase 4 thirteenth checkpoint on 2026-04-03:

- retired the GCS command-control legacy routes:
  - removed `POST /submit_command`
  - removed `GET /command/{command_id}`
  - removed `GET /commands/recent`
  - removed `GET /commands/active`
  - removed `GET /commands/statistics`
  - removed `POST /command/{command_id}/cancel`
  - removed `POST /command/execution-start`
  - removed `POST /command/execution-result`
- deliberately treated that family as a safe retirement target only after confirming there were no remaining live dashboard, runtime-tooling, or SITL-helper callers on the old command URLs; the remaining references were compatibility decorators, request-log allowances, route-resolver aliases, and docs/tests
- kept the canonical command-control surface:
  - `POST /api/v1/commands`
  - `GET /api/v1/commands/{command_id}`
  - `GET /api/v1/commands/recent`
  - `GET /api/v1/commands/active`
  - `GET /api/v1/commands/statistics`
  - `POST /api/v1/commands/{command_id}/cancel`
  - `POST /api/v1/command-reports/execution-start`
  - `POST /api/v1/command-reports/execution-result`
- updated the shared frontend route resolver, request-log classification, operator/developer docs, and route-inventory guardrails so the retired command aliases no longer linger as pseudo-compatibility

After this checkpoint, the remaining compatibility-retirement work is centered on the still-mounted origin and versionless Swarm Trajectory legacy families.

### Phase 5

- define canonical event-stream contracts for telemetry, command state, git sync, and logs
- align them with future MCP exposure

### Phase 6

- remove the remaining deferred or high-risk legacy routes only after frontend, runtime callers, SITL tools, docs, and tests are fully migrated and validated

Frontend dead code does not need to survive until phase 6. If a consumer is unrouted, unreferenced, and superseded by a validated live workflow, it should be removed during migration rather than kept as misleading pseudo-compatibility.

## Phase 1 Canonical Routes

The first alias slice introduces these canonical entry points:

### GCS

- `GET /api/v1/system/health`
- `GET /api/v1/fleet/telemetry`
- `POST /api/v1/fleet/heartbeats`
- `GET /api/v1/fleet/heartbeats`
- `GET /api/v1/fleet/network-status`

### Drone

- `GET /api/v1/system/health`
- `GET /api/v1/drone/state`
- `POST /api/v1/drone/commands`
- `GET /api/v1/preflight/armability`
- `GET /api/v1/navigation/home`
- `GET /api/v1/navigation/global-origin`
- `GET /api/v1/network/status`
- `GET /api/v1/swarm/config`
- `GET /api/v1/telemetry/local-position`

These routes do not remove legacy endpoints. They create a canonical migration target and an initial contract for tests, docs, and future MCP tooling.

## Non-Goals for Phase 1

Phase 1 does not yet:

- rename or remove legacy routes
- centralize all frontend callers
- normalize every response envelope
- replace WebSocket/SSE strategy
- rework show-management, git-sync, or origin workflows fully

Those are later slices after the first canonical surface is in place and verified.
