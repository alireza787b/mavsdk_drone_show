export const DRONE_MISSION_TYPES = {
  NONE: 0,
  DRONE_SHOW_FROM_CSV: 1,
  SMART_SWARM: 2,
  CUSTOM_CSV_DRONE_SHOW: 5,  // New Custom CSV Drone Show mission type
};

export const DRONE_ACTION_TYPES = {
  TAKE_OFF: 10,
  LAND: 101,
  HOLD: 102,
  TEST: 100,
  REBOOT: 7,  // Added reboot command
};

export const defaultTriggerTimeDelay = 10;
