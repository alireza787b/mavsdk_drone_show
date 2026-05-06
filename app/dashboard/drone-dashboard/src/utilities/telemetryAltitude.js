import { FIELD_NAMES } from '../constants/fieldMappings';

const ZERO_ALTITUDE_EPSILON_M = 0.001;

export function toFiniteTelemetryNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function resolveMslAltitude(drone = {}) {
  const globalAltitude = toFiniteTelemetryNumber(drone?.[FIELD_NAMES.POSITION_ALT] ?? drone?.altitude);
  const globalPositionValid = drone?.[FIELD_NAMES.GLOBAL_POSITION_VALID] !== false;
  if (
    globalAltitude !== null
    && (globalPositionValid || Math.abs(globalAltitude) > ZERO_ALTITUDE_EPSILON_M)
  ) {
    return {
      value: globalAltitude,
      source: 'global_position',
      label: 'MSL',
      trustedForMap: globalPositionValid,
    };
  }

  const rawGpsAltitude = toFiniteTelemetryNumber(drone?.[FIELD_NAMES.GPS_RAW_ALTITUDE_M] ?? drone?.gps_raw_altitude_m);
  if (rawGpsAltitude !== null) {
    return {
      value: rawGpsAltitude,
      source: 'gps_raw',
      label: 'GPS MSL',
      trustedForMap: false,
    };
  }

  return {
    value: null,
    source: 'unavailable',
    label: 'MSL',
    trustedForMap: false,
  };
}

export function formatAltitudeMeters(value, label = 'MSL', fallback = 'Alt n/a') {
  const numeric = toFiniteTelemetryNumber(value);
  if (numeric === null) {
    return fallback;
  }
  const formatted = Math.abs(numeric) >= 10 ? numeric.toFixed(0) : numeric.toFixed(1);
  return `${formatted} m ${label}`.trim();
}
