/**
 * PX4 Flight Mode Constants - Official Standards Implementation
 *
 * Based on official PX4-Autopilot source code v1.15+
 * References:
 * - PX4-Autopilot/src/modules/commander/px4_custom_mode.h (Official definitions)
 * - MAVLink common.xml protocol specification
 * - PX4 Developer Guide flight mode documentation
 * - Tested against real PX4 HEARTBEAT messages
 *
 * PX4 stores custom_mode as a little-endian union:
 * - bits 0..15: reserved
 * - bits 16..23: main_mode
 * - bits 24..31: sub_mode
 *
 * Therefore an AUTO mission heartbeat is 0x04040000, not 0x00040004.
 */

/**
 * Official PX4 Main Mode Definitions (bits 16..23 of custom_mode)
 * Source: PX4-Autopilot/src/modules/commander/px4_custom_mode.h
 */
export const PX4_MAIN_MODES = {
  MANUAL: 1,
  ALTCTL: 2,
  POSCTL: 3,
  AUTO: 4,
  ACRO: 5,
  OFFBOARD: 6,
  STABILIZED: 7,
  RATTITUDE: 8
};

/**
 * Official PX4 Auto Sub-Mode Definitions (bits 24..31 when main_mode = AUTO)
 * Source: PX4-Autopilot/src/modules/commander/px4_custom_mode.h
 */
export const PX4_AUTO_SUB_MODES = {
  AUTO_READY: 1,
  AUTO_TAKEOFF: 2,
  AUTO_LOITER: 3,
  AUTO_MISSION: 4,
  AUTO_RTL: 5,
  AUTO_LAND: 6,
  AUTO_RESERVED_DO_NOT_USE: 7,
  AUTO_FOLLOW_TARGET: 8,
  AUTO_PRECLAND: 9
};

const UINT32_MAX = 0xFFFFFFFF;

const normalizeUint32 = (value) => {
  if (typeof value === 'string' && value.trim() === '') {
    return null;
  }

  const numericValue = typeof value === 'string' ? Number(value) : value;
  if (!Number.isInteger(numericValue) || numericValue < 0 || numericValue > UINT32_MAX) {
    return null;
  }

  return numericValue >>> 0;
};

/**
 * Encode the two PX4 mode bytes into MAVLink HEARTBEAT.custom_mode.
 *
 * @param {number} mainMode - PX4_CUSTOM_MAIN_MODE value
 * @param {number} [subMode=0] - PX4_CUSTOM_SUB_MODE value
 * @returns {number} Unsigned 32-bit PX4 custom_mode
 */
export const encodePx4CustomMode = (mainMode, subMode = 0) => {
  if (
    !Number.isInteger(mainMode) || mainMode < 0 || mainMode > 0xFF ||
    !Number.isInteger(subMode) || subMode < 0 || subMode > 0xFF
  ) {
    throw new RangeError('PX4 main mode and sub-mode must be unsigned bytes');
  }

  return (((subMode & 0xFF) << 24) | ((mainMode & 0xFF) << 16)) >>> 0;
};

/**
 * Decode MAVLink HEARTBEAT.custom_mode using PX4's px4_custom_mode union.
 *
 * @param {number|string} customMode - Unsigned PX4 custom_mode value
 * @returns {{customMode: number, reserved: number, mainMode: number, subMode: number}|null}
 */
export const decodePx4CustomMode = (customMode) => {
  const mode = normalizeUint32(customMode);
  if (mode === null) {
    return null;
  }

  return {
    customMode: mode,
    reserved: mode & 0xFFFF,
    mainMode: (mode >>> 16) & 0xFF,
    subMode: (mode >>> 24) & 0xFF
  };
};

const AUTO_SUB_MODE_NAMES = {
  [PX4_AUTO_SUB_MODES.AUTO_READY]: 'Ready',
  [PX4_AUTO_SUB_MODES.AUTO_TAKEOFF]: 'Takeoff',
  [PX4_AUTO_SUB_MODES.AUTO_LOITER]: 'Hold',
  [PX4_AUTO_SUB_MODES.AUTO_MISSION]: 'Mission',
  [PX4_AUTO_SUB_MODES.AUTO_RTL]: 'Return',
  [PX4_AUTO_SUB_MODES.AUTO_LAND]: 'Land',
  [PX4_AUTO_SUB_MODES.AUTO_RESERVED_DO_NOT_USE]: 'Auto Reserved',
  [PX4_AUTO_SUB_MODES.AUTO_FOLLOW_TARGET]: 'Follow Target',
  [PX4_AUTO_SUB_MODES.AUTO_PRECLAND]: 'Precision Land'
};

/**
 * Official PX4 Flight Mode Mappings.
 * Keys are generated from PX4's byte layout to keep the table and decoder aligned.
 */
