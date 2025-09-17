//app/dashboard/drone-dashboard/src/utilities/flightModeUtils.js
import { 
  getFlightModeName, 
  getSystemStatusName, 
  isSafeFlightMode, 
  isSystemReady 
} from '../constants/px4FlightModes';

/**
 * Get flight mode title from PX4 custom_mode
 * @param {number} customMode - PX4 custom_mode value
 * @returns {string} Human-readable flight mode name
 */
export const getFlightModeTitle = (customMode) => {
  const modeName = getFlightModeName(customMode);

  // Add debug logging for unmapped modes
  if (modeName.includes('Unknown') && customMode !== 0) {
    console.warn(`Unknown flight mode detected: ${customMode}. This should be added to PX4_FLIGHT_MODES mapping.`);

    // Try to decode the mode to help with debugging
    const mainMode = (customMode >> 16) & 0xFFFF;
    const subMode = customMode & 0xFFFF;
    console.warn(`Decoded - Main Mode: ${mainMode}, Sub Mode: ${subMode}`);

    // Intelligent fallback detection for common modes
    if (mainMode === 6) {
      console.warn('This is an OFFBOARD mode (main mode 6). Expected custom_mode: 393216');
      return 'Offboard*'; // Mark as offboard but with asterisk to indicate detection issue
    } else if (mainMode === 516) {
      console.warn('Detected custom takeoff mode');
      return 'Takeoff*';
    } else if (mainMode === 1540) {
      console.warn('Detected custom land mode');
      return 'Land*';
    } else if (mainMode === 4) {
      // Auto modes with unknown sub-modes
      if (subMode === 2) return 'Takeoff*';
      if (subMode === 6) return 'Land*';
      if (subMode === 3) return 'Hold*';
      if (subMode === 5) return 'Return*';
      return 'Auto*';
    }

    // Generic fallback with mode info
    return `Unknown (${mainMode}:${subMode})`;
  }

  return modeName;
};

/**
 * Get system status title from MAV_STATE value
 * @param {number} systemStatus - MAV_STATE value  
 * @returns {string} Human-readable system status
 */
export const getSystemStatusTitle = (systemStatus) => {
  return getSystemStatusName(systemStatus);
};

/**
 * Check if drone is in safe flight mode
 * @param {number} customMode - PX4 custom_mode value
 * @returns {boolean} True if in safe mode
 */
export const isSafeMode = (customMode) => {
  return isSafeFlightMode(customMode);
};

/**
 * Check if system is ready for operations
 * @param {number} systemStatus - MAV_STATE value
 * @returns {boolean} True if system is ready
 */
export const isReady = (systemStatus) => {
  return isSystemReady(systemStatus);
};