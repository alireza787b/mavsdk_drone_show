import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../constants/droneConstants';

export const STRICT_SYNC_MISSION_TYPES = new Set([
  DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV,
  DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW,
  DRONE_MISSION_TYPES.SWARM_TRAJECTORY,
]);

export const SCHEDULABLE_ACTION_KEYS = new Set([
  'TAKE_OFF',
  'HOVER_TEST',
  'HOLD',
  'LAND',
  'RETURN_RTL',
  'TEST',
  'TEST_LED',
]);

export const isStrictSyncMissionType = (missionType) => STRICT_SYNC_MISSION_TYPES.has(Number(missionType));

export const isSchedulableActionKey = (actionKey) => SCHEDULABLE_ACTION_KEYS.has(String(actionKey));

export const getMissionScheduleDoctrine = (missionType) => {
  if (!isStrictSyncMissionType(missionType)) {
    return null;
  }

  return {
    label: 'Strict synchronized launch',
    detail:
      'Queue this mission before the safe pre-trigger window closes. If dispatch or startup slips beyond the late-start tolerance, drones abort instead of joining late and pretending the shared timeline stayed synchronized.',
  };
};

export const getMissionExecutionPolicy = (missionType, { isImmediate = false } = {}) => {
  if (!isStrictSyncMissionType(missionType)) {
    return null;
  }

  return isImmediate
    ? 'Synchronized offboard launch. Drones accept immediately, but any aircraft that misses the coordinated startup tolerance aborts instead of joining late.'
    : 'Synchronized offboard launch. Drones queue for the shared trigger; if dispatch or startup slips beyond the safe window, they abort instead of joining late.';
};

export const getActionExecutionPolicy = ({ actionKey, isImmediate = true }) => {
  switch (String(actionKey)) {
    case 'TAKE_OFF':
    case 'HOVER_TEST':
      return isImmediate
        ? 'Launch begins on acceptance and retries PX4 armability briefly before failing.'
        : 'Launch waits for the trigger, then retries PX4 armability briefly before failing.';
    case 'LAND':
    case 'RETURN_RTL':
    case 'HOLD':
    case 'TEST':
    case 'TEST_LED':
      return isImmediate
        ? 'Executes immediately on acceptance.'
        : 'Waits for the trigger, then executes immediately on acceptance.';
    default:
      return 'Immediate only. This action is not queued behind a future trigger.';
  }
};

export const isLaunchStyleCommand = (missionType) => {
  const normalized = Number(missionType);
  return normalized === DRONE_ACTION_TYPES.TAKE_OFF || isStrictSyncMissionType(normalized);
};
