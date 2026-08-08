# Telemetry Altitude Policy

MDS treats altitude and map position as related but separate signals.

## Display Order

1. `relative_home`: PX4 home-relative altitude only after PX4 has
   authoritatively reported `home_position_set=true`.
2. `local_ned`: `-LOCAL_POSITION_NED.z`, used for VIO/non-GPS/local-position modes.
3. `baro`: barometric altitude estimate when local or home-relative altitude is unavailable.
4. `absolute_msl`: valid PX4 global-position altitude above mean sea level.

`relative_home`, `local_ned`, and `baro` are not map coordinates. Do not use
them for map placement, distance-to-home, or terrain clearance unless a valid
global/home/terrain reference is also available.

`GLOBAL_POSITION_INT.relative_alt` is not sufficient by itself. Before PX4
publishes `HOME_POSITION`, some runtimes can report a value that resembles MSL
altitude rather than height above launch. MDS therefore marks that source
invalid and emits `relative_altitude_m=null` until authoritative home exists.
For example, a vehicle reporting 60 m MSL with home unavailable is shown as
`MSL 60 m` (or a valid local/barometric source), never as `REL 60 m`.

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
- Home distance shows unavailable until both a valid global coordinate and
  authoritative PX4 home exist. Map placement still depends only on a valid
  global coordinate.
- A drone can be operational in a local-position/VIO mode while map and home
  distance remain unavailable.

## Mission Planning

Mission planning must not promote display-only altitude into global mission
truth.

- QuickScout and other PX4 Mission-style planners require valid global
  coordinates when assigning or launching global waypoint missions.
- Swarm Trajectory authoring stores global latitude/longitude and MSL altitude.
  `Target AGL` is converted into stored MSL only after terrain/elevation is
  resolved for that waypoint.
- `relative_home`, `local_ned`, and `baro` can support local operator awareness
  but cannot define map placement, corridor buffers, distance-to-home, or
  terrain clearance by themselves.
- Missing or stale global position must be shown as unavailable. Do not plan
  from `(0, 0)` unless the operator explicitly selected `(0, 0)` as mission
  geometry.
- Last-known position is a source-labeled historical point. It can seed a
  last-known search only when the operator accepts it as search geometry; it is
  not fresh telemetry.