export const PX4_FLIGHT_MODES = {
  // System States
  0: 'Initializing',

  // Manual Control Modes
  [encodePx4CustomMode(PX4_MAIN_MODES.MANUAL)]: 'Manual',
  [encodePx4CustomMode(PX4_MAIN_MODES.ALTCTL)]: 'Altitude',
  [encodePx4CustomMode(PX4_MAIN_MODES.POSCTL)]: 'Position',
  [encodePx4CustomMode(PX4_MAIN_MODES.ACRO)]: 'Acro',
  [encodePx4CustomMode(PX4_MAIN_MODES.OFFBOARD)]: 'Offboard',
  [encodePx4CustomMode(PX4_MAIN_MODES.STABILIZED)]: 'Stabilized',
  [encodePx4CustomMode(PX4_MAIN_MODES.RATTITUDE)]: 'Rattitude',

  // Auto Modes with Sub-modes
  [encodePx4CustomMode(PX4_MAIN_MODES.AUTO)]: 'Auto',
  ...Object.fromEntries(
    Object.entries(AUTO_SUB_MODE_NAMES).map(([subMode, name]) => [
      encodePx4CustomMode(PX4_MAIN_MODES.AUTO, Number(subMode)),
      name
    ])
  )
};

/**
 * Official MAVLink System Status (MAV_STATE) enumeration
 * Source: MAVLink common.xml specification
 */
export const MAV_STATE = {
  0: 'Uninit',
  1: 'Boot',
  2: 'Calibrating',
  3: 'Standby',
  4: 'Active',
  5: 'Critical',
  6: 'Emergency',
  7: 'Poweroff',
  8: 'Flight Termination'
};

/**
 * Standards-compliant flight mode detection with PX4 decoding
 * @param {number} customMode - PX4 custom_mode from HEARTBEAT message
 * @returns {string} Human-readable flight mode name
 */
export const getFlightModeName = (customMode) => {
  if (customMode === null || customMode === undefined) {
    return 'No Data';
  }

  const decoded = decodePx4CustomMode(customMode);
  if (!decoded) {
    return 'Invalid Mode';
  }

  const { customMode: mode, mainMode, subMode } = decoded;

  // Direct lookup for known modes
  if (Object.prototype.hasOwnProperty.call(PX4_FLIGHT_MODES, mode)) {
    return PX4_FLIGHT_MODES[mode];
  }

  // Handle main modes with unknown sub-modes
  switch (mainMode) {
    case PX4_MAIN_MODES.MANUAL:
      return 'Manual';
    case PX4_MAIN_MODES.ALTCTL:
      return 'Altitude';
    case PX4_MAIN_MODES.POSCTL:
      return 'Position';
    case PX4_MAIN_MODES.AUTO:
      return AUTO_SUB_MODE_NAMES[subMode] || (subMode === 0 ? 'Auto' : `Auto.${subMode}`);
    case PX4_MAIN_MODES.ACRO:
      return 'Acro';
    case PX4_MAIN_MODES.OFFBOARD:
      return 'Offboard';
    case PX4_MAIN_MODES.STABILIZED:
      return 'Stabilized';
    case PX4_MAIN_MODES.RATTITUDE:
      return 'Rattitude';

    default:
      return `Unknown (${mode})`;
  }
};

/**
 * Get system status name from MAV_STATE value
 * @param {number} systemStatus - MAV_STATE from HEARTBEAT message
 * @returns {string} Human-readable system status
 */
export const getSystemStatusName = (systemStatus) => {
  if (systemStatus === null || systemStatus === undefined) {
    return 'No Data';
  }

  const status = typeof systemStatus === 'string' ? parseInt(systemStatus, 10) : systemStatus;

  if (isNaN(status)) {
    return 'Invalid Status';
  }

  return MAV_STATE[status] || `Unknown (${status})`;
};

/**
 * Check if flight mode allows manual pilot control
 * @param {number} customMode - PX4 custom_mode value
 * @returns {boolean} True if manual control available
 */
export const isSafeFlightMode = (customMode) => {
  const decoded = decodePx4CustomMode(customMode);
  if (!decoded) return false;

  // Modes with direct pilot control are considered "safe" by this UI helper.
  return [
    PX4_MAIN_MODES.MANUAL,
    PX4_MAIN_MODES.ALTCTL,
    PX4_MAIN_MODES.POSCTL,
    PX4_MAIN_MODES.ACRO,
    PX4_MAIN_MODES.STABILIZED,
    PX4_MAIN_MODES.RATTITUDE
  ].includes(decoded.mainMode);
};

/**
 * Check if system is ready for operations
 * @param {number} systemStatus - MAV_STATE value
 * @returns {boolean} True if system ready
 */
export const isSystemReady = (systemStatus) => {
  const status = typeof systemStatus === 'string' ? parseInt(systemStatus, 10) : systemStatus;

  if (isNaN(status)) return false;

  // Standby (3) and Active (4) are operational states
  return status === 3 || status === 4;
};

/**
 * Get flight mode category for UI styling
 * @param {number} customMode - PX4 custom_mode value
 * @returns {string} Category: 'manual', 'auto', 'offboard', or 'unknown'
 */
export const getFlightModeCategory = (customMode) => {
  const decoded = decodePx4CustomMode(customMode);
  if (!decoded) return 'unknown';

  switch (decoded.mainMode) {
    case PX4_MAIN_MODES.MANUAL:
    case PX4_MAIN_MODES.ALTCTL:
    case PX4_MAIN_MODES.POSCTL:
    case PX4_MAIN_MODES.ACRO:
    case PX4_MAIN_MODES.STABILIZED:
    case PX4_MAIN_MODES.RATTITUDE:
      return 'manual';

    case PX4_MAIN_MODES.AUTO:
      return 'auto';

    case PX4_MAIN_MODES.OFFBOARD:
      return 'offboard';

    default:
      return 'unknown';
  }
};
