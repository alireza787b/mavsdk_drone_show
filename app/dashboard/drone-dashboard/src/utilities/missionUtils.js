/**
 * Mission Utilities
 * Provides human-readable mission names for the drone dashboard
 */

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
 * @param {string} missionName - The mission enum name from backend
 * @returns {string} Human-readable mission name
 */
export const getFriendlyMissionName = (missionName) => {
  if (!missionName || missionName === 'N/A') {
    return 'No Active Mission';
  }

  return MISSION_DISPLAY_NAMES[missionName] || missionName;
};

/**
 * Get mission status color/class based on mission type
 * @param {string} missionName - The mission enum name
 * @returns {string} CSS class for styling
 */
export const getMissionStatusClass = (missionName) => {
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