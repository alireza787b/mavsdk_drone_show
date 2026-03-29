import { ALTITUDE_REFERENCE, TIMING_MODES, YAW_CONSTANTS } from './SpeedCalculator';

export const getTrajectoryAltitudeReferenceLabel = (reference = ALTITUDE_REFERENCE.MSL) =>
  reference === ALTITUDE_REFERENCE.AGL ? 'Target AGL' : 'MSL input';

export const getTrajectoryAltitudeReferenceDescription = (reference = ALTITUDE_REFERENCE.MSL) =>
  reference === ALTITUDE_REFERENCE.AGL
    ? 'Operator enters target clearance above ground. The planner converts it into the canonical stored MSL altitude using terrain data.'
    : 'Operator enters the canonical mission altitude directly in MSL. This stored MSL altitude is what the mission executes.';

export const getTrajectoryTimingModeLabel = (mode = TIMING_MODES.MANUAL_TIME) =>
  mode === TIMING_MODES.AUTO_SPEED ? 'Speed-driven ETA' : 'Time-driven speed';

export const getTrajectoryTimingModeDescription = (
  mode = TIMING_MODES.MANUAL_TIME,
  { isMissionAnchor = false } = {}
) => {
  if (isMissionAnchor) {
    return 'The first waypoint defines when the leader should reach the route after mission start.';
  }

  return mode === TIMING_MODES.AUTO_SPEED
    ? 'Operator sets the preferred arrival speed. The planner derives the inbound-leg arrival time.'
    : 'Operator pins the arrival time. The planner derives the required inbound-leg speed.';
};

export const getTrajectoryHeadingModeLabel = (mode = YAW_CONSTANTS.AUTO) =>
  mode === YAW_CONSTANTS.AUTO ? 'Auto heading' : 'Manual heading';

export const getTrajectoryHeadingModeDescription = (
  mode = YAW_CONSTANTS.AUTO,
  { isMissionAnchor = false } = {}
) => {
  if (mode === YAW_CONSTANTS.AUTO) {
    return 'Heading aligns with the inbound arrival leg from the previous waypoint.';
  }

  return isMissionAnchor
    ? 'Operator sets the initial route-entry heading explicitly at mission start.'
    : 'Operator locks a specific arrival heading at this waypoint.';
};

export const getTrajectoryMissionAnchorLabel = (waypointIndex = 0) =>
  waypointIndex === 0 ? 'Mission start anchor' : 'Waypoint arrival';

export const getTrajectoryMissionAnchorDescription = (waypointIndex = 0) =>
  waypointIndex === 0
    ? 'This first waypoint anchors when the leader should reach the route after mission start.'
    : 'This waypoint is evaluated by the arrival leg that reaches it from the previous waypoint.';
