// src/utilities/SpeedCalculator.js

import {
  TRAJECTORY_ALTITUDE_POLICY,
  TRAJECTORY_SPEED_POLICY,
  TRAJECTORY_TIMING_POLICY,
  TRAJECTORY_TERRAIN_POLICY,
  clampPreferredLegSpeed,
  getNominalPreferredLegSpeed,
} from '../constants/trajectoryMissionPolicy';

/**
 * Drone speed thresholds (m/s)
 * Backed by the shared trajectory mission policy so the planner UI, validation,
 * and operator messaging all use the same envelope.
 */
export const SPEED_THRESHOLDS = {
  MIN_SPEED: TRAJECTORY_SPEED_POLICY.MIN_PREFERRED,
  OPTIMAL_MAX: TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX,
  MARGINAL_MAX: TRAJECTORY_SPEED_POLICY.MARGINAL_MAX,
  ABSOLUTE_MAX: TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX,
};

/**
 * AVIATION STANDARD HEADING CONSTANTS
 * 
 * Following professional aviation standards:
 * - 000° = North, 090° = East, 180° = South, 270° = West
 * - Single source of truth: HeadingMode determines behavior
 * - Clean data structure without redundant flags
 */
export const YAW_CONSTANTS = {
  AUTO: 'auto',           // Automatic: align with the arrival leg into this waypoint
  MANUAL: 'manual',       // Manual: user-specified fixed heading
  DEFAULT_HEADING: 0      // Default heading: 000° (North)
};

export const TIMING_MODES = {
  AUTO_SPEED: 'auto_speed',
  MANUAL_TIME: 'manual_time',
};

export const ALTITUDE_REFERENCE = {
  MSL: 'msl',
  AGL: 'agl',
};

const EARTH_RADIUS_M = 6_371_000;

const toRadians = (degrees) => (degrees * Math.PI) / 180;
const toDegrees = (radians) => (radians * 180) / Math.PI;

const calculateHorizontalDistanceMeters = (fromWaypoint, toWaypoint) => {
  const lat1 = toRadians(fromWaypoint.latitude);
  const lat2 = toRadians(toWaypoint.latitude);
  const dLat = lat2 - lat1;
  const dLon = toRadians(toWaypoint.longitude - fromWaypoint.longitude);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

  return EARTH_RADIUS_M * c;
};

const calculateInitialBearing = (fromPoint, toPoint) => {
  const lat1 = toRadians(fromPoint.latitude);
  const lat2 = toRadians(toPoint.latitude);
  const dLon = toRadians(toPoint.longitude - fromPoint.longitude);

  const y = Math.sin(dLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);

  return toDegrees(Math.atan2(y, x));
};

const calculateSegmentDistance3D = (fromWaypoint, toWaypoint) => {
  const horizontalDistance = calculateHorizontalDistanceMeters(fromWaypoint, toWaypoint);
  const altitudeDifference = Math.abs(
    (toWaypoint.altitude ?? 0) - (fromWaypoint.altitude ?? 0)
  );

  return Math.sqrt(
    Math.pow(horizontalDistance, 2) + Math.pow(altitudeDifference, 2)
  );
};

/**
 * Calculate heading (yaw) from one point to another
 * Aviation standard: 0° = North, 90° = East, 180° = South, 270° = West
 * @param {Object} fromPoint - Starting point with lat, lon
 * @param {Object} toPoint - Destination point with lat, lon
 * @returns {number} Heading in degrees (0-360, aviation standard)
 */
export const calculateHeading = (fromPoint, toPoint) => {
  try {
    // Convert signed initial bearing to 0-360 aviation standard.
    let heading = calculateInitialBearing(fromPoint, toPoint);
    if (heading < 0) {
      heading += 360;
    }
    
    return Math.round(heading * 10) / 10; // Round to 1 decimal place
  } catch {
    return YAW_CONSTANTS.DEFAULT_HEADING;
  }
};

/**
 * Normalize heading to aviation standard (0-360 range)
 * @param {number} heading - Heading angle in degrees
 * @returns {number} Normalized heading (0-360, aviation standard)
 */
