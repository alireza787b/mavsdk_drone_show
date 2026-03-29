import { ALTITUDE_REFERENCE, TIMING_MODES, YAW_CONSTANTS } from './SpeedCalculator';

export const getTrajectoryAltitudeReferenceLabel = (reference = ALTITUDE_REFERENCE.MSL) =>
  reference === ALTITUDE_REFERENCE.AGL ? 'Target AGL' : 'MSL input';

export const getTrajectoryTimingModeLabel = (mode = TIMING_MODES.MANUAL_TIME) =>
  mode === TIMING_MODES.AUTO_SPEED ? 'Speed-driven ETA' : 'Time-driven speed';

export const getTrajectoryHeadingModeLabel = (mode = YAW_CONSTANTS.AUTO) =>
  mode === YAW_CONSTANTS.AUTO ? 'Auto heading' : 'Manual heading';

export const getTrajectoryMissionAnchorLabel = (waypointIndex = 0) =>
  waypointIndex === 0 ? 'Mission start anchor' : 'Waypoint arrival';
