// app/dashboard/drone-dashboard/src/constants/fieldMappings.js
/**
 * Field Name Mappings - Flask to FastAPI Migration
 * ==================================================
 * Single source of truth for telemetry field name conversions.
 *
 * **Backend Standard:** snake_case (FastAPI Pydantic)
 * **Legacy Frontend:** PascalCase (Flask migration artifact)
 *
 * This file ensures consistent field access across all React components
 * after the GCS server migration from Flask → FastAPI.
 *
 * @author MAVSDK Drone Show Team
 * @date 2025-11-24
 */

/**
 * Complete field mapping from legacy PascalCase to FastAPI snake_case
 * Use this for direct field access: drone[FIELD_NAMES.BATTERY_VOLTAGE]
 */
export const FIELD_NAMES = {
  // Identity
  HW_ID: 'hw_id',
  POS_ID: 'pos_id',
  DETECTED_POS_ID: 'detected_pos_id',
  IP: 'ip',

  // Position & Navigation
  POSITION_LAT: 'position_lat',
  POSITION_LONG: 'position_long',
  POSITION_ALT: 'position_alt',
  VELOCITY_NORTH: 'velocity_north',
  VELOCITY_EAST: 'velocity_east',
  VELOCITY_DOWN: 'velocity_down',
  YAW: 'yaw',

  // Flight Status
  FLIGHT_MODE: 'flight_mode',
  BASE_MODE: 'base_mode',
  SYSTEM_STATUS: 'system_status',
  IS_ARMED: 'is_armed',
  IS_READY_TO_ARM: 'is_ready_to_arm',

  // Mission State
  STATE: 'state',
  MISSION: 'mission',
  LAST_MISSION: 'last_mission',
  TRIGGER_TIME: 'trigger_time',
  FOLLOW_MODE: 'follow_mode',

  // Battery & Power
  BATTERY_VOLTAGE: 'battery_voltage',

  // GPS & Positioning Accuracy
  GPS_FIX_TYPE: 'gps_fix_type',
  SATELLITES_VISIBLE: 'satellites_visible',
  HDOP: 'hdop',
  VDOP: 'vdop',

  // Timestamps
  TIMESTAMP: 'timestamp',
  UPDATE_TIME: 'update_time',
  HEARTBEAT_LAST_SEEN: 'heartbeat_last_seen',
};

/**
 * Normalize drone telemetry data from any format to FastAPI snake_case
 *
 * @param {Object} droneData - Raw drone data (may use PascalCase or snake_case)
 * @returns {Object} Normalized drone data with snake_case field names
 *
 * @example
 * const raw = { Position_Lat: 35.72, Battery_Voltage: 16.2 };
 * const normalized = normalizeDroneData(raw);
 * // { position_lat: 35.72, battery_voltage: 16.2 }
 */
export function normalizeDroneData(droneData) {
  if (!droneData || typeof droneData !== 'object') {
    return droneData;
  }

  // Map of legacy PascalCase → snake_case conversions
  const legacyToSnakeCaseMap = {
    // Identity
    hw_ID: 'hw_id',
    Pos_ID: 'pos_id',
    Detected_Pos_ID: 'detected_pos_id',
    IP: 'ip',

    // Position
    Position_Lat: 'position_lat',
    Position_Long: 'position_long',
    Position_Alt: 'position_alt',
    Velocity_North: 'velocity_north',
    Velocity_East: 'velocity_east',
    Velocity_Down: 'velocity_down',
    Yaw: 'yaw',

    // Flight Status
    Flight_Mode: 'flight_mode',
    Base_Mode: 'base_mode',
    System_Status: 'system_status',
    Is_Armed: 'is_armed',
    Is_Ready_To_Arm: 'is_ready_to_arm',

    // Mission
    State: 'state',
    Mission: 'mission',
    Last_Mission: 'last_mission',
    lastMission: 'last_mission', // Alternative naming
    Trigger_Time: 'trigger_time',
    Follow_Mode: 'follow_mode',

    // Battery
    Battery_Voltage: 'battery_voltage',

    // GPS
    Gps_Fix_Type: 'gps_fix_type',
    Satellites_Visible: 'satellites_visible',
    Hdop: 'hdop',
    Vdop: 'vdop',

    // Timestamps
    Timestamp: 'timestamp',
    Update_Time: 'update_time',
    Heartbeat_Last_Seen: 'heartbeat_last_seen',
  };

  const normalized = {};

  for (const [key, value] of Object.entries(droneData)) {
    // Use mapped name if exists, otherwise keep original key (might already be snake_case)
    const normalizedKey = legacyToSnakeCaseMap[key] || key;
    normalized[normalizedKey] = value;
  }

  return normalized;
}

