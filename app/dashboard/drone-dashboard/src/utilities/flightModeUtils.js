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