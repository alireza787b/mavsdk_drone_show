/**
 * Mission Utilities
 * Provides human-readable mission names for the drone dashboard
 */

import { getCommandMetadata } from '../constants/missionCatalog';

const EMPTY_MISSION_NAMES = new Set(['NONE', 'N/A', '']);

const normalizeMissionName = (missionValue) => {
  if (missionValue === null || missionValue === undefined) {
    return null;
  }

  const metadata = getCommandMetadata(missionValue);
  if (metadata) {
    return metadata.key;
  }

  return typeof missionValue === 'string' ? missionValue.trim() || null : null;
};

export const isMissionEmpty = (missionValue) => {
  const missionName = normalizeMissionName(missionValue);
  return !missionName || EMPTY_MISSION_NAMES.has(missionName);
};

/**
 * Get a user-friendly mission name
 * @param {string|number} missionValue - The mission enum name (string) or integer value
 * @returns {string} Human-readable mission name
 */
export const getFriendlyMissionName = (missionValue) => {
  if (isMissionEmpty(missionValue)) {
    return getCommandMetadata('NONE').statusLabel;
  }

  const metadata = getCommandMetadata(missionValue);
  if (metadata) {
    return metadata.statusLabel;
  }

  if (typeof missionValue === 'number' || /^\d+$/.test(String(missionValue).trim())) {
    return `Unknown Mission (${missionValue})`;
  }

  return missionValue;
};

/**
 * Get mission status color/class based on mission type
 * @param {string|number} missionValue - The mission enum name (string) or integer value
 * @returns {string} CSS class for styling
 */
export const getMissionStatusClass = (missionValue) => {
  if (isMissionEmpty(missionValue)) {
    return 'mission-none';
  }

  return getCommandMetadata(missionValue)?.statusClass || 'mission-default';
};

export const getMissionDisplayContext = (currentMissionValue, lastMissionValue) => {
  const currentMissionName = getFriendlyMissionName(currentMissionValue);
  const lastMissionName = getFriendlyMissionName(lastMissionValue);
  const hasCurrentMission = !isMissionEmpty(currentMissionValue);
  const hasLastMission = !isMissionEmpty(lastMissionValue);
  const currentMissionStatusClass = getMissionStatusClass(currentMissionValue);

  let badgeTooltip = `Current mission: ${currentMissionName}.`;
  if (!hasCurrentMission && hasLastMission) {
    badgeTooltip = `No active mission. Last mission: ${lastMissionName}.`;
  } else if (hasCurrentMission && hasLastMission && currentMissionName !== lastMissionName) {
    badgeTooltip = `Current mission: ${currentMissionName}. Last mission: ${lastMissionName}.`;
  }

  return {
    currentMissionName,
    currentMissionStatusClass,
    lastMissionName,
    hasCurrentMission,
    hasLastMission,
    badgeTooltip,
  };
};
