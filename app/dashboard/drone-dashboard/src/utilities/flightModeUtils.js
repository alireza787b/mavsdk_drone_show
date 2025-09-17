/**
 * Flight Mode Utilities - Modern Implementation
 *
 * Based on latest PX4 v1.15+ and MAVLink Standard Modes Protocol
 * Provides robust flight mode detection with comprehensive fallback logic
 */

import {
  getFlightModeName,
  getSystemStatusName,
  isSafeFlightMode,
  isSystemReady,
  getFlightModeCategory,
  PX4_MAIN_MODES
} from '../constants/px4FlightModes';

/**
 * Get flight mode title with enhanced debugging and fallback
 * @param {number|string} customMode - PX4 custom_mode value
 * @returns {string} Human-readable flight mode name
 */
export const getFlightModeTitle = (customMode) => {
  try {
    // Handle edge cases first
    if (customMode === null || customMode === undefined) {
      console.warn('Flight mode is null/undefined');
      return 'No Data';
    }

    // Convert to number and validate
    const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

    if (isNaN(mode)) {
      console.error(`Invalid flight mode value: ${customMode} (type: ${typeof customMode})`);
      return 'Invalid Mode';
    }

    // Get the mode name using modern detection
    const modeName = getFlightModeName(mode);

    // Enhanced debugging for unknown modes
    if (modeName.includes('Unknown') && mode !== 0) {
      const mainMode = (mode >> 16) & 0xFFFF;
      const subMode = mode & 0xFFFF;

      console.group(`🔍 Flight Mode Debug - Unknown Mode Detected`);
      console.warn(`Raw custom_mode: ${mode}`);
      console.warn(`Main mode: ${mainMode} (0x${mainMode.toString(16)})`);
      console.warn(`Sub mode: ${subMode} (0x${subMode.toString(16)})`);
      console.warn(`Binary: ${mode.toString(2)}`);
      console.warn(`Hex: 0x${mode.toString(16)}`);

      // Check for known patterns
      if (mainMode === PX4_MAIN_MODES.OFFBOARD) {
        console.warn('✓ This is OFFBOARD mode - should be detected');
      } else if (mainMode === PX4_MAIN_MODES.AUTO) {
        console.warn(`✓ This is AUTO mode with sub-mode ${subMode}`);
      } else if (mainMode === 516) {
        console.warn('✓ This is custom TAKEOFF mode (516)');
      } else if (mainMode === 1540) {
        console.warn('✓ This is custom LAND mode (1540)');
      } else {
        console.warn('❌ Unknown main mode - needs to be added to mapping');
      }

      console.groupEnd();
    }

    // Additional validation logging
    if (mode !== 0 && !modeName.includes('Unknown')) {
      console.debug(`✓ Flight mode detected: ${mode} → ${modeName}`);
    }

    return modeName;

  } catch (error) {
    console.error('Error in getFlightModeTitle:', error);
    return 'Error';
  }
};

/**
 * Get system status title with enhanced error handling
 * @param {number|string} systemStatus - MAV_STATE value
 * @returns {string} Human-readable system status
 */
export const getSystemStatusTitle = (systemStatus) => {
  try {
    if (systemStatus === null || systemStatus === undefined) {
      return 'No Data';
    }

    const status = typeof systemStatus === 'string' ? parseInt(systemStatus, 10) : systemStatus;

    if (isNaN(status)) {
      console.error(`Invalid system status value: ${systemStatus}`);
      return 'Invalid Status';
    }

    const statusName = getSystemStatusName(status);

    if (statusName.includes('Unknown')) {
      console.warn(`Unknown system status: ${status}`);
    }

    return statusName;

  } catch (error) {
    console.error('Error in getSystemStatusTitle:', error);
    return 'Error';
  }
};

/**
 * Check if drone is in safe flight mode with enhanced validation
 * @param {number|string} customMode - PX4 custom_mode value
 * @returns {boolean} True if in safe mode
 */
export const isSafeMode = (customMode) => {
  try {
    const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

    if (isNaN(mode)) {
      return false;
    }

    return isSafeFlightMode(mode);

  } catch (error) {
    console.error('Error in isSafeMode:', error);
    return false;
  }
};

