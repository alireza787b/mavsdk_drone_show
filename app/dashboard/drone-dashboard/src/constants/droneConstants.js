import { getCustomShowImageURL, getBackendURL } from '../utilities/utilities'; // Import utility functions

export const DRONE_MISSION_TYPES = {
  NONE: 0,
  DRONE_SHOW_FROM_CSV: 1,
  SMART_SWARM: 2,
  CUSTOM_CSV_DRONE_SHOW: 3,
};

export const DRONE_MISSION_IMAGES = {
  [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: `${getBackendURL()}/get-show-plots/all_drones.png`,
  [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: `${getCustomShowImageURL()}`,  // Use the function to get the custom show image URL
};

export const getMissionDescription = (missionType) => {
  switch (missionType) {
    case DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV:
      return 'Executes a fully synchronized drone show using pre-processed Skybrush CSV data. This mission coordinates multiple drones autonomously, leveraging MAVSDK to maintain precision in complex aerial maneuvers.';
    case DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW:
      return 'Initiates a custom drone show sequence from a user-defined CSV file. This mission allows for flexibility in the drone choreography, utilizing MAVSDK for offboard control to follow intricate trajectories specified in the CSV.';
    case DRONE_MISSION_TYPES.SMART_SWARM:
      return 'Implements a smart swarm formation with leader-follower dynamics. This mission is designed for scenarios requiring coordinated movements across multiple drones, where MAVSDK ensures seamless communication and control within the swarm (currently in development).';
    case DRONE_MISSION_TYPES.NONE:
      return 'Immediately cancels any active mission, bringing all drones back to their default state.';
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
