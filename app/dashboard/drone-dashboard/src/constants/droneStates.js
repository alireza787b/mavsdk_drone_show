/**
 * Drone Show Application States
 * 
 * These are custom application states for the drone show system,
 * completely separate from PX4's flight modes and arming status.
 * 
 * These states represent the mission execution workflow:
 * IDLE -> MISSION_READY -> MISSION_EXECUTING -> IDLE
 */

export const DRONE_SHOW_STATES = {
  0: 'Idle',                    // No mission loaded
  1: 'Mission Ready',           // Mission loaded, waiting for trigger time
  2: 'Mission Executing',       // Mission is currently executing
  999: 'Unknown'                // Unknown/error state
};

/**
 * Get human-readable drone show state name
 * @param {number} state - Drone show state value
 * @returns {string} Human-readable state name
 */
export const getDroneShowStateName = (state) => {
  // Convert state to number if it's a string (backward compatibility)
  const numState = typeof state === 'string' ? parseInt(state, 10) : state;
  
  // Debug logging for unmapped states
  if (!(numState in DRONE_SHOW_STATES)) {
    console.warn(`Unknown drone show state: ${state} (${typeof state}). Adding to mapping.`);
  }
  
  return DRONE_SHOW_STATES[numState] || `Unknown (${state})`;
};

/**
 * Check if drone is ready for mission commands
 * @param {number} state - Drone show state value
 * @returns {boolean} True if ready for mission commands
 */
export const isReadyForMission = (state) => {
  return state === 0; // IDLE state
};

/**
 * Check if drone has mission loaded and waiting
 * @param {number} state - Drone show state value
 * @returns {boolean} True if mission is loaded and waiting for trigger
 */
export const isMissionReady = (state) => {
  return state === 1; // MISSION_READY state
};

/**
 * Check if drone is executing a mission
 * @param {number} state - Drone show state value
 * @returns {boolean} True if mission is executing
 */
export const isMissionExecuting = (state) => {
  return state === 2; // MISSION_EXECUTING state
};