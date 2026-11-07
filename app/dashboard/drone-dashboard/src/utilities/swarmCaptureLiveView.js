import LatLon from 'geodesy/latlon-nvector-ellipsoidal.js';

// Display confidence only. Capture authority remains with the native two-sample API.
export const CAPTURE_VIEW_MAX_AGE_MS = 5000;
const finite = value => typeof value === 'number' && Number.isFinite(value) ? value : null;

function validGlobalRow(row, id) {
  return row && String(row.hw_id) === id && row.global_position_valid === true
    && row.position_source === 'global_position_int'
    && [row.position_lat, row.position_long, row.position_alt].every(v => finite(v) !== null)
    && Math.abs(row.position_lat) <= 90 && Math.abs(row.position_long) <= 180
    && (row.position_lat !== 0 || row.position_long !== 0);
}

export function captureViewReference(row, id) {
  return validGlobalRow(row, id) ? { latitude: row.position_lat,
    longitude: row.position_long, altitude_msl_m: row.position_alt } : null;
}

/** Project cached PX4 global positions into the frozen capture's common datum.
 * Never feeds a saved assignment, chooses a raw-GPS fallback or subtracts homes.
 */
export function captureLivePositions(rows, hwIds, reference, ages = {}, delayed = false) {
  if (!reference || [reference.latitude, reference.longitude, reference.altitude_msl_m].some(v => finite(v) === null)) return [];
  const origin = new LatLon(reference.latitude, reference.longitude, reference.altitude_msl_m);
  return hwIds.flatMap(id => {
    const row = rows?.[id];
    if (!validGlobalRow(row, id)) return [];
    try {
      const delta = origin.deltaTo(new LatLon(row.position_lat, row.position_long, row.position_alt));
      const sourceAge = finite(row.global_position_age_ms)
        ?? (finite(row.server_time) !== null && finite(row.global_position_timestamp_ms) !== null
          ? row.server_time - row.global_position_timestamp_ms : null);
      const elapsed = ages[id] ?? Infinity;
      return [{ id, north: delta.north, east: delta.east,
        up: row.position_alt - reference.altitude_msl_m,
        stale: delayed || row.telemetry_available !== true || sourceAge === null || sourceAge < 0
          || !(row.global_position_timestamp_ms > 0) || sourceAge + elapsed > CAPTURE_VIEW_MAX_AGE_MS }];
    } catch (_) { return []; }
  });
}
