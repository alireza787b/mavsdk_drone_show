# 2026-04-03 SAR Router Normalization

## Goal

Normalize the QuickScout SAR backend onto the same dependency-injected router-factory standard as the rest of the cleaned GCS API without changing the live `/api/sar/*` contract.

## Scope Closed

- replaced the old module-global SAR router with `create_sar_router(deps)`
- removed the ad hoc `sys.path` mutation from `gcs-server/sar/routes.py`
- switched SAR-internal imports to package-relative imports
- changed the SAR route layer to read shared runtime dependencies from the live `app_fastapi` module object at request time:
  - `load_config`
  - `telemetry_data_all_drones`
  - `telemetry_lock`
  - `send_commands_to_selected`
- kept the public QuickScout HTTP contract stable:
  - `POST /api/sar/mission/plan`
  - `POST /api/sar/mission/launch`
  - `GET /api/sar/mission/{mission_id}/status`
  - `POST /api/sar/mission/{mission_id}/pause`
  - `POST /api/sar/mission/{mission_id}/resume`
  - `POST /api/sar/mission/{mission_id}/abort`
  - `POST /api/sar/mission/{mission_id}/progress`
  - `POST /api/sar/poi`
  - `GET /api/sar/poi`
  - `PATCH /api/sar/poi/{poi_id}`
  - `DELETE /api/sar/poi/{poi_id}`
  - `POST /api/sar/elevation/batch`
- added focused router-level coverage in `tests/test_gcs_sar_routes.py`

## Validation

- local focused backend batch: `21 passed`
- Hetzner focused backend batch: `21 passed`

## Remaining API Debt

- GCS WebSocket stream canonicalization decision:
  - `/ws/telemetry`
  - `/ws/heartbeats`
  - `/ws/git-status`
- explicit stable-root versus `/api/v1/...` decision for:
  - `/api/logs/*`
  - `/api/sar/*`