export const normalizeHeading = (heading) => {
  let normalized = heading % 360;
  if (normalized < 0) {
    normalized += 360;
  }
  return Math.round(normalized * 10) / 10;
};

/**
 * Format heading for aviation display (3-digit format: 000°, 090°, 180°, etc.)
 * @param {number} heading - Heading in degrees (0-360)
 * @returns {string} Formatted heading (e.g., "000°", "090°", "270°")
 */
export const formatHeading = (heading) => {
  const normalized = normalizeHeading(heading);
  return normalized.toFixed(0).padStart(3, '0') + '°';
};

/**
 * Calculate required speed between two waypoints
 * @param {Object} fromWaypoint - Starting waypoint with lat, lon, timeFromStart
 * @param {Object} toWaypoint - Destination waypoint with lat, lon, timeFromStart
 * @param {Object} currentPosition - Current clicked position (optional, for preview)
 * @returns {number} Required speed in m/s
 */
export const calculateSpeed = (fromWaypoint, toWaypoint, currentPosition = null) => {
  try {
    // Use current position if provided, otherwise use toWaypoint position
    const targetPosition = currentPosition || toWaypoint;
    
    const totalDistance = calculateSegmentDistance3D(fromWaypoint, {
      ...targetPosition,
      altitude: toWaypoint.altitude,
    });
    
    // Calculate time difference
    const timeDifference = toWaypoint.timeFromStart - (fromWaypoint.timeFromStart || 0);
    
    if (timeDifference <= 0) {
      return 0;
    }
    
    // Calculate required speed
    const requiredSpeed = totalDistance / timeDifference;
    
    return Math.round(requiredSpeed * 10) / 10; // Round to 1 decimal place
  } catch {
    return 0;
  }
};

/**
 * Validate if a speed is feasible for drone operations
 * @param {number} speed - Speed in m/s
 * @returns {string} Status: 'feasible', 'marginal', 'impossible', or 'unknown'
 */
export const validateSpeed = (speed) => {
  if (speed < SPEED_THRESHOLDS.MIN_SPEED) {
    return 'unknown';
  }
  
  if (speed <= SPEED_THRESHOLDS.OPTIMAL_MAX) {
    return 'feasible';
  }
  
  if (speed <= SPEED_THRESHOLDS.MARGINAL_MAX) {
    return 'marginal';
  }
  
  return 'impossible';
};

/**
 * Get speed status with descriptive information
 * @param {number} speed - Speed in m/s
 * @returns {string} Speed status
 */
export const getSpeedStatus = (speed) => {
  return validateSpeed(speed);
};

/**
 * Get human-readable speed description
 * @param {number} speed - Speed in m/s
 * @returns {string} Human-readable description
 */
export const getSpeedDescription = (speed) => {
  const status = validateSpeed(speed);
  
  switch (status) {
    case 'feasible':
      return `Normal operating speed (${speed} m/s)`;
    case 'marginal':
      return `High speed operation (${speed} m/s) - Use caution`;
    case 'impossible':
      return `Extreme speed (${speed} m/s) - Not safe for operation`;
    default:
      return `Speed: ${speed} m/s`;
  }
};

export const TRAJECTORY_SEGMENT_COLORS = Object.freeze({
  feasible: '#00d4ff',
  marginal: '#f5a623',
  impossible: '#dc3545',
  unknown: '#8ea4bf',
});

export const getTrajectorySegmentColor = (speedStatus = 'unknown') =>
  TRAJECTORY_SEGMENT_COLORS[speedStatus] ?? TRAJECTORY_SEGMENT_COLORS.unknown;

