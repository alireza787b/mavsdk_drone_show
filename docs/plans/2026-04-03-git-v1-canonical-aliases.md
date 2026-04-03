# 2026-04-03 Git V1 Canonical Aliases

## Scope

Phase 4, fifth GCS canonical route slice:

- `GET /api/v1/git/status`
- `POST /api/v1/git/sync-operations`

This slice keeps the legacy compatibility routes live:

- `GET /git-status`
- `POST /sync-repos`
- `GET /get-gcs-git-status` *(deprecated)*
- `GET /get-drone-git-status/{drone_id}` *(deprecated)*

## Contract Decisions

- Canonical fleet git reads use `GET /api/v1/git/status`.
- Canonical git sync uses `POST /api/v1/git/sync-operations`.
- The earlier provisional `sync-jobs` naming was deliberately rejected for the canonical surface because the live route returns a verified result synchronously and does not create or expose a durable background-job resource.
- The one-off GCS/drone git endpoints remain compatibility-only and are not part of the canonical migration target.

## Caller Migration

- Dashboard shared GCS service layer now uses the canonical git routes.
- `CommandPreflightSummary` now uses the shared git route key instead of hardcoding `/git-status`.
- Request-log noise classification now treats `GET /api/v1/git/status` as routine polling traffic.

## Local Validation

- `python3 -m pytest tests/test_gcs_git_routes.py tests/test_gcs_api_http.py::TestGitStatusEndpoints tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_api_route_inventory.py tests/test_request_logging.py -q`
  - result: `26 passed`

## Hetzner Validation

- backend/tooling batch:
  - `26 passed`
- frontend shared GCS service Jest slice:
  - `15 passed`
- production dashboard build:
  - passed

## Notes

- The WebSocket path remains `/ws/git-status` in this phase. Only the HTTP git snapshot/mutation surface is canonicalized here.
- The next clean Phase 4 boundary is show-management canonicalization.
