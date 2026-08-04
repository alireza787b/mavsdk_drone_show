# Formation Origin System

## Purpose

The formation origin is the WGS84 latitude, longitude, and absolute MSL
altitude used to project mission-space North/East offsets into global
coordinates. It is operator-managed GCS state. It is not interchangeable with
PX4 home, PX4 GPS global origin, a raw receiver fix, or a drone's local NED
origin.

This guide is the current origin contract. Coordinate/control-mode details are
in [Control Modes and Coordinate Systems](../control-modes-and-coordinates.md).

## Coordinate contract

Trajectory files use NED axes:

- `x` / `px`: North in meters
- `y` / `py`: East in meters
- `z` / `pz`: Down in meters

The first trajectory row for a show slot is its intended launch offset from the
formation origin. Mission Config obtains these offsets from the trajectory
files; they are not duplicated in `config.json`.

Keep these references distinct:

| Reference | Owner | Meaning |
|---|---|---|
| Formation origin | MDS GCS | Shared mission-space `(0,0,0)` in WGS84 + MSL |
| PX4 home | PX4 | Vehicle return/landing reference |
| PX4 GPS global origin | PX4 estimator | PX4 global/local-frame conversion reference |
| Current global position | PX4 `GLOBAL_POSITION_INT` | Estimator-approved live WGS84 + MSL sample |
| Raw GPS fix | GPS receiver | Receiver quality; not proof that PX4 accepts a global position |
| Local NED | PX4 | Vehicle-local North/East/Down frame |

A raw 3D GPS fix is not sufficient for a drone-referenced formation origin.
MDS requires a fresh, estimator-approved current global position.

## Sources of truth

- `data/origin.json`: local runtime override written by the canonical origin API
- `data/origin.sitl.default.json`: tracked stock-SITL fallback only
- trajectory first rows: intended per-slot North/East launch offsets
- `/api/v1/fleet/telemetry`: live per-hardware position evidence

On a fresh SITL install, the packaged default is used only when no runtime
override exists. Real-hardware deployments must treat origin as reviewed
operator state. Do not commit customer/field origin overrides as code.

## Operator workflows

### Manual origin

Use this when the operator has independently verified WGS84 coordinates and MSL
altitude. Mission Config sends a typed manual request and updates its local state
only after the GCS confirms persistence.

The UI accepts latitude or longitude equal to zero. Latitude must be in
`[-90, 90]`, longitude in `[-180, 180]`, and altitude must be finite.

### Drone reference

Use this to recover the formation origin from one drone standing at its assigned
show-slot offset:

1. Keep the aircraft disarmed.
2. Select the hardware identity in Mission Config.
3. Review its availability label.
4. Compute a preview.
5. Review candidate latitude, longitude, MSL altitude, hardware identity, slot,
   and sample age.
6. Select **Set Origin**.

The browser sends only `hw_id`. The GCS resolves the configured `pos_id`, takes a
locked telemetry snapshot, validates it, reads the assigned trajectory start,
and computes the candidate. The final write repeats that process atomically
against a fresh snapshot; it does not trust or persist browser-supplied position
data.

The reference is rejected when any of these are true:

- hardware is unknown, duplicated, or has no valid assigned slot
- telemetry is missing or unavailable
- aircraft is armed
- raw GPS is below 3D fix
- PX4 global position is not valid
- position source is not `global_position_int`
- latitude/longitude or absolute MSL altitude is invalid
- the global-position timestamp is missing or older than the canonical local
  telemetry staleness threshold
- the assigned trajectory start is missing

MDS does not silently substitute raw-GPS coordinates, PX4 home, local NED,
relative altitude, or barometric display altitude. If current global position is
unavailable, either wait for PX4 to publish it or use an independently verified
manual origin.

## Canonical APIs

### Read current origin

```http
GET /api/v1/origin
```

```json
{
  "lat": 35.7244357,
  "lon": 51.2755813,
  "alt": 1278.0,
  "timestamp": 1785859200000,
  "source": "manual"
}
```

`GET /api/v1/origin/bootstrap` returns the same canonical data for runtime
consumers. `GET /api/v1/navigation/global-origin` is the typed navigation view.

### Persist a manual origin

```http
PUT /api/v1/origin
Content-Type: application/json
```

```json
{
  "method": "manual",
  "lat": 35.7244357,
  "lon": 51.2755813,
  "alt": 1278.0
}
```

The server owns the persisted source label; clients do not submit `alt_source`.

### Preview a drone-referenced origin

```http
POST /api/v1/origin/compute
Content-Type: application/json
```

```json
{
  "hw_id": "2"
}
```

Example response:

```json
{
  "status": "success",
  "origin": {
    "lat": 48.8566,
    "lon": 2.3522,
    "alt": 50.7,
    "source": "drone_global_position_msl"
  },
  "reference": {
    "hw_id": "2",
    "pos_id": 2,
    "latitude": 48.85664,
    "longitude": 2.35928,
    "altitude_msl": 50.7,
    "position_source": "global_position_int",
    "position_timestamp_ms": 1785859200000,
    "position_age_ms": 800,
    "gps_fix_type": 3
  },
  "intended_offset": {
    "north_m": -5.0,
    "east_m": -2.5
  }
}
```

This route is read-only. Obsolete client-supplied coordinate/slot fields are
forbidden.

### Atomically persist a drone-referenced origin

```http
PUT /api/v1/origin
Content-Type: application/json
```

```json
{
  "method": "drone_reference",
  "hw_id": "2"
}
```

The GCS revalidates current telemetry and recomputes before saving. A failed
validation does not modify `data/origin.json`.

### Launch positions and deviations

- `GET /api/v1/origin/launch-positions?heading=0&format=json|csv|kml`
  projects configured slot offsets from the saved origin.
- `GET /api/v1/origin/deviations` compares expected slot positions with fresh,
  valid PX4 global positions. Missing, invalid, or stale positions are reported
  as unavailable and are never treated as zero coordinates.

The heading option belongs to launch-position export. It is not implicitly
mixed into origin recovery; any future heading-aware origin workflow must update
computation, deviation review, persistence, and execution together.

## Runtime behavior

When `auto_global_origin` is selected for a compatible mission, the GCS attaches
the saved origin to the typed command payload. Drone runtime consumers can also
read `/api/v1/origin/bootstrap`. Local/non-shared-origin control modes retain
their documented behavior; setting a formation origin does not silently change
the selected control mode.

## Validation checklist

Before a real mission that uses shared origin:

1. Confirm the intended mission package and trajectory-slot assignments.
2. Confirm the origin source and MSL altitude.
3. Confirm every relevant current-position sample is fresh and globally valid.
4. Review launch-position projection and deviation results.
5. Confirm the mission's local/global and auto-origin mode explicitly.
6. Keep origin changes out of active flight operations.

Automated coverage lives in:

- `tests/test_origin_reference.py`
- `tests/test_gcs_origin_routes.py`
- origin/deviation tests under `tests/`
- `app/dashboard/drone-dashboard/src/utilities/originReference.test.js`
- `app/dashboard/drone-dashboard/src/hooks/useComputeOrigin.test.js`
- `app/dashboard/drone-dashboard/src/components/OriginModal.test.js`

## Related documentation

- [Drone Show](drone-show.md)
- [Control Modes and Coordinate Systems](../control-modes-and-coordinates.md)
- [GCS API Server](../apis/gcs-api-server.md)
- [Mission configuration](../guides/config-json-format.md)