export const buildTrajectorySegments = (waypoints = []) => {
  if (!Array.isArray(waypoints) || waypoints.length < 2) {
    return [];
  }

  return waypoints.slice(1).map((waypoint, index) => {
    const previousWaypoint = waypoints[index];
    const speed = waypoint.estimatedSpeed || calculateSpeed(previousWaypoint, waypoint);
    const speedStatus = waypoint.speedStatus || validateSpeed(speed);
    const distanceMeters = calculateSegmentDistance3D(previousWaypoint, waypoint);
    const durationSeconds = Math.max(
      0,
      (waypoint.timeFromStart || 0) - (previousWaypoint.timeFromStart || 0)
    );

    return {
      id: `${previousWaypoint.id}->${waypoint.id}`,
      fromWaypointId: previousWaypoint.id,
      toWaypointId: waypoint.id,
      fromWaypointName: previousWaypoint.name || `Waypoint ${index + 1}`,
      toWaypointName: waypoint.name || `Waypoint ${index + 2}`,
      fromIndex: index + 1,
      toIndex: index + 2,
      speed,
      speedStatus,
      color: getTrajectorySegmentColor(speedStatus),
      distanceMeters,
      durationSeconds,
      arrivalTimeFromStart: waypoint.timeFromStart || 0,
      timingMode: waypoint.timingMode || TIMING_MODES.MANUAL_TIME,
      preferredSpeed: waypoint.preferredSpeed || 0,
      headingMode: waypoint.headingMode || YAW_CONSTANTS.AUTO,
      heading: waypoint.heading || 0,
      calculatedHeading: waypoint.calculatedHeading || 0,
      fromAltitude: previousWaypoint.altitude || 0,
      toAltitude: waypoint.altitude || 0,
      toAltitudeReference: waypoint.altitudeReference || ALTITUDE_REFERENCE.MSL,
      toTargetAgl: waypoint.targetAgl || 0,
      toGroundElevation: waypoint.groundElevation || 0,
      terrainAccurate: waypoint.terrainAccurate !== false,
      coordinates: [
        [previousWaypoint.longitude, previousWaypoint.latitude],
        [waypoint.longitude, waypoint.latitude],
      ],
    };
  });
};

export const buildTrajectoryAttentionItems = (stats = {}) => {
  const items = [];
  const terrainCoverage = stats.terrainCoverage || {};
  const altitudeModes = stats.altitudeReferenceCounts || {};
  const speedStatusCounts = stats.speedStatusCounts || {};

  if ((speedStatusCounts.impossible || 0) > 0) {
    items.push({
      tone: 'danger',
      text: `${speedStatusCounts.impossible} leg${speedStatusCounts.impossible === 1 ? '' : 's'} exceed the safe speed envelope.`,
    });
  } else if ((stats.speedWarnings || 0) > 0) {
    items.push({
      tone: 'warning',
      text: `${stats.speedWarnings} leg${stats.speedWarnings === 1 ? ' requires' : 's require'} elevated speed review.`,
    });
  }

  const terrainAttentionCount = (terrainCoverage.estimated || 0) + (terrainCoverage.unknown || 0);
  if (terrainAttentionCount > 0) {
    items.push({
      tone: 'warning',
      text: `${terrainAttentionCount} waypoint${terrainAttentionCount === 1 ? '' : 's'} use estimated or missing terrain data.`,
    });
  }

  if ((altitudeModes.agl || 0) > 0) {
    items.push({
      tone: 'info',
      text: 'AGL entries are stored as MSL after applying the current ground estimate.',
    });
    items.push({
      tone: 'info',
      text: 'Terrain assist is waypoint-based only. Long terrain-changing legs still need denser waypoints or later terrain-follow review.',
    });
  }

  if (
    Number.isFinite(stats.minAgl)
    && stats.minAgl > 0
    && stats.minAgl < TRAJECTORY_TERRAIN_POLICY.MIN_SAFE_CLEARANCE_M
  ) {
    items.push({
      tone: 'warning',
      text: `Waypoint clearance dips below ${TRAJECTORY_TERRAIN_POLICY.MIN_SAFE_CLEARANCE_M}m AGL. Verify terrain intent and separation before launch.`,
    });
  }

  return items;
};

const getStoredHeadingMode = (waypoint, index) =>
  waypoint.headingMode || waypoint.yawMode || (index === 0 ? YAW_CONSTANTS.MANUAL : YAW_CONSTANTS.AUTO);

