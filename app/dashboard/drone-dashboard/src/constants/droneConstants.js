export const DRONE_MISSION_TYPES = {
  NONE: 0,
  DRONE_SHOW_FROM_CSV: 1,
  SMART_SWARM: 2,
  CUSTOM_CSV_DRONE_SHOW: 5,  // New Custom CSV Drone Show mission type
};

export const getMissionDescription = (missionType) => {
  console.log("Mission Type:", missionType); // Log the mission type to ensure it's correct
  switch (missionType) {
    case DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV:
      return 'Smartly runs the Skybrush exported and processed drone show, synchronized with other drones.';
    case DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW:
      return 'Runs the shapes/active.csv that can be either created by the CSV creator script or custom methods.';
    case DRONE_MISSION_TYPES.SMART_SWARM:
      return 'Can plan clustered leader-follower missions (under development).';
    case DRONE_MISSION_TYPES.NONE:
      return 'Cancel any currently active mission.';
    default:
      return '';
  }
};

export const DRONE_ACTION_TYPES = {
  TAKE_OFF: 10,
  LAND: 101,
  HOLD: 102,
  TEST: 100,
  REBOOT: 7,  // Added reboot command
};

export const defaultTriggerTimeDelay = 10;
