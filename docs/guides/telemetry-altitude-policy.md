# Telemetry Altitude Policy

MDS treats altitude and map position as related but separate signals.

## Display Order

1. `relative_home`: PX4 home-relative altitude when available.
2. `local_ned`: `-LOCAL_POSITION_NED.z`, used for VIO/non-GPS/local-position modes.
3. `baro`: barometric altitude estimate when local or home-relative altitude is unavailable.
4. `absolute_msl`: valid PX4 global-position altitude above mean sea level.

`relative_home`, `local_ned`, and `baro` are not map coordinates. Do not use
them for map placement, distance-to-home, or terrain clearance unless a valid
global/home/terrain reference is also available.

The telemetry payload carries `altitude_report`, `altitude_display_m`, and
`altitude_source` independently from map readiness. `altitude_report.sources`
contains per-source validity, freshness, and labels for:

- `relative_home`
- `absolute_msl`
- `local_ned`
- `baro`

Short telemetry gaps keep the last-known altitude with a stale indication rather
than replacing a useful local/barometric value with `waiting for map`.

## Operator UX

- Dashboard cards show one compact altitude chip with the source label.
- Tooltips explain the source and whether it is map-trusted.
- Drone detail shows all reported altitude sources with validity and freshness.
- Home distance and map placement show unavailable until a valid global
  coordinate exists.
- A drone can be operational in a local-position/VIO mode while map and home
  distance remain unavailable.