const getStoredHeadingValue = (waypoint, fallback = YAW_CONSTANTS.DEFAULT_HEADING) => {
  if (waypoint.heading !== undefined) {
    return normalizeHeading(waypoint.heading);
  }

  if (waypoint.yaw !== undefined) {
    return normalizeHeading(waypoint.yaw);
  }

  return normalizeHeading(fallback);
};

const getStoredTimeFromStart = (waypoint = {}) => {
  const directTime = waypoint.timeFromStart ?? waypoint.time ?? 0;
  return Number.isFinite(Number(directTime)) ? Number(directTime) : 0;
};

const getStoredPreferredSpeed = (waypoint = {}) => {
  if (Number.isFinite(waypoint.preferredSpeed) && waypoint.preferredSpeed > 0) {
    return clampPreferredLegSpeed(waypoint.preferredSpeed);
  }

  if (Number.isFinite(waypoint.estimatedSpeed) && waypoint.estimatedSpeed > 0) {
    return clampPreferredLegSpeed(waypoint.estimatedSpeed);
  }

  return getNominalPreferredLegSpeed(TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED);
};

const normalizeWaypointTiming = (waypoints = []) =>
  waypoints.reduce((normalized, waypoint, index) => {
    const nextWaypoint = {
      ...waypoint,
      timeFromStart: getStoredTimeFromStart(waypoint),
      time: getStoredTimeFromStart(waypoint),
    };

    if (index === 0) {
      normalized.push(nextWaypoint);
      return normalized;
    }

    const previousWaypoint = normalized[index - 1];
    const timingMode = waypoint.timingMode || TIMING_MODES.MANUAL_TIME;

    if (timingMode === TIMING_MODES.AUTO_SPEED) {
      const preferredSpeed = getStoredPreferredSpeed(waypoint);
      const derivedTime = suggestOptimalTime(
        previousWaypoint,
        waypoint,
        preferredSpeed,
        waypoint.altitude
      );

      normalized.push({
        ...nextWaypoint,
        preferredSpeed,
        timeFromStart: derivedTime,
        time: derivedTime,
      });
      return normalized;
    }

    normalized.push(nextWaypoint);
    return normalized;
  }, []);

export const getRetimedAutoSpeedWaypoints = (previousWaypoints = [], nextWaypoints = []) => {
  const previousById = new Map(
    (Array.isArray(previousWaypoints) ? previousWaypoints : [])
      .filter((waypoint) => waypoint?.id)
      .map((waypoint) => [waypoint.id, waypoint])
  );

  return (Array.isArray(nextWaypoints) ? nextWaypoints : [])
    .filter((waypoint) => {
      if (!waypoint?.id || (waypoint.timingMode || TIMING_MODES.MANUAL_TIME) !== TIMING_MODES.AUTO_SPEED) {
        return false;
      }

      const previousWaypoint = previousById.get(waypoint.id);
      if (!previousWaypoint) {
        return false;
      }

      return Math.abs(
        getStoredTimeFromStart(previousWaypoint) - getStoredTimeFromStart(waypoint)
      ) >= 0.05;
    })
    .map((waypoint) => ({
      id: waypoint.id,
      name: waypoint.name || waypoint.id,
      timeFromStart: getStoredTimeFromStart(waypoint),
    }));
};

/**
 * Calculate waypoint speeds and heading using the arrival leg as the authoritative segment.
 * - Waypoint 0 is the route-entry anchor, so it has no inbound leg speed
 * - Every later waypoint owns the speed and auto-heading for the leg that reaches it
 * - Auto heading aligns with the arrival leg from the previous waypoint
 * @param {Array} waypoints - Array of all waypoints
 * @returns {Array} Updated waypoints with consistent arrival-leg speed and heading
 */
