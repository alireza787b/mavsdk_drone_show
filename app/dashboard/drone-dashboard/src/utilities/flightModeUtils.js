/**
 * Flight Mode Utilities
 * Clean, professional implementation for PX4/MAVLink flight mode handling
 */

import {
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

  const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

  if (isNaN(mode)) {
    console.warn(`Invalid flight mode value: ${customMode}`);
    return 'Invalid Mode';
  }

  const modeName = getFlightModeName(mode);

  // Log unknown modes for debugging
  if (modeName.includes('Unknown') && mode !== 0) {
    const mainMode = (mode >> 16) & 0xFFFF;
    const subMode = mode & 0xFFFF;
    console.warn(`Unknown flight mode: ${mode} (Main: ${mainMode}, Sub: ${subMode})`);
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
  const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;
  return !isNaN(mode) && isSafeFlightMode(mode);
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