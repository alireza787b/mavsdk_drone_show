# 2026-04-04 Drone V1 Canonicalization

## Objective

Finish the remaining public drone-route cleanup that the API merge-readiness review left open, so the drone side matches the cleaned GCS contract direction instead of keeping a mixed canonical-plus-legacy public surface.

## Scope

- add the missing canonical drone route constants and route handlers
- migrate first-party runtime/tooling callers to the canonical drone contract
- retire the legacy drone business aliases once live callers and docs are moved
- align the HTTP and WebSocket drone-state payloads
- revalidate the slice locally and on Hetzner

## Changes

- Added shared canonical drone route constants in `src/drone_api_routes.py`.
- Canonicalized the internal route helpers in `src/params.py` so first-party callers resolve current drone routes from one source of truth.
- Migrated the remaining first-party callers to canonical drone routes across:
  - GCS telemetry/git polling
  - command/home-position helpers
  - mission runtimes and validators
  - drone runtime local helper calls
- Added the missing canonical drone routes:
  - `GET /api/v1/git/status`
  - `GET /api/v1/navigation/position-deviation`
- Retired the legacy drone business aliases:
  - `GET /get_drone_state`
  - `GET /api/live-armability`
  - `POST /api/send-command`
  - `GET /get-home-pos`
  - `GET /get-gps-global-origin`
  - `GET /get-git-status`
  - `GET /get-position-deviation`
  - `GET /get-network-status`
  - `GET /get-swarm-data`
  - `GET /get-local-position-ned`
- Kept `GET /ping` as the explicit stable operational probe instead of forcing probe clients onto a different contract midstream.
- Added a shared validator-backed state serializer in `src/drone_api_server.py` so:
  - `GET /api/v1/drone/state`
  - `WS /ws/drone-state`
  now emit the same schema.
- Updated active drone/operator docs and route-inventory tests so the canonical drone surface is the taught and asserted contract.

## Validation

- Local focused regression batch:
  - `python3 -m pytest tests/test_drone_api_http.py tests/test_api_route_inventory.py tests/test_drone_api_websocket.py tests/test_command_processing.py tests/test_git_manager.py tests/test_coordinator.py tests/test_swarm_trajectory_mission.py tests/test_gcs_core_routes.py tests/test_gcs_command_routes.py tests/test_gcs_git_routes.py -q`
  - result: `209 passed`
- Hetzner focused regression batch:
  - `/root/mavsdk_drone_show_validation/.venv/bin/python -m pytest tests/test_drone_api_http.py tests/test_api_route_inventory.py tests/test_drone_api_websocket.py tests/test_command_processing.py tests/test_git_manager.py tests/test_coordinator.py tests/test_swarm_trajectory_mission.py tests/test_gcs_core_routes.py tests/test_gcs_command_routes.py tests/test_gcs_git_routes.py -q`
  - result: `209 passed`

## Outcome

After this slice, the public route-shape story is materially coherent across both GCS and drone business HTTP surfaces:

- canonical business HTTP routes live under `/api/v1/...`
- stable subsystem roots remain `/api/logs/*` and `/api/sar/*`
- canonical transport roots remain `/ws/telemetry`, `/ws/heartbeats`, `/ws/git-status`, and `/ws/drone-state`
- `GET /ping` remains the explicit operational probe on the drone side

The next API work is no longer more route retirement. The remaining high-signal debt is typed command/input-contract tightening plus one final merge-readiness review from maintainer/contract/MCP perspectives.
