# 2026-04-03 Git Legacy Route Retirement

## Scope

Phase 4, ninth API-modernization checkpoint:

- remove `GET /get-gcs-git-status`
- remove `GET /get-drone-git-status/{drone_id}`

The canonical git surface remains:

- `GET /api/v1/git/status`
- `GET /git-status`
- `POST /api/v1/git/sync-operations`
- `POST /sync-repos`
- `WS /ws/git-status`

## Retirement Decision

- Both removed routes were already explicitly deprecated.
- Neither route has any remaining live code callers in the dashboard, runtime tooling, or validation scripts.
- The unified canonical git status resource already carries the same operator data:
  - `gcs_status` replaces the old one-off GCS route
  - `git_status[hw_id]` replaces the old one-off per-drone route
- Keeping them mounted would leave misleading permanent compatibility debt with no operational value.

## Local Validation

- `python3 -m pytest tests/test_gcs_git_routes.py tests/test_gcs_api_http.py::TestGitStatusEndpoints tests/test_api_route_inventory.py -q`
  - result: `12 passed`

## Hetzner Validation

- backend/tooling batch:
  - `12 passed`

## Notes

- This is the first actual public route-removal checkpoint in the API modernization stream.
- Remaining retirement work is broader and higher-risk because it touches still-mounted business alias families, not already-deprecated orphan routes.
- Hetzner validation for this slice used a fresh temporary copy of the clean runtime checkout at `8d39c08a` because the older long-lived validation tree had accumulated unrelated drift and stale sync artifacts.