export const calculateWaypointSpeeds = (waypoints) => {
  if (!waypoints || waypoints.length === 0) {
    return [];
  }

  const normalizedWaypoints = normalizeWaypointTiming(waypoints);

  return normalizedWaypoints.map((waypoint, index) => {
    if (index === 0) {
      const initialHeading = getStoredHeadingValue(waypoint);
      return {
        ...waypoint,
        estimatedSpeed: 0,
        speed: 0,
        speedFeasible: true,
        speedStatus: 'unknown',
        heading: initialHeading,
        // The mission-start anchor always uses an explicit heading.
        headingMode: YAW_CONSTANTS.MANUAL,
        calculatedHeading: initialHeading,
      };
    }

    const previousWaypoint = normalizedWaypoints[index - 1];
    const arrivalSpeed = calculateSpeed(previousWaypoint, waypoint);
    const speedStatus = validateSpeed(arrivalSpeed);
    const calculatedHeading = calculateHeading(previousWaypoint, waypoint);
    const headingMode = getStoredHeadingMode(waypoint, index);
    const actualHeading = headingMode === YAW_CONSTANTS.AUTO
      ? calculatedHeading
      : getStoredHeadingValue(waypoint, calculatedHeading);

    return {
      ...waypoint,
      estimatedSpeed: arrivalSpeed,
      speed: arrivalSpeed,
      speedFeasible: speedStatus === 'feasible',
      speedStatus,
      heading: actualHeading,
      headingMode,
      calculatedHeading,
    };
  });
};

/**
 * FIXED: Recalculate all waypoint speeds with correct logic
 * @param {Array} waypoints - Array of waypoints to recalculate
 * @returns {Array} Updated waypoints with all speeds recalculated
 */
export const recalculateAllSpeeds = (waypoints) => {
  return calculateWaypointSpeeds(waypoints);
};

/**
 * Recalculate the trajectory after waypoint drag-drop.
 * Drag operations are infrequent and the planner path is modest in size, so the
 * authoritative full recompute is safer than trying to hand-maintain partial legs.
 * @param {Array} waypoints - Array of all waypoints
 * @param {string} movedWaypointId - ID of the waypoint that was moved
 * @returns {Array} Updated waypoints with recalculated speeds
 */
export const recalculateAfterDrag = (waypoints, movedWaypointId) => {
  if (!waypoints || waypoints.length < 2) return waypoints;

  const movedIndex = waypoints.findIndex(wp => wp.id === movedWaypointId);
  if (movedIndex === -1) return waypoints;
  return calculateWaypointSpeeds(waypoints);
};

/**
 * Calculate the inbound-leg speed for a newly proposed waypoint.
 * @param {Object} position - New waypoint position
 * @param {Object} waypointData - New waypoint data (altitude, time, etc.)
 * @param {Array} existingWaypoints - Current waypoints array
 * @returns {number} Estimated speed for the new waypoint
 */
export const calculateSpeedForNewWaypoint = (position, waypointData, existingWaypoints) => {
  if (!existingWaypoints || existingWaypoints.length === 0) {
    // First waypoint has no speed
    return 0;
  }

  // Preview the inbound leg from the previous waypoint to the proposed waypoint.
  const previousWaypoint = existingWaypoints[existingWaypoints.length - 1];
  
  if (!previousWaypoint) return 0;

  const newWaypoint = {
    ...position,
    altitude: waypointData.altitude,
    timeFromStart: waypointData.timeFromStart
  };

  return calculateSpeed(previousWaypoint, newWaypoint);
};

/**
 * Calculate heading for a new waypoint.
 * - Single source of truth: headingMode determines all behavior
 * - Auto mode aligns with the arrival leg from the previous waypoint
 * - Manual mode keeps a user-specified fixed heading
 * - First waypoint defaults to manual because it is the route-entry anchor
 * 
 * @param {Object} position - New waypoint lat/lng position
 * @param {Object} waypointData - Waypoint config (headingMode, heading if manual)
 * @param {Array} existingWaypoints - Current trajectory waypoints
 * @returns {Object} Clean heading data: {heading, headingMode, calculatedHeading}
 */
