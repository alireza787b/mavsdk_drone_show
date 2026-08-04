import { FIELD_NAMES } from '../constants/fieldMappings';
import { normalizeComparableId } from './missionIdentityUtils';

const DEFAULT_REFERENCE_MAX_AGE_MS = 15_000;

const finiteNumber = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

export function findOriginReferenceTelemetry(telemetryByHwId, hwId) {
  const requestedId = normalizeComparableId(hwId);
  if (!requestedId || !telemetryByHwId || typeof telemetryByHwId !== 'object') {
    return null;
  }

  return Object.entries(telemetryByHwId).reduce((match, [key, row]) => {
    if (match || !row || typeof row !== 'object') return match;
    const keyId = normalizeComparableId(key);
    const rowId = normalizeComparableId(row[FIELD_NAMES.HW_ID], keyId);
    return keyId === requestedId && rowId === requestedId ? row : null;
  }, null);
}

export function describeOriginReference(telemetryByHwId, hwId) {
  const row = findOriginReferenceTelemetry(telemetryByHwId, hwId);
  if (!row) {
    return { eligible: false, label: 'No telemetry', detail: 'No GCS telemetry row is available.' };
  }
  if (row[FIELD_NAMES.TELEMETRY_AVAILABLE] !== true) {
    return {
      eligible: false,
      label: 'Telemetry unavailable',
      detail: row[FIELD_NAMES.TELEMETRY_ERROR] || 'Live telemetry is unavailable.',
    };
  }
  if (row[FIELD_NAMES.IS_ARMED] !== false) {
    return {
      eligible: false,
      label: row[FIELD_NAMES.IS_ARMED] === true ? 'Drone armed' : 'Arm state unknown',
      detail: 'Use a disarmed drone as the formation-origin reference.',
    };
  }

  const fixType = finiteNumber(row[FIELD_NAMES.GPS_FIX_TYPE]) || 0;
  if (row[FIELD_NAMES.GLOBAL_POSITION_VALID] !== true) {
    return {
      eligible: false,
      label: fixType >= 3 ? '3D fix · map pending' : 'Waiting for 3D fix',
      detail: row[FIELD_NAMES.POSITION_UNAVAILABLE_REASON]
        || (fixType >= 3
          ? 'GPS receiver has a 3D fix, but PX4 has not published a usable global position.'
          : 'A 3D GPS fix and PX4 global position are required.'),
    };
  }

  const lat = finiteNumber(row[FIELD_NAMES.POSITION_LAT]);
  const lon = finiteNumber(row[FIELD_NAMES.POSITION_LONG]);
  const alt = finiteNumber(row[FIELD_NAMES.POSITION_ALT]);
  const ageMs = finiteNumber(row[FIELD_NAMES.GLOBAL_POSITION_AGE_MS]);
  const configuredMaxAgeMs = finiteNumber(row.telemetry_stale_threshold_ms);
  const maxAgeMs = configuredMaxAgeMs && configuredMaxAgeMs > 0
    ? configuredMaxAgeMs
    : DEFAULT_REFERENCE_MAX_AGE_MS;
  const coordinatesValid = lat !== null && lon !== null
    && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
    && (Math.abs(lat) > 0.000001 || Math.abs(lon) > 0.000001);

  if (!coordinatesValid || alt === null) {
    return {
      eligible: false,
      label: 'Global position incomplete',
      detail: 'PX4 global latitude, longitude, and absolute MSL altitude are required.',
    };
  }
  if (ageMs === null || ageMs > maxAgeMs) {
    return {
      eligible: false,
      label: 'Global position stale',
      detail: 'Wait for a fresh PX4 global-position sample, then retry.',
    };
  }

  return {
    eligible: true,
    label: 'Reference ready',
    detail: `Fresh PX4 global position (${(ageMs / 1000).toFixed(1)}s old).`,
  };
}

export function candidateMatchesDrone(candidate, hwId) {
  const candidateId = normalizeComparableId(candidate?.reference?.hw_id);
  const selectedId = normalizeComparableId(hwId);
  return Boolean(candidate?.origin && candidateId && selectedId && candidateId === selectedId);
}
