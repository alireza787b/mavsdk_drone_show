/**
 * Flight Mode Utilities
 * Clean, professional implementation for PX4/MAVLink flight mode handling
 */

import {
  decodePx4CustomMode,
  getFlightModeCategory as getPx4FlightModeCategory,
  getFlightModeName,
  getSystemStatusName,
  isSafeFlightMode,
  isSystemReady
} from '../constants/px4FlightModes';

/**
 * Get flight mode title with proper error handling
 * @param {number|string} customMode - PX4 custom_mode value
 * @returns {string} Human-readable flight mode name
 */
export const getFlightModeTitle = (customMode) => {
  if (customMode === null || customMode === undefined) {
    return 'No Data';
  }

  const decoded = decodePx4CustomMode(customMode);
  if (!decoded) {
    console.warn(`Invalid flight mode value: ${customMode}`);
    return 'Invalid Mode';
  }

  const modeName = getFlightModeName(decoded.customMode);

  // Log unknown modes for debugging
  if (modeName.includes('Unknown') && decoded.customMode !== 0) {
    console.warn(
      `Unknown flight mode: ${decoded.customMode} ` +
      `(Main: ${decoded.mainMode}, Sub: ${decoded.subMode})`
    );
  }

  return modeName;
};

/**
 * Get system status title with error handling
 * @param {number|string} systemStatus - MAV_STATE value
 * @returns {string} Human-readable system status
 */
export const getSystemStatusTitle = (systemStatus) => {
  if (systemStatus === null || systemStatus === undefined) {
    return 'No Data';
  }

  const status = typeof systemStatus === 'string' ? parseInt(systemStatus, 10) : systemStatus;

  if (isNaN(status)) {
    console.warn(`Invalid system status value: ${systemStatus}`);
    return 'Invalid Status';
  }

  return getSystemStatusName(status);
};

/**
 * Check if drone is in safe flight mode
 * @param {number|string} customMode - PX4 custom_mode value
 * @returns {boolean} True if in safe mode
 */
export const isSafeMode = (customMode) => {
  return isSafeFlightMode(customMode);
};

/**
 * Check if system is ready
 * @param {number|string} systemStatus - MAV_STATE value
 * @returns {boolean} True if system is ready
 */
export const isReady = (systemStatus) => {
  const status = typeof systemStatus === 'string' ? parseInt(systemStatus, 10) : systemStatus;
  return !isNaN(status) && isSystemReady(status);
};

/**
 * Get flight mode category for UI styling
 * @param {number|string} customMode - PX4 custom_mode value
 * @returns {string} Category: 'manual', 'auto', 'offboard', or 'unknown'
 */
export const getFlightModeCategory = (customMode) => {
  return getPx4FlightModeCategory(customMode);
};