export const calculateHeadingForNewWaypoint = (position, waypointData, existingWaypoints) => {
  let headingMode = waypointData.headingMode || YAW_CONSTANTS.AUTO;
  let calculatedHeading = YAW_CONSTANTS.DEFAULT_HEADING;
  let actualHeading = YAW_CONSTANTS.DEFAULT_HEADING;

  if (existingWaypoints && existingWaypoints.length > 0) {
    // Not first waypoint: align auto heading with the arrival leg from the previous waypoint.
    const previousWaypoint = existingWaypoints[existingWaypoints.length - 1];
    calculatedHeading = calculateHeading(previousWaypoint, position);
    
    // Apply heading mode logic
    actualHeading = headingMode === YAW_CONSTANTS.AUTO 
      ? calculatedHeading 
      : normalizeHeading(waypointData.heading || calculatedHeading);
  } else {
    // First waypoint: user sets initial drone orientation (defaults to manual)
    actualHeading = normalizeHeading(waypointData.heading || YAW_CONSTANTS.DEFAULT_HEADING);
    headingMode = waypointData.headingMode || YAW_CONSTANTS.MANUAL;
  }

  return {
    heading: actualHeading,
    headingMode: headingMode,
    calculatedHeading: calculatedHeading,
  };
};

/**
 * Validate waypoint sequence for time conflicts
 * @param {Array} waypoints - Array of waypoints to validate
 * @returns {Object} Validation result with issues array
 */
export const validateWaypointSequence = (waypoints) => {
  const issues = [];
  
  if (!waypoints || waypoints.length < 2) {
    return { valid: true, issues: [] };
  }

  for (let i = 1; i < waypoints.length; i++) {
    const current = waypoints[i];
    const previous = waypoints[i - 1];
    
    const currentTime = current.timeFromStart || current.time || 0;
    const previousTime = previous.timeFromStart || previous.time || 0;
    
    if (currentTime <= previousTime) {
      issues.push({
        waypoint: current.name,
        issue: 'time_conflict',
        message: `Time (${currentTime}s) must be greater than previous waypoint time (${previousTime}s)`
      });
    }

    const arrivalLegSpeed = calculateSpeed(previous, current);
    if (arrivalLegSpeed > SPEED_THRESHOLDS.ABSOLUTE_MAX) {
      issues.push({
        waypoint: current.name,
        issue: 'impossible_speed',
        message: `Arrival leg speed (${arrivalLegSpeed.toFixed(1)} m/s) exceeds safe operational limits`
      });
    }
  }

  return {
    valid: issues.length === 0,
    issues
  };
};

/**
 * Calculate total trajectory statistics
 * @param {Array} waypoints - Array of waypoints
 * @returns {Object} Trajectory statistics
 */
