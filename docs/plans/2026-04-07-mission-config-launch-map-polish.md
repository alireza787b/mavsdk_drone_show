# 2026-04-07 Mission Config Launch Map Polish

## Scope

- Make the Mission Config launch map read more like an operator map by default.
- Tighten the initial launch-layout fit/zoom behavior so small fleets fill the view more naturally.
- Keep map markers readable across zoom levels instead of freezing one icon size/style.
- Make the Origin status affordance consistently reviewable, even when the origin is already healthy.

## What Changed

- `DronePositionMap` now defaults to `googleSatellite` instead of the previous Esri satellite layer.
- The launch-map viewport fit now uses a tighter pad for small fleets and a slightly closer single-drone default zoom, so the launch layout fills the visible area more effectively.
- Expected-slot markers and live overlay styling now adapt to zoom level:
  - marker size
  - label font size
  - border weight
  - live-point radius
  - deviation-line weight
- Expected-slot markers now use their live status color in the marker border, making the map more legible at a glance while preserving the live overlay and path color.
- The Mission Config Origin status chip stays clickable in all states, not only warning states, so operators can re-open the origin review workflow even when the origin is already `Ready`.

## Validation

### Hetzner frontend

- `CI=true npm test -- --runInBand --watch=false DronePositionMap.test.js MissionLayout.test.js MissionConfig.test.js`
- Result: `3` suites passed, `6` tests passed

- `npm run build`
- Result: `Compiled successfully`

## Notes

- This slice intentionally keeps the shared Leaflet map wrapper intact and improves the Mission Config launch-map behavior inside the page-specific layer instead of forking another map implementation.
- The build remains large overall, but this slice did not introduce new warnings or build failures.
