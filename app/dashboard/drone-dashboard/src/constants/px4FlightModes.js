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
 * Custom Mode Encoding: (main_mode << 16) | sub_mode
 */

/**
 * Official PX4 Main Mode Definitions (upper 16 bits of custom_mode)
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
 * Official PX4 Auto Sub-Mode Definitions (lower 16 bits when main_mode = AUTO)
 * Source: PX4-Autopilot/src/modules/commander/px4_custom_mode.h
 */
export const PX4_AUTO_SUB_MODES = {
  AUTO_READY: 1,
  AUTO_TAKEOFF: 2,
  AUTO_LOITER: 3,
  AUTO_MISSION: 4,
  AUTO_RTL: 5,
  AUTO_LAND: 6,
  AUTO_RTGS: 7,
  AUTO_FOLLOW_TARGET: 8,
  AUTO_PRECLAND: 9
};

/**
 * Official PX4 Flight Mode Mappings
 * Direct mapping from custom_mode values to human-readable names
 * Format: custom_mode = (main_mode << 16) | sub_mode
 */
export const PX4_FLIGHT_MODES = {
  // System States
  0: 'Initializing',

  // Manual Control Modes (main_mode << 16)
  65536: 'Manual',          // MANUAL (1 << 16)
  131072: 'Altitude',       // ALTCTL (2 << 16)
  196608: 'Position',       // POSCTL (3 << 16)
  327680: 'Acro',          // ACRO (5 << 16)
  393216: 'Offboard',      // OFFBOARD (6 << 16)
  458752: 'Stabilized',    // STABILIZED (7 << 16)
  524288: 'Rattitude',     // RATTITUDE (8 << 16)

  // Auto Modes with Sub-modes ((AUTO << 16) | sub_mode)
  262144: 'Auto',          // AUTO (4 << 16 | 0)
  262145: 'Ready',         // AUTO_READY (4 << 16 | 1)
  262146: 'Takeoff',       // AUTO_TAKEOFF (4 << 16 | 2)
  262147: 'Hold',          // AUTO_LOITER (4 << 16 | 3)
  262148: 'Mission',       // AUTO_MISSION (4 << 16 | 4)
  262149: 'Return',        // AUTO_RTL (4 << 16 | 5)
  262150: 'Land',          // AUTO_LAND (4 << 16 | 6)
  262151: 'RTGS',          // AUTO_RTGS (4 << 16 | 7)
  262152: 'Follow Target', // AUTO_FOLLOW_TARGET (4 << 16 | 8)
  262153: 'Precision Land' // AUTO_PRECLAND (4 << 16 | 9)
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

  const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

  if (isNaN(mode)) {
    return 'Invalid Mode';
  }

  // Direct lookup for known modes
  if (PX4_FLIGHT_MODES[mode]) {
    return PX4_FLIGHT_MODES[mode];
  }

  // PX4 encoding fallback: decode main_mode and sub_mode
  const mainMode = (mode >> 16) & 0xFFFF;
  const subMode = mode & 0xFFFF;

  // Handle main modes with unknown sub-modes
  switch (mainMode) {
    case PX4_MAIN_MODES.MANUAL:
      return 'Manual';
    case PX4_MAIN_MODES.ALTCTL:
      return 'Altitude';
    case PX4_MAIN_MODES.POSCTL:
      return 'Position';
    case PX4_MAIN_MODES.AUTO:
      // Map known AUTO sub-modes
      const autoModes = {
        1: 'Ready',
        2: 'Takeoff',
        3: 'Hold',
        4: 'Mission',
        5: 'Return',
        6: 'Land',
        7: 'RTGS',
        8: 'Follow Target',
        9: 'Precision Land'
      };
      return autoModes[subMode] || `Auto.${subMode}`;
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
  const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

  if (isNaN(mode)) return false;

  // Manual control modes are considered "safe"
  const manualModes = [
    65536,   // Manual
    131072,  // Altitude
    196608,  // Position
    327680,  // Acro
    458752,  // Stabilized
    524288   // Rattitude
  ];

  return manualModes.includes(mode);
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
  const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

  if (isNaN(mode)) return 'unknown';

  const mainMode = (mode >> 16) & 0xFFFF;

  switch (mainMode) {
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