export const calculateTrajectoryStats = (waypoints) => {
  const waypointCount = waypoints?.length || 0;
  const routeEntryAnchorCount = waypointCount > 0 ? 1 : 0;
  const routeEntryDelaySeconds = waypointCount > 0
    ? Number(waypoints[0]?.timeFromStart || waypoints[0]?.time || 0)
    : 0;
  const timingModeCounts = {
    [TIMING_MODES.AUTO_SPEED]: 0,
    [TIMING_MODES.MANUAL_TIME]: 0,
  };
  const altitudeReferenceCounts = {
    [ALTITUDE_REFERENCE.MSL]: 0,
    [ALTITUDE_REFERENCE.AGL]: 0,
  };
  const headingModeCounts = {
    [YAW_CONSTANTS.AUTO]: 0,
    [YAW_CONSTANTS.MANUAL]: 0,
  };
  const terrainCoverage = {
    accurate: 0,
    estimated: 0,
    unknown: 0,
  };
  const speedStatusCounts = {
    feasible: 0,
    marginal: 0,
    impossible: 0,
    unknown: 0,
  };
  const authoringBreakdown = {
    routeEntryAnchors: routeEntryAnchorCount,
    speedDrivenLegs: 0,
    timeDrivenLegs: 0,
    entryHeadings: routeEntryAnchorCount,
    autoArrivalHeadings: 0,
    manualArrivalHeadings: 0,
  };

  if (waypoints?.length) {
    waypoints.forEach((waypoint, index) => {
      const timingMode = waypoint.timingMode || TIMING_MODES.MANUAL_TIME;
      const altitudeReference = waypoint.altitudeReference || ALTITUDE_REFERENCE.MSL;
      const headingMode = waypoint.headingMode || (index === 0 ? YAW_CONSTANTS.MANUAL : YAW_CONSTANTS.AUTO);

      timingModeCounts[timingMode] = (timingModeCounts[timingMode] || 0) + 1;
      altitudeReferenceCounts[altitudeReference] = (altitudeReferenceCounts[altitudeReference] || 0) + 1;
      headingModeCounts[headingMode] = (headingModeCounts[headingMode] || 0) + 1;

      if (typeof waypoint.groundElevation === 'number') {
        if (waypoint.terrainAccurate === true) {
          terrainCoverage.accurate += 1;
        } else {
          terrainCoverage.estimated += 1;
        }
      } else {
        terrainCoverage.unknown += 1;
      }
    });
  }

  if (!waypoints || waypoints.length < 2) {
    const soloAltitude = waypoints[0]?.altitude || 0;
    const soloGroundElevation = typeof waypoints[0]?.groundElevation === 'number'
      ? waypoints[0].groundElevation
      : null;
    const routeMotionTime = 0;

    return {
      waypointCount,
      legCount: Math.max(0, waypointCount - 1),
      totalDistance: 0,
      totalTime: routeEntryDelaySeconds,
      routeMotionTime,
      maxSpeed: 0,
      avgSpeed: 0,
      speedWarnings: 0,
      maxAltitude: soloAltitude,
      minAltitude: soloAltitude,
      maxAgl: soloGroundElevation === null ? 0 : Math.max(0, soloAltitude - soloGroundElevation),
      minAgl: soloGroundElevation === null ? 0 : Math.max(0, soloAltitude - soloGroundElevation),
      routeEntryDelaySeconds,
      timingModeCounts,
      altitudeReferenceCounts,
      headingModeCounts,
      authoringBreakdown,
      terrainCoverage,
      speedStatusCounts,
      maxSpeedStatus: 'unknown',
    };
  }

  let totalDistance = 0;
  let maxSpeed = 0;
  let speedWarnings = 0;
  let maxAlt = waypoints[0].altitude;
  let minAlt = waypoints[0].altitude;
  let maxAgl = typeof waypoints[0].groundElevation === 'number'
    ? Math.max(0, waypoints[0].altitude - waypoints[0].groundElevation)
    : 0;
  let minAgl = typeof waypoints[0].groundElevation === 'number'
    ? Math.max(0, waypoints[0].altitude - waypoints[0].groundElevation)
    : 0;

  // Calculate stats using corrected speed logic
  for (let i = 0; i < waypoints.length - 1; i++) {
    const curr = waypoints[i];
    const next = waypoints[i + 1];

    // Calculate segment distance and speed FROM current TO next
    const segmentSpeed = calculateSpeed(curr, next);
    const segmentDistance = calculateSegmentDistance3D(curr, next);
    const speedStatus = validateSpeed(segmentSpeed);
    
    totalDistance += segmentDistance;
    maxSpeed = Math.max(maxSpeed, segmentSpeed);
    maxAlt = Math.max(maxAlt, next.altitude);
    minAlt = Math.min(minAlt, next.altitude);
    speedStatusCounts[speedStatus] = (speedStatusCounts[speedStatus] || 0) + 1;

    if (typeof next.groundElevation === 'number') {
      const nextAgl = Math.max(0, next.altitude - next.groundElevation);
      maxAgl = Math.max(maxAgl, nextAgl);
      minAgl = Math.min(minAgl, nextAgl);
    }

    // Count speed warnings
    if (speedStatus !== 'feasible') {
      speedWarnings++;
    }
  }
  
  // Also check the speed values stored in waypoints (for consistency)
  waypoints.forEach(wp => {
    if (wp.estimatedSpeed && wp.estimatedSpeed > 0) {
      maxSpeed = Math.max(maxSpeed, wp.estimatedSpeed);
    }
  });

  const totalTime = waypoints[waypoints.length - 1]?.timeFromStart || 0;
  const routeMotionTime = Math.max(0, totalTime - routeEntryDelaySeconds);
  const avgSpeed = routeMotionTime > 0 ? totalDistance / routeMotionTime : 0;
  authoringBreakdown.speedDrivenLegs = timingModeCounts[TIMING_MODES.AUTO_SPEED] || 0;
  authoringBreakdown.timeDrivenLegs = Math.max(
    0,
    (timingModeCounts[TIMING_MODES.MANUAL_TIME] || 0) - routeEntryAnchorCount
  );
  authoringBreakdown.autoArrivalHeadings = headingModeCounts[YAW_CONSTANTS.AUTO] || 0;
  authoringBreakdown.manualArrivalHeadings = Math.max(
    0,
    (headingModeCounts[YAW_CONSTANTS.MANUAL] || 0) - routeEntryAnchorCount
  );

  return {
    waypointCount,
    legCount: Math.max(0, waypointCount - 1),
    totalDistance,
    totalTime,
    routeMotionTime,
    maxSpeed,
    avgSpeed: Math.round(avgSpeed * 10) / 10,
    speedWarnings,
    maxAltitude: maxAlt,
    minAltitude: minAlt,
    maxAgl,
    minAgl,
    routeEntryDelaySeconds,
    timingModeCounts,
    altitudeReferenceCounts,
    headingModeCounts,
    authoringBreakdown,
    terrainCoverage,
    speedStatusCounts,
    maxSpeedStatus: validateSpeed(maxSpeed),
  };
};

