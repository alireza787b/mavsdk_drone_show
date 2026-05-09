# Telemetry Altitude Policy

MDS treats altitude and map position as related but separate signals.

## Display Order

1. `MSL`: valid PX4 global position altitude.
2. `GPS MSL`: raw GPS altitude when `GPS_RAW_INT` reports a 3D fix.
3. `Local`: `-LOCAL_POSITION_NED.z`, used for VIO/non-GPS/local-position modes.

`Local` is a local-frame height, not guaranteed AGL. Do not use it for map
placement, distance-to-home, or terrain clearance unless a valid home/terrain
reference is also available.

## Operator UX

- Dashboard cards show one compact altitude chip with the source label.
- Tooltips explain the source and whether it is map-trusted.
- Home distance and map placement show unavailable until a valid global
  coordinate exists.
- A drone can be operational in a local-position/VIO mode while map and home
  distance remain unavailable.
