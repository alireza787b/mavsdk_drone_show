import { FIELD_NAMES } from '../constants/fieldMappings';

const ZERO_ALTITUDE_EPSILON_M = 0.001;

export function toFiniteTelemetryNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function resolveMslAltitude(drone = {}) {
  const report = drone?.altitude_report;
  if (report && typeof report === 'object') {
    const value = toFiniteTelemetryNumber(report.display_m);
    const source = String(report.source || 'unavailable');
    const label = report.label || ({
      relative_home: 'REL',
      absolute_msl: 'MSL',
      local_ned: 'LCL',
      baro: 'BARO',
    }[source] || 'ALT');
    return {
      value,
      source,
      label,
      trustedForMap: source === 'absolute_msl' && drone?.[FIELD_NAMES.GLOBAL_POSITION_VALID] !== false,
      stale: Boolean(report.stale),
      sources: report.sources || {},
      report,
    };
  }

  const globalAltitude = toFiniteTelemetryNumber(drone?.[FIELD_NAMES.POSITION_ALT] ?? drone?.altitude);
  const globalPositionValid = drone?.[FIELD_NAMES.GLOBAL_POSITION_VALID] !== false;
  if (
    globalAltitude !== null
    && (globalPositionValid || Math.abs(globalAltitude) > ZERO_ALTITUDE_EPSILON_M)
  ) {
    return {
      value: globalAltitude,
      source: 'absolute_msl',
      label: 'MSL',
      trustedForMap: globalPositionValid,
    };
  }

  const rawGpsAltitude = toFiniteTelemetryNumber(drone?.[FIELD_NAMES.GPS_RAW_ALTITUDE_M] ?? drone?.gps_raw_altitude_m);
  const gpsRawUsable = drone?.[FIELD_NAMES.GPS_RAW_VALID] === true || Number(drone?.[FIELD_NAMES.GPS_FIX_TYPE]) >= 3;
  if (rawGpsAltitude !== null && gpsRawUsable) {
    return {
      value: rawGpsAltitude,
      source: 'absolute_msl',
      label: 'MSL',
      trustedForMap: false,
    };
  }

  const localDown = toFiniteTelemetryNumber(drone?.[FIELD_NAMES.LOCAL_POSITION_DOWN] ?? drone?.local_position_down);
  const localOk = drone?.[FIELD_NAMES.LOCAL_POSITION_OK] === true
    || Number(drone?.[FIELD_NAMES.LOCAL_POSITION_TIME_BOOT_MS] ?? drone?.local_position_time_boot_ms) > 0;
  if (localDown !== null && localOk) {
    return {
      value: -localDown,
      source: 'local_ned',
      label: 'LCL',
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