/**
 * Check if system is ready with enhanced validation
 * @param {number|string} systemStatus - MAV_STATE value
 * @returns {boolean} True if system is ready
 */
export const isReady = (systemStatus) => {
  try {
    const status = typeof systemStatus === 'string' ? parseInt(systemStatus, 10) : systemStatus;

    if (isNaN(status)) {
      return false;
    }

    return isSystemReady(status);

  } catch (error) {
    console.error('Error in isReady:', error);
    return false;
  }
};

/**
 * Get flight mode category for styling
 * @param {number|string} customMode - PX4 custom_mode value
 * @returns {string} Mode category
 */
export const getFlightModeStyle = (customMode) => {
  try {
    const mode = typeof customMode === 'string' ? parseInt(customMode, 10) : customMode;

    if (isNaN(mode)) {
      return 'unknown';
    }

    return getFlightModeCategory(mode);

  } catch (error) {
    console.error('Error in getFlightModeStyle:', error);
    return 'unknown';
  }
};

/**
 * Comprehensive flight mode validation and diagnosis
 * @param {Object} droneData - Complete drone telemetry data
 * @returns {Object} Diagnostic information
 */
export const diagnoseFlightMode = (droneData) => {
  const diagnosis = {
    isValid: false,
    mode: null,
    modeName: 'Unknown',
    category: 'unknown',
    issues: [],
    recommendations: []
  };

  try {
    // Check if flight mode data exists
    if (!droneData || typeof droneData !== 'object') {
      diagnosis.issues.push('No drone data provided');
      return diagnosis;
    }

    const flightMode = droneData.Flight_Mode;

    if (flightMode === null || flightMode === undefined) {
      diagnosis.issues.push('Flight_Mode field is missing from telemetry');
      diagnosis.recommendations.push('Check backend telemetry data structure');
      return diagnosis;
    }

    // Validate and convert mode
    const mode = typeof flightMode === 'string' ? parseInt(flightMode, 10) : flightMode;

    if (isNaN(mode)) {
      diagnosis.issues.push(`Flight_Mode is not a valid number: ${flightMode}`);
      diagnosis.recommendations.push('Check data type conversion in backend');
      return diagnosis;
    }

    // Get mode information
    diagnosis.mode = mode;
    diagnosis.modeName = getFlightModeName(mode);
    diagnosis.category = getFlightModeCategory(mode);

    // Check if mode is recognized
    if (diagnosis.modeName.includes('Unknown')) {
      diagnosis.issues.push(`Unrecognized flight mode: ${mode}`);

      const mainMode = (mode >> 16) & 0xFFFF;
      const subMode = mode & 0xFFFF;

      diagnosis.recommendations.push(`Add mapping for main_mode=${mainMode}, sub_mode=${subMode}`);

      // Check for common patterns
      if (mainMode === 6) {
        diagnosis.recommendations.push('This appears to be OFFBOARD mode - check standard mapping');
      } else if (mainMode === 4) {
        diagnosis.recommendations.push('This appears to be AUTO mode - check sub-mode mapping');
      }
    } else {
      diagnosis.isValid = true;
    }

    return diagnosis;

  } catch (error) {
    diagnosis.issues.push(`Error during diagnosis: ${error.message}`);
    return diagnosis;
  }
};

/**
 * Debug utility to log comprehensive flight mode information
 * @param {Object} droneData - Complete drone telemetry data
 * @param {string} droneId - Drone identifier for logging
 */
export const debugFlightMode = (droneData, droneId = 'Unknown') => {
  if (!console.group) return; // Skip if debugging not available

  const diagnosis = diagnoseFlightMode(droneData);

  console.group(`🚁 Flight Mode Debug - Drone ${droneId}`);
  console.log('Raw telemetry data:', {
    Flight_Mode: droneData?.Flight_Mode,
    System_Status: droneData?.System_Status,
    Is_Armed: droneData?.Is_Armed,
    timestamp: new Date().toISOString()
  });

  console.log('Diagnosis:', diagnosis);

  if (diagnosis.issues.length > 0) {
    console.warn('Issues found:', diagnosis.issues);
    console.info('Recommendations:', diagnosis.recommendations);
  }

  console.groupEnd();
};