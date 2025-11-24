/**
 * Mission Utilities
 * Provides human-readable mission names for the drone dashboard
 */

/**
 * Mapping from mission integer values to enum names
 * Synchronized with backend src/enums.py Mission class
 */
export const MISSION_INT_TO_NAME = {
  0: 'NONE',
  1: 'DRONE_SHOW_FROM_CSV',
  2: 'SMART_SWARM',
  3: 'CUSTOM_CSV_DRONE_SHOW',
  4: 'SWARM_TRAJECTORY',
  6: 'REBOOT_FC',
  7: 'REBOOT_SYS',
  8: 'TEST_LED',
  10: 'TAKE_OFF',
  100: 'TEST',
  101: 'LAND',
  102: 'HOLD',
  103: 'UPDATE_CODE',
  104: 'RETURN_RTL',
  105: 'KILL_TERMINATE',
  106: 'HOVER_TEST',
  110: 'INIT_SYSID',
  111: 'APPLY_COMMON_PARAMS',
  999: 'UNKNOWN'
};

/**
 * Mapping from mission enum names to user-friendly display names
 */
export const MISSION_DISPLAY_NAMES = {
  'NONE': 'No Mission',
  'DRONE_SHOW_FROM_CSV': 'Drone Show (CSV)',
  'SMART_SWARM': 'Smart Swarm',
  'CUSTOM_CSV_DRONE_SHOW': 'Custom Drone Show',
  'SWARM_TRAJECTORY': 'Swarm Formation',
  'HOVER_TEST': 'Hover Test',
  'TAKE_OFF': 'Takeoff',
  'LAND': 'Landing',
  'HOLD': 'Hold Position',
  'TEST': 'System Test',
  'REBOOT_FC': 'Reboot Flight Controller',
  'REBOOT_SYS': 'System Reboot',
  'TEST_LED': 'LED Test',
  'UPDATE_CODE': 'Code Update',
  'RETURN_RTL': 'Return to Launch',
  'KILL_TERMINATE': 'Emergency Terminate',
  'INIT_SYSID': 'Initialize System ID',
  'APPLY_COMMON_PARAMS': 'Apply Parameters',
  'UNKNOWN': 'Unknown Mission'
};

/**
 * Get a user-friendly mission name
 * @param {string|number} missionValue - The mission enum name (string) or integer value
 * @returns {string} Human-readable mission name
 */
export const getFriendlyMissionName = (missionValue) => {
  if (missionValue === null || missionValue === undefined || missionValue === 'N/A') {
    return 'No Active Mission';
  }

  // Handle integer values (convert to enum name first)
  if (typeof missionValue === 'number') {
    const enumName = MISSION_INT_TO_NAME[missionValue];
    if (!enumName) {
      return `Unknown Mission (${missionValue})`;
    }
    return MISSION_DISPLAY_NAMES[enumName] || enumName;
  }

  // Handle string values (enum names)
  return MISSION_DISPLAY_NAMES[missionValue] || missionValue;
};

/**
 * Get mission status color/class based on mission type
 * @param {string|number} missionValue - The mission enum name (string) or integer value
 * @returns {string} CSS class for styling
 */
export const getMissionStatusClass = (missionValue) => {
  // Convert integer to enum name if needed
  let missionName = missionValue;
  if (typeof missionValue === 'number') {
    missionName = MISSION_INT_TO_NAME[missionValue];
  }

  if (!missionName || missionName === 'NONE' || missionName === 'N/A') {
    return 'mission-none';
  }

  // Formation/choreography missions
  if (['SWARM_TRAJECTORY', 'DRONE_SHOW_FROM_CSV', 'CUSTOM_CSV_DRONE_SHOW', 'SMART_SWARM'].includes(missionName)) {
    return 'mission-performance';
  }

  // Basic flight operations
  if (['TAKE_OFF', 'LAND', 'HOLD', 'RETURN_RTL'].includes(missionName)) {
    return 'mission-flight';
  }

  // Testing operations
  if (['TEST', 'HOVER_TEST', 'TEST_LED'].includes(missionName)) {
    return 'mission-test';
  }

  // System operations
  if (['REBOOT_FC', 'REBOOT_SYS', 'UPDATE_CODE', 'INIT_SYSID', 'APPLY_COMMON_PARAMS'].includes(missionName)) {
    return 'mission-system';
  }

  // Emergency operations
  if (missionName === 'KILL_TERMINATE') {
    return 'mission-emergency';
  }

  return 'mission-default';
};