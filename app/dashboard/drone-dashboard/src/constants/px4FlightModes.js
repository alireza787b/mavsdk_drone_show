/**
 * PX4 Flight Mode Constants - Modern Implementation
 *
 * Based on latest PX4 v1.15+ and MAVLink Standard Modes Protocol
 * References:
 * - https://docs.px4.io/main/en/mavlink/standard_modes
 * - https://mavlink.io/en/services/standard_modes.html
 * - PX4-Autopilot/src/modules/commander/px4_custom_mode.h
 * - PX4-Autopilot/src/lib/modes/standard_modes.hpp
 */

// PX4 Main Mode definitions (upper 16 bits of custom_mode)
export const PX4_MAIN_MODES = {
  MANUAL: 1,
  ALTCTL: 2,      // Altitude Control
  POSCTL: 3,      // Position Control
  AUTO: 4,        // Auto modes (mission, RTL, etc.)
  ACRO: 5,        // Acrobatic mode
  OFFBOARD: 6,    // Offboard control
  STABILIZED: 7,  // Stabilized mode
  RATTITUDE: 8,   // Rate + Attitude mode
  SIMPLE: 9,      // Simple mode (if supported)
  TERMINATION: 10 // Flight termination
};

// PX4 Sub Mode definitions for AUTO main mode (lower 16 bits)
export const PX4_AUTO_SUB_MODES = {
  AUTO_READY: 1,     // Ready to start mission
  AUTO_TAKEOFF: 2,   // Automatic takeoff
  AUTO_LOITER: 3,    // Loiter/Hold at current position
  AUTO_MISSION: 4,   // Execute mission
  AUTO_RTL: 5,       // Return to Launch
  AUTO_LAND: 6,      // Automatic landing
  AUTO_RTGS: 7,      // Return to Ground Station
  AUTO_FOLLOW: 8,    // Follow mode
  AUTO_PRECLAND: 9,  // Precision landing
  AUTO_VTOL_TAKEOFF: 10 // VTOL takeoff
};

/**
 * Comprehensive PX4 custom_mode to flight mode name mapping
 * Format: custom_mode = (main_mode << 16) | sub_mode
 *
 * Updated for PX4 v1.15+ with comprehensive mode support
 */
export const PX4_FLIGHT_MODES = {
  // Special/Unknown states
  0: 'Initializing',        // Uninitialized or bootup state

  // Manual Control Modes (Direct pilot control)
  65536: 'Manual',          // MANUAL (1 << 16) - Full manual control
  131072: 'Altitude',       // ALTCTL (2 << 16) - Altitude stabilized
  196608: 'Position',       // POSCTL (3 << 16) - Position stabilized
  327680: 'Acro',          // ACRO (5 << 16) - Acrobatic mode
  393216: 'Offboard',      // OFFBOARD (6 << 16) - External control
  458752: 'Stabilized',    // STABILIZED (7 << 16) - Attitude stabilized
  524288: 'Rattitude',     // RATTITUDE (8 << 16) - Rate + Attitude
  589824: 'Simple',        // SIMPLE (9 << 16) - Simplified control
  655360: 'Termination',   // TERMINATION (10 << 16) - Flight termination

  // Auto Modes (Autonomous flight)
  262144: 'Auto',          // AUTO (4 << 16) - Base auto mode
  262145: 'Ready',         // AUTO_READY (4 << 16 | 1) - Mission ready
  262146: 'Takeoff',       // AUTO_TAKEOFF (4 << 16 | 2) - Auto takeoff
  262147: 'Hold',          // AUTO_LOITER (4 << 16 | 3) - Hold position
  262148: 'Mission',       // AUTO_MISSION (4 << 16 | 4) - Execute mission
  262149: 'Return',        // AUTO_RTL (4 << 16 | 5) - Return to launch
  262150: 'Land',          // AUTO_LAND (4 << 16 | 6) - Auto landing
  262151: 'RTGS',          // AUTO_RTGS (4 << 16 | 7) - Return to GS
  262152: 'Follow',        // AUTO_FOLLOW (4 << 16 | 8) - Follow target
  262153: 'Precision Land', // AUTO_PRECLAND (4 << 16 | 9) - Precision landing
  262154: 'VTOL Takeoff',  // AUTO_VTOL_TAKEOFF (4 << 16 | 10) - VTOL takeoff

  // Position Control sub-modes
  196609: 'Orbit',         // POSCTL with orbit sub-mode
  196610: 'Position Slow', // POSCTL with slow sub-mode

  // Extended/Custom modes observed in field
  33816576: 'Takeoff',     // Custom takeoff (516 << 16)
  100925440: 'Land',       // Custom land (1540 << 16)

  // Additional Offboard variations
  393217: 'Offboard',      // OFFBOARD with sub-mode 1
  393218: 'Offboard',      // OFFBOARD with sub-mode 2
  393219: 'Offboard',      // OFFBOARD with sub-mode 3
  393220: 'Offboard',      // OFFBOARD with sub-mode 4

  // Special Hold modes (GPS-independent)
  50593792: 'Hold',        // Special Hold variant
  84148224: 'Return'       // Special Return variant
};

