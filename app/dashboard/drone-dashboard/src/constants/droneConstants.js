// src/constants/droneConstants.js
import { getCustomShowImageURL, getBackendURL } from '../utilities/utilities'; // Import utility functions

export const DRONE_MISSION_TYPES = {
    NONE: 0,
    DRONE_SHOW_FROM_CSV: 1,
    SMART_SWARM: 2,
    CUSTOM_CSV_DRONE_SHOW: 3,
    SWARM_TRAJECTORY: 4,
};

// Define mission display order for better UX (Cancel last as requested)
export const DRONE_MISSION_DISPLAY_ORDER = [
    { key: 'DRONE_SHOW_FROM_CSV', value: DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV },
    { key: 'CUSTOM_CSV_DRONE_SHOW', value: DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW },
    { key: 'SMART_SWARM', value: DRONE_MISSION_TYPES.SMART_SWARM },
    { key: 'SWARM_TRAJECTORY', value: DRONE_MISSION_TYPES.SWARM_TRAJECTORY },
    { key: 'NONE', value: DRONE_MISSION_TYPES.NONE }, // Cancel last for safety
];

export const DRONE_ACTION_TYPES = {
    TAKE_OFF: 10,
    LAND: 101,
    HOLD: 102,
    TEST: 100,
    UPDATE_CODE: 103,
    RETURN_RTL: 104,
    KILL_TERMINATE: 105,
    HOVER_TEST: 106,
    REBOOT_FC: 6,
    REBOOT_SYS: 7,
    TEST_LED: 8,
    DISARM: 9,
    INIT_SYSID: 110,
    APPLY_COMMON_PARAMS: 111,
};

export const DRONE_MISSION_IMAGES = {
    [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: `${getBackendURL()}/get-show-plots/combined_drone_paths.jpg`,
    [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: `${getCustomShowImageURL()}`, // Use the function to get the custom show image URL
};

export const DRONE_MISSION_NAMES = {
    0: 'Cancel Mission',
    1: 'Drone Show from CSV',
    2: 'Smart Swarm',
    3: 'Custom CSV Drone Show',
    4: 'Swarm Trajectory',
};

export const DRONE_ACTION_NAMES = {
    6: 'Reboot Flight Controls',
    7: 'Reboot Companion Computer',
    8: 'Test Light Show',
    9: 'Disarm Drones',
    10: 'Take Off',
    100: 'Test',
    101: 'Land',
    102: 'Hold',
    103: 'Update Code',
    104: 'Return to Launch',
    105: 'Emergency Kill',
    106: 'Hover Test',
    110: 'Init System ID',
    111: 'Apply Common Params',
};

export const getMissionDescription = (missionType) => {
    switch (missionType) {
        case DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV:
            return 'Launch the processed SkyBrush show package with synchronized timing and optional global launch correction.';
        case DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW:
            return 'Replay the active custom protocol CSV relative to each drone launch point.';
        case DRONE_MISSION_TYPES.SMART_SWARM:
            return 'Start the published leader-follower topology for live formation flight and in-flight reassignment.';
        case DRONE_MISSION_TYPES.SWARM_TRAJECTORY:
            return 'Dispatch the processed leader-route package with synchronized timing across the selected cluster.';
        case DRONE_MISSION_TYPES.NONE:
            return 'Cancel the active mission for the current target scope immediately.';
        default:
            return '';
    }
};

export const getCommandName = (missionType) => {
    return (
        DRONE_MISSION_NAMES[missionType] ||
        DRONE_ACTION_NAMES[missionType] ||
        'Unknown Command'
    );
};

export const defaultTriggerTimeDelay = 10;
