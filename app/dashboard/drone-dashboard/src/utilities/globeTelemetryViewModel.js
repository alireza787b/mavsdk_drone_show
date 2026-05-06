import { FIELD_NAMES, normalizeDroneData } from '../constants/fieldMappings';
import { getDroneShowStateName } from '../constants/droneStates';
import { getPromotedMissionConfigField } from './missionConfigFields';
import { normalizeDroneConfigData } from './missionIdentityUtils';
import { getDroneRuntimeStatus } from './droneRuntimeStatus';
import { resolveMslAltitude } from './telemetryAltitude';

const LOW_LATENCY_INTERVAL_MS = 1000;
const MEDIUM_FLEET_INTERVAL_MS = 1500;
const LARGE_FLEET_INTERVAL_MS = 2500;
const BACKGROUND_INTERVAL_MS = 6000;
const CONSTRAINED_NETWORK_INTERVAL_MS = 3000;

function toFiniteNumber(value, fallback = null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function hasNonZeroCoordinate(lat, lon) {
  return Number.isFinite(lat)
    && Number.isFinite(lon)
    && (Math.abs(lat) > 0.000001 || Math.abs(lon) > 0.000001);
}

function getConnectionProfile() {
  if (typeof navigator === 'undefined') {
    return {};
  }

  return navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
}

export function calculateGlobeTelemetryIntervalMs(droneCount = 0, options = {}) {
  const hidden = options.hidden ?? (typeof document !== 'undefined' ? document.hidden : false);
  if (hidden) {
    return BACKGROUND_INTERVAL_MS;
  }

  const connection = options.connection || getConnectionProfile();
  const effectiveType = String(connection.effectiveType || '').toLowerCase();
  if (connection.saveData || effectiveType.includes('2g')) {
    return CONSTRAINED_NETWORK_INTERVAL_MS;
  }

  if (effectiveType.includes('3g')) {
    return Math.max(MEDIUM_FLEET_INTERVAL_MS, CONSTRAINED_NETWORK_INTERVAL_MS - 1000);
  }

  if (droneCount > 80) {
    return LARGE_FLEET_INTERVAL_MS;
  }

  if (droneCount > 30) {
    return MEDIUM_FLEET_INTERVAL_MS;
  }

  return LOW_LATENCY_INTERVAL_MS;
}

export function buildGlobeDroneViewModels(telemetryPayload = {}, configPayload = [], nowMs = Date.now()) {
  const configRows = normalizeDroneConfigData(configPayload);
  const configMap = new Map(configRows.map((row) => [String(row.hw_id), row]));

  return Object.entries(telemetryPayload || {})
    .filter(([, drone]) => drone && typeof drone === 'object' && Object.keys(drone).length > 0)
    .map(([id, rawDrone]) => {
      const drone = normalizeDroneData(rawDrone) || {};
      const config = configMap.get(String(id)) || {};
      const stateValue = drone[FIELD_NAMES.STATE] ?? null;
      const velocityNorth = toFiniteNumber(drone[FIELD_NAMES.VELOCITY_NORTH]);
      const velocityEast = toFiniteNumber(drone[FIELD_NAMES.VELOCITY_EAST]);
      const velocityDown = toFiniteNumber(drone[FIELD_NAMES.VELOCITY_DOWN]);
      const hasVelocity = [velocityNorth, velocityEast, velocityDown].every(Number.isFinite);
      const speed = hasVelocity
        ? Math.sqrt((velocityNorth ** 2) + (velocityEast ** 2) + (velocityDown ** 2))
        : null;
      const runtimeStatus = getDroneRuntimeStatus(drone, nowMs);
      const promotedField = getPromotedMissionConfigField(config);
      const operatorAlias = promotedField?.displayValue && promotedField.displayValue !== 'Not set'
        ? promotedField.displayValue
        : '';
      const latitude = toFiniteNumber(drone[FIELD_NAMES.POSITION_LAT], 0);
      const longitude = toFiniteNumber(drone[FIELD_NAMES.POSITION_LONG], 0);
      const altitudeReading = resolveMslAltitude(drone);
      const altitude = altitudeReading.value ?? 0;
      const globalPositionValid = drone[FIELD_NAMES.GLOBAL_POSITION_VALID] === undefined
        ? hasNonZeroCoordinate(latitude, longitude)
        : Boolean(drone[FIELD_NAMES.GLOBAL_POSITION_VALID]) && hasNonZeroCoordinate(latitude, longitude);

      return {
        ...drone,
        hw_id: String(drone[FIELD_NAMES.HW_ID] ?? id),
        pos_id: config.pos_id ?? drone[FIELD_NAMES.POS_ID] ?? id,
        operator_alias: operatorAlias,
        operator_alias_label: promotedField?.label || null,
        position: [latitude, longitude, altitude],
        noMapFix: !globalPositionValid,
        global_position_valid: globalPositionValid,
        global_position_age_ms: toFiniteNumber(drone[FIELD_NAMES.GLOBAL_POSITION_AGE_MS]),
        position_source: drone[FIELD_NAMES.POSITION_SOURCE] || 'unavailable',
        position_unavailable_reason: drone[FIELD_NAMES.POSITION_UNAVAILABLE_REASON] || null,
        state: stateValue,
        stateLabel: stateValue === null ? 'Unknown' : getDroneShowStateName(stateValue),
        follow_mode: toFiniteNumber(drone[FIELD_NAMES.FOLLOW_MODE], 0),
        altitude,
        altitude_source: altitudeReading.source,
        altitude_label: altitudeReading.label,
        altitude_available: altitudeReading.value !== null,
        marker_color: config.marker_color || config.markerColor || drone.marker_color || '',
        battery_voltage: toFiniteNumber(drone[FIELD_NAMES.BATTERY_VOLTAGE]),
        distance_to_home_m: toFiniteNumber(drone[FIELD_NAMES.DISTANCE_TO_HOME_M]),
        flight_mode: drone[FIELD_NAMES.FLIGHT_MODE] ?? null,
        base_mode: drone[FIELD_NAMES.BASE_MODE] ?? null,
        system_status: drone[FIELD_NAMES.SYSTEM_STATUS] ?? null,
        is_armed: drone[FIELD_NAMES.IS_ARMED] ?? null,
        gps_fix_type: drone[FIELD_NAMES.GPS_FIX_TYPE] ?? null,
        gps_raw_valid: drone[FIELD_NAMES.GPS_RAW_VALID] ?? null,
        gps_raw_age_ms: toFiniteNumber(drone[FIELD_NAMES.GPS_RAW_AGE_MS]),
        gps_raw_altitude_m: toFiniteNumber(drone[FIELD_NAMES.GPS_RAW_ALTITUDE_M]),
        satellites_visible: drone[FIELD_NAMES.SATELLITES_VISIBLE] ?? null,
        mission: drone[FIELD_NAMES.MISSION] ?? null,
        last_mission: drone[FIELD_NAMES.LAST_MISSION] ?? null,
        speed_mps: speed,
        last_update: drone[FIELD_NAMES.UPDATE_TIME] ?? drone[FIELD_NAMES.TIMESTAMP] ?? drone[FIELD_NAMES.HEARTBEAT_LAST_SEEN] ?? null,
        runtimeStatus,
        runtime_level: runtimeStatus.level,
        runtime_indicator_class: runtimeStatus.indicatorClass,
        runtime_label: runtimeStatus.label,
      };
    })
    .sort((left, right) => String(left.pos_id).localeCompare(String(right.pos_id), undefined, { numeric: true }));
}
