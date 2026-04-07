# 2026-04-07 Mission Config Launch Map And Sync Finalization

## Scope

- Fix the Mission Config `Plot` -> `Map` view so it renders a real operator-useful launch map instead of a blank/black pane.
- Resolve the live Hetzner git-sync warning by getting GCS and active SITL drones onto one clean current commit.
- Reconfirm the operator `Sync` action path with explicit branch/commit reporting.

## What Changed

### Mission Config launch map

- Rebuilt `DronePositionMap` on top of the shared `LeafletMapBase` instead of the older one-off map surface.
- Fixed the zero-origin bug by treating `0` latitude / longitude as valid coordinates instead of falsy values.
- Added launch-map viewport invalidation and auto-fit so toggling from `Plot` to `Map` no longer leaves the Leaflet canvas stale.
- Added expected launch-slot markers, live-position overlays, deviation lines, and origin marker so the map carries the same mission context as the plot view.
- Added click-through parity: tapping an expected marker routes back into the matching Mission Config drone card.
- Replaced the duplicated legacy `DronePositionMap.css` rules with one clean map layout.

### Sync feedback

- `POST /api/v1/git/sync-operations` now returns `target_branch` and `target_commit`.
- The shared dashboard sync hook now includes that target ref in operator feedback, plus failed drone IDs when present.

## Validation

### Local

- `python3 -m pytest tests/test_gcs_git_routes.py tests/test_gcs_api_http.py -q`
- Result: `86 passed`

### Hetzner frontend

- `CI=true npm test -- --runInBand --watch=false src/components/DronePositionMap.test.js src/components/DroneConfigCard.test.js src/components/ControlButtons.test.js`
- Result: `3` suites passed, `5` tests passed

- `npm run build`
- Result: `Compiled successfully`

## Live Hetzner runtime

- GCS backend now reports:
  - branch: `main-candidate`
  - commit: `296151595f4126587e344444540f7d1b71ecfb0d`
  - status: `clean`
- `GET /api/v1/system/health` returns `ok`
- `GET /api/v1/git/status` now shows:
  - drones `1/2/3` synced to `296151595f4126587e344444540f7d1b71ecfb0d`
  - `synced_count=3`
  - `needs_sync_count=0`

### Live sync-operation proof

- `POST /api/v1/git/sync-operations`
- Result:
  - `success=true`
  - `synced_drones=[1,2,3]`
  - `failed_drones=[4,5]`
  - `target_branch=main-candidate`
  - `target_commit=296151595f4126587e344444540f7d1b71ecfb0d`
- Interpretation:
  - the active 3-drone SITL fleet updated and verified cleanly
  - config entries `4` and `5` are not active runtime participants in the current Hetzner SITL stack, so they are correctly reported outside the verified active set

## Notes

- The live frontend process on Hetzner is serving `HTTP 200` on host-local `127.0.0.1:3030`.
- The backend is the authoritative git-status source for operator sync state, and it is now clean/current again.
