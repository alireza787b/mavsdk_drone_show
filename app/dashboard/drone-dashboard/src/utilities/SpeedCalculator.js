// src/utilities/SpeedCalculator.js
// PHASE 1 ENHANCEMENTS: Drag-drop recalculation utilities

import { distance } from '@turf/turf';

/**
 * Drone speed thresholds (m/s)
 * Based on typical commercial drone specifications
 */
export const SPEED_THRESHOLDS = {
  MIN_SPEED: 0.1,        // Minimum practical speed
  OPTIMAL_MAX: 12,       // Optimal max speed for most operations
  MARGINAL_MAX: 20,      // High speed but still feasible
  ABSOLUTE_MAX: 30,      // Beyond safe operational limits
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
    
    // Calculate horizontal distance using Turf.js
    const point1 = [fromWaypoint.longitude, fromWaypoint.latitude];
    const point2 = [targetPosition.longitude, targetPosition.latitude];
    const horizontalDistance = distance(point1, point2, { units: 'meters' });
    
    // Calculate altitude difference
    const altitudeDifference = Math.abs(toWaypoint.altitude - fromWaypoint.altitude);
    
    // Calculate 3D distance using Pythagorean theorem
    const totalDistance = Math.sqrt(
      Math.pow(horizontalDistance, 2) + Math.pow(altitudeDifference, 2)
    );
    
    // Calculate time difference
    const timeDifference = toWaypoint.timeFromStart - (fromWaypoint.timeFromStart || 0);
    
    if (timeDifference <= 0) {
      return 0;
    }
    
    // Calculate required speed
    const requiredSpeed = totalDistance / timeDifference;
    
    return Math.round(requiredSpeed * 10) / 10; // Round to 1 decimal place
  } catch (error) {
    console.warn('Speed calculation error:', error);
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

/**
 * PHASE 1: Recalculate speeds after waypoint drag-drop operation
 * This function updates speeds for the moved waypoint and any affected segments
 * @param {Array} waypoints - Array of all waypoints
 * @param {string} movedWaypointId - ID of the waypoint that was moved
 * @returns {Array} Updated waypoints with recalculated speeds
 */
export const recalculateAfterDrag = (waypoints, movedWaypointId) => {
  if (!waypoints || waypoints.length < 2) return waypoints;

  const movedIndex = waypoints.findIndex(wp => wp.id === movedWaypointId);
  if (movedIndex === -1) return waypoints;

  return waypoints.map((waypoint, index) => {
    // Skip first waypoint (no speed calculation needed)
    if (index === 0) return waypoint;

    // Recalculate speed for moved waypoint and next waypoint after moved one
    if (index === movedIndex || index === movedIndex + 1) {
      const previousWaypoint = waypoints[index - 1];
      const recalculatedSpeed = calculateSpeed(previousWaypoint, waypoint);
      const speedStatus = validateSpeed(recalculatedSpeed);

      return {
        ...waypoint,
        estimatedSpeed: recalculatedSpeed,
        speed: recalculatedSpeed, // Legacy compatibility
        speedFeasible: speedStatus === 'feasible'
      };
    }

    return waypoint;
  });
};

/**
 * PHASE 1: Batch recalculate all waypoint speeds in trajectory
 * Useful after multiple edits or complex operations
 * @param {Array} waypoints - Array of waypoints to recalculate
 * @returns {Array} Updated waypoints with all speeds recalculated
 */
export const recalculateAllSpeeds = (waypoints) => {
  if (!waypoints || waypoints.length < 2) return waypoints;

  return waypoints.map((waypoint, index) => {
    if (index === 0) {
      // First waypoint has no speed requirement
      return {
        ...waypoint,
        estimatedSpeed: 0,
        speed: 0,
        speedFeasible: true
      };
    }

    const previousWaypoint = waypoints[index - 1];
    const recalculatedSpeed = calculateSpeed(previousWaypoint, waypoint);
    const speedStatus = validateSpeed(recalculatedSpeed);

    return {
      ...waypoint,
      estimatedSpeed: recalculatedSpeed,
      speed: recalculatedSpeed, // Legacy compatibility
      speedFeasible: speedStatus === 'feasible'
    };
  });
};

/**
 * PHASE 1: Validate waypoint sequence for time conflicts
 * Ensures all waypoints have incrementing time values
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

    // Check for impossible speeds
    if (current.estimatedSpeed > SPEED_THRESHOLDS.ABSOLUTE_MAX) {
      issues.push({
        waypoint: current.name,
        issue: 'impossible_speed',
        message: `Speed (${current.estimatedSpeed.toFixed(1)} m/s) exceeds safe operational limits`
      });
    }
  }

  return {
    valid: issues.length === 0,
    issues
  };
};

/**
 * Calculate total trajectory statistics including speeds
 * @param {Array} waypoints - Array of waypoints
 * @returns {Object} Trajectory statistics
 */
export const calculateTrajectoryStats = (waypoints) => {
  if (!waypoints || waypoints.length < 2) {
    return {
      totalDistance: 0,
      totalTime: 0,
      maxSpeed: 0,
      avgSpeed: 0,
      speedWarnings: 0,
      maxAltitude: waypoints[0]?.altitude || 0,
      minAltitude: waypoints[0]?.altitude || 0,
    };
  }

  let totalDistance = 0;
  let maxSpeed = 0;
  let speedWarnings = 0;
  let maxAlt = waypoints[0].altitude;
  let minAlt = waypoints[0].altitude;

  for (let i = 1; i < waypoints.length; i++) {
    const prev = waypoints[i - 1];
    const curr = waypoints[i];

    // Calculate segment distance and speed
    const segmentSpeed = calculateSpeed(prev, curr);
    const point1 = [prev.longitude, prev.latitude];
    const point2 = [curr.longitude, curr.latitude];
    const segmentDistance = distance(point1, point2, { units: 'meters' });
    
    totalDistance += segmentDistance;
    maxSpeed = Math.max(maxSpeed, segmentSpeed);
    maxAlt = Math.max(maxAlt, curr.altitude);
    minAlt = Math.min(minAlt, curr.altitude);

    // Count speed warnings
    if (validateSpeed(segmentSpeed) !== 'feasible') {
      speedWarnings++;
    }
  }

  const totalTime = waypoints[waypoints.length - 1].timeFromStart || 0;
  const avgSpeed = totalTime > 0 ? totalDistance / totalTime : 0;

  return {
    totalDistance,
    totalTime,
    maxSpeed,
    avgSpeed: Math.round(avgSpeed * 10) / 10,
    speedWarnings,
    maxAltitude: maxAlt,
    minAltitude: minAlt,
  };
};

/**
 * Suggest optimal time for a waypoint based on distance and preferred speed
 * @param {Object} fromWaypoint - Previous waypoint
 * @param {Object} toPosition - Target position
 * @param {number} preferredSpeed - Preferred speed in m/s (default: 8 m/s)
 * @param {number} altitude - Target altitude
 * @returns {number} Suggested time from start
 */
export const suggestOptimalTime = (fromWaypoint, toPosition, preferredSpeed = 8, altitude = 100) => {
  try {
    const point1 = [fromWaypoint.longitude, fromWaypoint.latitude];
    const point2 = [toPosition.longitude, toPosition.latitude];
    const horizontalDistance = distance(point1, point2, { units: 'meters' });
    
    const altitudeDifference = Math.abs(altitude - fromWaypoint.altitude);
    const totalDistance = Math.sqrt(
      Math.pow(horizontalDistance, 2) + Math.pow(altitudeDifference, 2)
    );
    
    const requiredTime = totalDistance / preferredSpeed;
    const suggestedTime = (fromWaypoint.timeFromStart || 0) + Math.ceil(requiredTime);
    
    return suggestedTime;
  } catch (error) {
    console.warn('Time suggestion error:', error);
    return (fromWaypoint.timeFromStart || 0) + 10; // Default fallback
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