/**
 * Normalize telemetry response containing multiple drones
 *
 * @param {Object} telemetryResponse - Response from /telemetry endpoint
 * @returns {Object} Normalized telemetry with all drones using snake_case
 *
 * @example
 * const response = { "1": { Position_Lat: 35.72 }, "2": { Position_Lat: 35.73 } };
 * const normalized = normalizeTelemetryResponse(response);
 * // { "1": { position_lat: 35.72 }, "2": { position_lat: 35.73 } }
 */
export function normalizeTelemetryResponse(telemetryResponse) {
  if (!telemetryResponse || typeof telemetryResponse !== 'object') {
    return telemetryResponse;
  }

  const normalized = {};

  for (const [droneId, droneData] of Object.entries(telemetryResponse)) {
    normalized[droneId] = normalizeDroneData(droneData);
  }

  return normalized;
}

/**
 * Get field value with fallback to legacy naming
 * Use this when you're unsure if data is normalized
 *
 * @param {Object} drone - Drone data object
 * @param {string} fieldKey - Field name constant from FIELD_NAMES
 * @param {*} defaultValue - Default value if field not found
 * @returns {*} Field value or default
 *
 * @example
 * const voltage = getField(drone, FIELD_NAMES.BATTERY_VOLTAGE, 0);
 */
export function getField(drone, fieldKey, defaultValue = undefined) {
  if (!drone || !fieldKey) {
    return defaultValue;
  }

  // Try snake_case (standard)
  if (drone[fieldKey] !== undefined) {
    return drone[fieldKey];
  }

  // Try to find legacy PascalCase equivalent
  const legacyMap = {
    'hw_id': ['hw_ID', 'HW_ID'],
    'pos_id': ['Pos_ID', 'POS_ID'],
    'detected_pos_id': ['Detected_Pos_ID'],
    'position_lat': ['Position_Lat'],
    'position_long': ['Position_Long'],
    'position_alt': ['Position_Alt'],
    'battery_voltage': ['Battery_Voltage'],
    'flight_mode': ['Flight_Mode'],
    'base_mode': ['Base_Mode'],
    'system_status': ['System_Status'],
    'is_armed': ['Is_Armed'],
    'is_ready_to_arm': ['Is_Ready_To_Arm'],
    'state': ['State'],
    'mission': ['Mission'],
    'last_mission': ['Last_Mission', 'lastMission'],
    'gps_fix_type': ['Gps_Fix_Type'],
    'satellites_visible': ['Satellites_Visible'],
    'hdop': ['Hdop'],
    'vdop': ['Vdop'],
    'timestamp': ['Timestamp'],
    'update_time': ['Update_Time'],
  };

  const legacyNames = legacyMap[fieldKey] || [];
  for (const legacyName of legacyNames) {
    if (drone[legacyName] !== undefined) {
      return drone[legacyName];
    }
  }

  return defaultValue;
}

/**
 * Best Practice Usage Examples:
 *
 * // 1. Direct access with FIELD_NAMES constant (recommended)
 * const voltage = drone[FIELD_NAMES.BATTERY_VOLTAGE];
 *
 * // 2. Normalize entire response (use in data fetching layer)
 * const normalized = normalizeTelemetryResponse(apiResponse);
 *
 * // 3. Safe access with fallback (use when data source uncertain)
 * const lat = getField(drone, FIELD_NAMES.POSITION_LAT, 0);
 */