/**
 * Suggest optimal time for a waypoint based on distance and preferred speed
 * @param {Object} fromWaypoint - Previous waypoint
 * @param {Object} toPosition - Target position
 * @param {number} preferredSpeed - Preferred speed in m/s (defaults to mission policy)
 * @param {number} altitude - Target altitude
 * @returns {number} Suggested time from start
 */
export const suggestOptimalTime = (
  fromWaypoint,
  toPosition,
  preferredSpeed = TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED,
  altitude = TRAJECTORY_ALTITUDE_POLICY.DEFAULT_MSL
) => {
  try {
    const totalDistance = calculateSegmentDistance3D(fromWaypoint, {
      ...toPosition,
      altitude,
    });
    
    const requiredTime = totalDistance / preferredSpeed;
    const timeStep = TRAJECTORY_TIMING_POLICY.DERIVED_TIME_STEP_S;
    const baseTime = fromWaypoint.timeFromStart || 0;
    const suggestedTime = baseTime + (Math.ceil(requiredTime / timeStep) * timeStep);
    
    return Number(suggestedTime.toFixed(1));
  } catch {
    return Number(
      ((fromWaypoint.timeFromStart || 0) + TRAJECTORY_TIMING_POLICY.DEFAULT_FALLBACK_LEG_DURATION_S).toFixed(1)
    );
  }
};

/**
 * Convert speed between different units
 * @param {number} speed - Speed value
 * @param {string} fromUnit - Source unit ('ms', 'kmh', 'mph', 'knots')
 * @param {string} toUnit - Target unit
 * @returns {number} Converted speed
 */
export const convertSpeed = (speed, fromUnit = 'ms', toUnit = 'ms') => {
  // Convert to m/s first
  let speedInMS = speed;
  
  switch (fromUnit) {
    case 'kmh':
      speedInMS = speed / 3.6;
      break;
    case 'mph':
      speedInMS = speed * 0.44704;
      break;
    case 'knots':
      speedInMS = speed * 0.514444;
      break;
    case 'ms':
    default:
      speedInMS = speed;
      break;
  }
  
  // Convert from m/s to target unit
  switch (toUnit) {
    case 'kmh':
      return Math.round(speedInMS * 3.6 * 10) / 10;
    case 'mph':
      return Math.round(speedInMS * 2.23694 * 10) / 10;
    case 'knots':
      return Math.round(speedInMS * 1.94384 * 10) / 10;
    case 'ms':
    default:
      return Math.round(speedInMS * 10) / 10;
  }
};
