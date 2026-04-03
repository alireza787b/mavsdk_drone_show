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
- unprefixed operational routes like `/health`, `/submit_command`, `/git-status`
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

After this checkpoint, the only substantive business-route domain still inline in `gcs-server/app_fastapi.py` is the Commands surface. That is now the clean next extraction boundary before Phase 4 canonical route migration.

### Phase 4

- migrate configuration, origin, swarm, git, and show-management domains to canonical v1 routes
- keep legacy compatibility adapters during rollout

### Phase 5

- define canonical event-stream contracts for telemetry, command state, git sync, and logs
- align them with future MCP exposure

### Phase 6

- remove deprecated legacy routes only after frontend, runtime callers, SITL tools, docs, and tests are fully migrated and validated

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
