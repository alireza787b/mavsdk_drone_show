# Tactical Map And Globe Slice

Date: 2026-04-25

## Scope

This slice upgrades the `Drone Visualization` page from a simple marker view to
a tactical fleet view shared by:

- 3D globe scene
- Mapbox map view
- Leaflet fallback map view

## Decisions

- Keep marker interaction lightweight and operator-focused: click/touch a drone
  marker or drone chip to open one compact tactical card.
- Use the existing fleet config `marker_color` field as the marker/card accent
  source of truth.
- Prefer the canonical `/ws/telemetry` stream for live updates; keep adaptive
  HTTP polling as fallback.
- Bound WebSocket requested cadence on the server so large fleets, background
  tabs, and constrained links can reduce client bandwidth without a new API.
- Do not add heavy map overlays by default. Controls remain minimal: provider,
  layer/fallback controls, fleet fit, fullscreen/navigation where supported.

## Implemented

- Shared `TacticalDroneCard` with altitude, battery, GPS, speed, mode, mission,
  follow target, coordinates, last-seen time, and quick links.
- Drone selection strip with transport/cadence badge and per-drone chips.
- Persistent 3D marker selection with enlarged hit target and selected ring.
- Mapbox marker popover cards, navigation/fullscreen/scale controls, and fleet
  fit action.
- Leaflet marker popup cards and tile-layer control on the tactical map view.
- WebSocket `interval_ms` query support with backend bounding.
- View-model tests for tactical telemetry mapping and adaptive cadence.
- Component tests for tactical card quick links.
- GCS WebSocket contract test for bounded interval query.
- Documentation updates for map behavior and WebSocket stream cadence.

## Validation

- Backend focused test:
  `python3 -m pytest tests/test_gcs_api_websocket.py`
- Hetzner frontend focused tests:
  `CI=true npm test -- --runInBand --watch=false src/utilities/globeTelemetryViewModel.test.js src/components/TacticalDroneCard.test.js src/services/gcsApiService.test.js`
- Hetzner production dashboard build:
  `npm run build`

## Notes

- The page now uses WebSocket when available and shows `WS`; if WebSocket drops,
  it falls back to HTTP and shows `HTTP`.
- SITL and real hardware use the same UI path because the card is fed only by
  canonical fleet telemetry plus fleet config.
