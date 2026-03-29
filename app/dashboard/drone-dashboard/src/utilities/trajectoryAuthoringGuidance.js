import { ALTITUDE_REFERENCE, TIMING_MODES, YAW_CONSTANTS, formatHeading } from './SpeedCalculator';

const formatSeconds = (seconds = 0) => {
  if (!Number.isFinite(seconds)) {
    return '0s';
  }

  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds % 60);
    return `${minutes}m ${remainder}s`;
  }

  return `${Math.round(seconds)}s`;
};

const formatSpeed = (speed = 0) => `${Number(speed || 0).toFixed(1)} m/s`;

const formatAltitude = (altitude = 0) => `${Number(altitude || 0).toFixed(1)}m MSL`;

const formatAgl = (agl = 0) => `${Math.max(0, Number(agl || 0)).toFixed(1)}m AGL`;

export const getTrajectoryAltitudeReferenceLabel = (reference = ALTITUDE_REFERENCE.MSL) =>
  reference === ALTITUDE_REFERENCE.AGL ? 'Target AGL' : 'MSL input';

export const getTrajectoryAltitudeReferenceDescription = (reference = ALTITUDE_REFERENCE.MSL) =>
  reference === ALTITUDE_REFERENCE.AGL
    ? 'Operator enters target clearance above ground. The planner converts it into the canonical stored MSL altitude using terrain data.'
    : 'Operator enters the canonical mission altitude directly in MSL. This stored MSL altitude is what the mission executes.';

export const getTrajectoryTimeFieldLabel = ({ isMissionAnchor = false } = {}) =>
  isMissionAnchor ? 'Route entry time' : 'Waypoint arrival time';

export const getTrajectoryTimingModeLabel = (mode = TIMING_MODES.MANUAL_TIME) =>
  mode === TIMING_MODES.AUTO_SPEED ? 'Speed-driven ETA' : 'Time-driven speed';

export const getTrajectoryTimingModeDescription = (
  mode = TIMING_MODES.MANUAL_TIME,
  { isMissionAnchor = false } = {}
) => {
  if (isMissionAnchor) {
    return 'The first waypoint defines when the leader should enter the route after mission start.';
  }

  return mode === TIMING_MODES.AUTO_SPEED
    ? 'Operator sets the preferred inbound-leg speed. The planner derives the waypoint arrival time.'
    : 'Operator pins the waypoint arrival time. The planner derives the required inbound-leg speed.';
};

export const getTrajectoryPreferredSpeedLabel = () => 'Preferred leg speed';

export const getTrajectoryRequiredSpeedLabel = () => 'Required leg speed';

export const getTrajectoryHeadingModeLabel = (mode = YAW_CONSTANTS.AUTO) =>
  mode === YAW_CONSTANTS.AUTO ? 'Auto heading' : 'Manual heading';

export const getTrajectoryHeadingFieldLabel = ({ isMissionAnchor = false } = {}) =>
  isMissionAnchor ? 'Entry heading' : 'Arrival heading';

export const getTrajectoryHeadingModeDescription = (
  mode = YAW_CONSTANTS.AUTO,
  { isMissionAnchor = false } = {}
) => {
  if (mode === YAW_CONSTANTS.AUTO) {
    return 'Heading aligns with the inbound arrival leg from the previous waypoint.';
  }

  return isMissionAnchor
    ? 'Operator sets the initial route-entry heading explicitly at mission start.'
    : 'Operator locks the heading the leader should hold on arrival at this waypoint.';
};

export const getTrajectoryMissionAnchorLabel = (waypointIndex = 0) =>
  waypointIndex === 0 ? 'Mission start anchor' : 'Waypoint arrival';

export const getTrajectoryMissionAnchorDescription = (waypointIndex = 0) =>
  waypointIndex === 0
    ? 'This first waypoint anchors when the leader should enter the route after mission start.'
    : 'This waypoint is evaluated by the arrival leg that reaches it from the previous waypoint.';

