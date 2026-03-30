const toFiniteNumber = (value, fallback = 0) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

export const formatTrajectoryDuration = (seconds = 0) => {
  const normalizedSeconds = Math.max(0, toFiniteNumber(seconds, 0));

  if (normalizedSeconds >= 60) {
    const minutes = Math.floor(normalizedSeconds / 60);
    const remainder = Math.round(normalizedSeconds % 60);
    return `${minutes}m ${remainder}s`;
  }

  return `${normalizedSeconds.toFixed(0)}s`;
};

export const getTrajectoryMissionClockSeconds = (stats = {}) =>
  Math.max(0, toFiniteNumber(stats.totalTime, 0));

export const getTrajectoryRouteEntryDelaySeconds = (stats = {}) =>
  Math.max(0, toFiniteNumber(stats.routeEntryDelaySeconds, 0));

export const getTrajectoryRouteMotionSeconds = (stats = {}) => {
  if (Number.isFinite(Number(stats.routeMotionTime))) {
    return Math.max(0, Number(stats.routeMotionTime));
  }

  return Math.max(
    0,
    getTrajectoryMissionClockSeconds(stats) - getTrajectoryRouteEntryDelaySeconds(stats),
  );
};

export const getWaypointMissionClockSeconds = (waypoints = []) =>
  Math.max(0, toFiniteNumber(waypoints[waypoints.length - 1]?.timeFromStart, 0));

export const getWaypointRouteEntryDelaySeconds = (waypoints = []) =>
  Math.max(0, toFiniteNumber(waypoints[0]?.timeFromStart, 0));

export const getWaypointRouteMotionSeconds = (waypoints = []) =>
  Math.max(
    0,
    getWaypointMissionClockSeconds(waypoints) - getWaypointRouteEntryDelaySeconds(waypoints),
  );
