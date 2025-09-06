/**
 * PX4 Flight Mode Constants
 * 
 * These constants map PX4 custom_mode values to human-readable flight mode names.
 * Based on official PX4 documentation: https://docs.px4.io/main/en/flight_modes/
 * 
 * The custom_mode field from HEARTBEAT message contains PX4-specific flight mode values.
 * These values are different from MAVLink base_mode which only contains arming flags.
 * 
 * Reference: PX4-Autopilot/src/modules/commander/px4_custom_mode.h
 */

// PX4 Main Mode definitions (upper 16 bits of custom_mode)
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

// PX4 Sub Mode definitions for AUTO main mode (lower 16 bits)
export const PX4_AUTO_SUB_MODES = {
  AUTO_READY: 1,
  AUTO_TAKEOFF: 2,
  AUTO_LOITER: 3,
  AUTO_MISSION: 4,
  AUTO_RTL: 5,
  AUTO_LAND: 6,
  AUTO_FOLLOW: 8,
  AUTO_PRECLAND: 9
};

/**
 * Complete PX4 custom_mode to flight mode name mapping
 * Format: custom_mode = (main_mode << 16) | sub_mode
 */
export const PX4_FLIGHT_MODES = {
  // Manual modes
  65536: 'Manual',         // MANUAL (1 << 16)
  131072: 'Altitude',      // ALTCTL (2 << 16)
  196608: 'Position',      // POSCTL (3 << 16)
  327680: 'Acro',         // ACRO (5 << 16)
  393216: 'Offboard',     // OFFBOARD (6 << 16)
  458752: 'Stabilized',   // STABILIZED (7 << 16)
  524288: 'Rattitude',    // RATTITUDE (8 << 16)

  // Auto modes (AUTO main mode with sub modes)
  262145: 'Ready',         // AUTO_READY (4 << 16 | 1)
  262146: 'Takeoff',       // AUTO_TAKEOFF (4 << 16 | 2)
  262147: 'Hold',          // AUTO_LOITER (4 << 16 | 3) - Hold/Loiter
  262148: 'Mission',       // AUTO_MISSION (4 << 16 | 4)
  262149: 'Return',        // AUTO_RTL (4 << 16 | 5) - Return to Launch
  262150: 'Land',          // AUTO_LAND (4 << 16 | 6)
  262152: 'Follow',        // AUTO_FOLLOW (4 << 16 | 8)
  262153: 'Precision Land' // AUTO_PRECLAND (4 << 16 | 9)
};

/**
 * MAVLink System Status (MAV_STATE) enumeration
 * Used for overall system health assessment
 */
export const MAV_STATE = {
  0: 'Uninit',      // MAV_STATE_UNINIT
  1: 'Boot',        // MAV_STATE_BOOT
  2: 'Calibrating', // MAV_STATE_CALIBRATING
  3: 'Standby',     // MAV_STATE_STANDBY
  4: 'Active',      // MAV_STATE_ACTIVE
  5: 'Critical',    // MAV_STATE_CRITICAL
  6: 'Emergency',   // MAV_STATE_EMERGENCY
  7: 'Poweroff',    // MAV_STATE_POWEROFF
  8: 'Flight Termination' // MAV_STATE_FLIGHT_TERMINATION
};

/**
 * Get human-readable flight mode name from PX4 custom_mode value
 * @param {number} customMode - PX4 custom_mode from HEARTBEAT message
 * @returns {string} Human-readable flight mode name
 */
export const getFlightModeName = (customMode) => {
  return PX4_FLIGHT_MODES[customMode] || `Unknown (${customMode})`;
};

/**
 * Get human-readable system status from MAV_STATE value
 * @param {number} systemStatus - System status from HEARTBEAT message
 * @returns {string} Human-readable system status
 */
export const getSystemStatusName = (systemStatus) => {
  return MAV_STATE[systemStatus] || `Unknown (${systemStatus})`;
};

/**
 * Check if drone is in a safe flight mode for operations
 * @param {number} customMode - PX4 custom_mode value
 * @returns {boolean} True if in safe mode (Position, Hold, etc.)
 */
export const isSafeFlightMode = (customMode) => {
  const safeMode = [196608, 262147, 262149]; // Position, Hold, Return
  return safeMode.includes(customMode);
};

/**
 * Check if drone is ready to arm based on system status
 * @param {number} systemStatus - MAV_STATE value
 * @returns {boolean} True if system is ready (STANDBY or ACTIVE)
 */
export const isSystemReady = (systemStatus) => {
  return systemStatus >= 3 && systemStatus <= 4; // STANDBY or ACTIVE
};