export const getTrajectoryAltitudeIntentSummary = ({
  altitudeReference = ALTITUDE_REFERENCE.MSL,
  altitude = 0,
  targetAgl = 0,
  groundElevation = 0,
  terrainAccurate = true,
} = {}) => {
  const terrainLabel = terrainAccurate === false ? 'estimated terrain' : 'terrain';
  const clearance = Math.max(0, Number(targetAgl || 0));

  if (altitudeReference === ALTITUDE_REFERENCE.AGL) {
    return {
      label: 'Altitude Logic',
      control: `Operator sets ${formatAgl(clearance)} target clearance.`,
      derived: `Planner stores ${formatAltitude(altitude)} using ${terrainLabel} at ${formatAltitude(groundElevation)}.`,
      compact: `${formatAgl(clearance)} → ${formatAltitude(altitude)}`,
    };
  }

  return {
    label: 'Altitude Logic',
    control: `Operator sets canonical mission altitude ${formatAltitude(altitude)}.`,
    derived: `Planner reports current waypoint clearance as ${formatAgl(clearance)} against ${terrainLabel}.`,
    compact: `${formatAltitude(altitude)} → ${formatAgl(clearance)}`,
  };
};

export const getTrajectoryTimingIntentSummary = ({
  isMissionAnchor = false,
  timingMode = TIMING_MODES.MANUAL_TIME,
  timeFromStart = 0,
  preferredSpeed = 0,
  requiredSpeed = 0,
} = {}) => {
  if (isMissionAnchor) {
    return {
      label: 'Route Entry Logic',
      control: `Operator sets route entry at ${formatSeconds(timeFromStart)} after mission start.`,
      derived: 'Planner derives the first inbound leg once the next waypoint exists.',
      compact: `Entry ${formatSeconds(timeFromStart)}`,
    };
  }

  if (timingMode === TIMING_MODES.AUTO_SPEED) {
    return {
      label: 'Timing Logic',
      control: `Operator sets preferred inbound-leg speed ${formatSpeed(preferredSpeed)}.`,
      derived: `Planner derives arrival at ${formatSeconds(timeFromStart)} and verifies the leg at ${formatSpeed(requiredSpeed)}.`,
      compact: `${formatSpeed(preferredSpeed)} → ${formatSeconds(timeFromStart)}`,
    };
  }

  return {
    label: 'Timing Logic',
    control: `Operator pins arrival at ${formatSeconds(timeFromStart)}.`,
    derived: `Planner derives required inbound-leg speed ${formatSpeed(requiredSpeed)}.`,
    compact: `${formatSeconds(timeFromStart)} → ${formatSpeed(requiredSpeed)}`,
  };
};

export const getTrajectoryHeadingIntentSummary = ({
  isMissionAnchor = false,
  headingMode = YAW_CONSTANTS.AUTO,
  heading = 0,
  calculatedHeading = 0,
} = {}) => {
  if (isMissionAnchor || headingMode === YAW_CONSTANTS.MANUAL) {
    return {
      label: 'Heading Logic',
      control: `Operator locks heading ${formatHeading(heading)}.`,
      derived: isMissionAnchor
        ? 'This heading defines the initial route-entry posture.'
        : 'Planner keeps the operator heading on arrival.',
      compact: `Manual ${formatHeading(heading)}`,
    };
  }

  return {
    label: 'Heading Logic',
    control: 'Planner aligns heading with the inbound arrival leg.',
    derived: `Current derived arrival heading: ${formatHeading(calculatedHeading)}.`,
    compact: `Auto ${formatHeading(calculatedHeading)}`,
  };
};

export const getTrajectoryWorkflowStages = ({
  leaderId = null,
  followerCount = 0,
  expectedDroneCount = null,
} = {}) => {
  const totalExpectedDrones = Number.isFinite(expectedDroneCount)
    ? expectedDroneCount
    : followerCount > 0
      ? followerCount + 1
      : null;

  return [
    {
      key: 'author',
      label: 'Author top-leader path',
      detail: 'This workspace only authors top-leader routes. Follower paths are generated later from the current Swarm Design hierarchy and offsets.',
    },
    {
      key: 'intent',
      label: 'Define route entry and leg intent',
      detail: 'Waypoint 1 anchors route-entry time and heading. Later waypoints use either Speed-driven ETA or Time-driven speed.',
    },
    {
      key: 'assign',
      label: leaderId ? `Assign Leader ${leaderId}` : 'Assign selected leader',
      detail: leaderId
        ? `Uploading replaces only Leader ${leaderId}'s authored CSV${totalExpectedDrones ? ` and prepares ${totalExpectedDrones} drone output${totalExpectedDrones === 1 ? '' : 's'} for the next processing pass.` : '.'}`
        : 'Uploading replaces one leader CSV only. It does not regenerate follower outputs yet.',
    },
    {
      key: 'process',
      label: 'Process, review, then launch',
      detail: 'Open Swarm Trajectory to regenerate follower outputs and review plots, then launch Mission 4 from Dashboard once preflight is clear.',
    },
  ];
};