/**
 * MAVLink System Status (MAV_STATE) enumeration
 * Used for overall system health assessment
 */
export const MAV_STATE = {
  0: 'Initializing',        // MAV_STATE_UNINIT
  1: 'Booting',            // MAV_STATE_BOOT
  2: 'Calibrating',        // MAV_STATE_CALIBRATING
  3: 'Standby',            // MAV_STATE_STANDBY
  4: 'Active',             // MAV_STATE_ACTIVE
  5: 'Critical',           // MAV_STATE_CRITICAL
  6: 'Emergency',          // MAV_STATE_EMERGENCY
  7: 'Poweroff',          // MAV_STATE_POWEROFF
  8: 'Flight Termination'  // MAV_STATE_FLIGHT_TERMINATION
};

/**
 * Modern flight mode detection with fallback logic
 * @param {number} customMode - PX4 custom_mode from HEARTBEAT message
 * @returns {string} Human-readable flight mode name
 */
export const getFlightModeName = (customMode) => {
  // Handle null/undefined/invalid inputs
  if (customMode === null || customMode === undefined) {
    return 'No Data';
  }

  // Convert to number if string
  const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

  // Handle NaN or invalid numbers
  if (isNaN(mode)) {
    return 'Invalid Mode';
  }

  // Direct lookup first
  if (PX4_FLIGHT_MODES[mode]) {
    return PX4_FLIGHT_MODES[mode];
  }

  // Intelligent fallback for unmapped modes
  const mainMode = (mode >> 16) & 0xFFFF;
  const subMode = mode & 0xFFFF;

  // Handle known main modes with unknown sub-modes
  switch (mainMode) {
    case PX4_MAIN_MODES.MANUAL:
      return 'Manual';
    case PX4_MAIN_MODES.ALTCTL:
      return 'Altitude';
    case PX4_MAIN_MODES.POSCTL:
      return subMode === 0 ? 'Position' : `Position (${subMode})`;
    case PX4_MAIN_MODES.AUTO:
      // Handle AUTO sub-modes
      switch (subMode) {
        case 1: return 'Ready';
        case 2: return 'Takeoff';
        case 3: return 'Hold';
        case 4: return 'Mission';
        case 5: return 'Return';
        case 6: return 'Land';
        case 7: return 'RTGS';
        case 8: return 'Follow';
        case 9: return 'Precision Land';
        case 10: return 'VTOL Takeoff';
        default: return `Auto (${subMode})`;
      }
    case PX4_MAIN_MODES.ACRO:
      return 'Acro';
    case PX4_MAIN_MODES.OFFBOARD:
      return 'Offboard';
    case PX4_MAIN_MODES.STABILIZED:
      return 'Stabilized';
    case PX4_MAIN_MODES.RATTITUDE:
      return 'Rattitude';
    case PX4_MAIN_MODES.TERMINATION:
      return 'Termination';

    // Handle custom main modes observed in field
    case 516:
      return 'Takeoff';
    case 1540:
      return 'Land';

    default:
      // Final fallback with detailed info
      if (mode === 0) {
        return 'Initializing';
      }
      return `Unknown (${mode})`;
  }
};

/**
 * Get human-readable system status from MAV_STATE value
 * @param {number} systemStatus - System status from HEARTBEAT message
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

  return MAV_STATE[status] || `Unknown Status (${status})`;
};

/**
 * Check if drone is in a safe flight mode for operations
 * @param {number} customMode - PX4 custom_mode value
 * @returns {boolean} True if in safe mode
 */
export const isSafeFlightMode = (customMode) => {
  const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

  if (isNaN(mode)) return false;

  const safeModes = [
    196608,   // Position
    262147,   // Hold
    262149,   // Return
    262150,   // Land
    50593792  // Hold (GPS-less)
  ];

  return safeModes.includes(mode);
};

/**
 * Check if system is ready based on system status
 * @param {number} systemStatus - MAV_STATE value
 * @returns {boolean} True if system is ready
 */
export const isSystemReady = (systemStatus) => {
  const status = typeof systemStatus === 'string' ? parseInt(systemStatus, 10) : systemStatus;

  if (isNaN(status)) return false;

  // STANDBY (3) or ACTIVE (4) states indicate readiness
  return status >= 3 && status <= 4;
};

/**
 * Get flight mode category for styling/grouping
 * @param {number} customMode - PX4 custom_mode value
 * @returns {string} Mode category
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

    case PX4_MAIN_MODES.TERMINATION:
      return 'emergency';

    default:
      return 'custom';
  }
};