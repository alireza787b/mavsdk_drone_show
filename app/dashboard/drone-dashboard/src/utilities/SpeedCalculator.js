// src/utilities/SpeedCalculator.js
// CRITICAL FIX: Corrected speed calculation logic
// FIXED: Each waypoint shows speed FROM current TO next waypoint (not FROM previous TO current)

import { distance, bearing } from '@turf/turf';

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
 * Yaw (heading) constants - Aviation Standard
 * Aviation heading: 0° = North, 90° = East, 180° = South, 270° = West
 */
export const YAW_CONSTANTS = {
  AUTO: 'auto',         // Automatic: heading to next waypoint
  MANUAL: 'manual',     // Manual: user-specified heading
  DEFAULT_HEADING: 0,   // Default heading (000° - North)
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
    const point1 = [fromPoint.longitude, fromPoint.latitude];
    const point2 = [toPoint.longitude, toPoint.latitude];
    
    // Turf.js bearing returns -180 to 180, convert to 0-360 aviation standard
    let heading = bearing(point1, point2);
    if (heading < 0) {
      heading += 360;
    }
    
    return Math.round(heading * 10) / 10; // Round to 1 decimal place
  } catch (error) {
    console.warn('Heading calculation error:', error);
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
 * CRITICAL FIX: Calculate waypoint speeds and yaw with correct FROM current TO next logic
 * - Each waypoint (except last) shows speed needed FROM current to NEXT waypoint
 * - Yaw calculation: auto = heading to next waypoint, manual = user-specified
 * - Last waypoint shows the speed that was used to reach it (maintains consistency)
 * @param {Array} waypoints - Array of all waypoints
 * @returns {Array} Updated waypoints with corrected speed and yaw calculations
 */
export const calculateWaypointSpeeds = (waypoints) => {
  if (!waypoints || waypoints.length < 2) {
    // Single waypoint: set default heading values
    return waypoints.map(waypoint => ({
      ...waypoint,
      heading: waypoint.heading !== undefined ? waypoint.heading : YAW_CONSTANTS.DEFAULT_HEADING,
      headingMode: waypoint.headingMode || YAW_CONSTANTS.AUTO,
      calculatedHeading: YAW_CONSTANTS.DEFAULT_HEADING
    }));
  }

  return waypoints.map((waypoint, index) => {
    // FIXED LOGIC: Calculate speed and yaw FROM current waypoint TO next waypoint
    if (index < waypoints.length - 1) {
      // Current waypoint shows speed needed to reach NEXT waypoint
      const nextWaypoint = waypoints[index + 1];
      const speedToNext = calculateSpeed(waypoint, nextWaypoint);
      const speedStatus = validateSpeed(speedToNext);
      
      // Calculate automatic heading to next waypoint
      const calculatedHeading = calculateHeading(waypoint, nextWaypoint);
      
      // Determine actual heading based on mode
      let actualHeading;
      let headingMode = waypoint.headingMode || YAW_CONSTANTS.AUTO;
      
      if (headingMode === YAW_CONSTANTS.AUTO) {
        actualHeading = calculatedHeading;
      } else {
        actualHeading = waypoint.heading !== undefined ? normalizeHeading(waypoint.heading) : calculatedHeading;
      }
      
      return {
        ...waypoint,
        estimatedSpeed: speedToNext,
        speed: speedToNext, // Legacy compatibility
        speedFeasible: speedStatus === 'feasible',
        heading: actualHeading,
        headingMode: headingMode,
        calculatedHeading: calculatedHeading
      };
    } else {
      // LAST WAYPOINT: Maintain the speed from the previous leg and set appropriate heading
      const previousWaypoint = waypoints[index - 1];
      let maintainedSpeed = 0;
      let actualHeading = YAW_CONSTANTS.DEFAULT_HEADING;
      let calculatedHeading = YAW_CONSTANTS.DEFAULT_HEADING;
      
      if (previousWaypoint) {
        // Calculate what speed was needed to reach this final waypoint
        maintainedSpeed = calculateSpeed(previousWaypoint, waypoint);
        // For last waypoint, calculated heading could be the same as previous or user-specified
        calculatedHeading = previousWaypoint.calculatedHeading || YAW_CONSTANTS.DEFAULT_HEADING;
      }
      
      let headingMode = waypoint.headingMode || YAW_CONSTANTS.MANUAL; // Last waypoint defaults to manual
      
      if (headingMode === YAW_CONSTANTS.AUTO && previousWaypoint) {
        // Auto mode: maintain heading from previous waypoint
        actualHeading = calculatedHeading;
      } else {
        // Manual mode: use user-specified heading or default
        actualHeading = waypoint.heading !== undefined ? normalizeHeading(waypoint.heading) : YAW_CONSTANTS.DEFAULT_HEADING;
      }
      
      return {
        ...waypoint,
        estimatedSpeed: maintainedSpeed,
        speed: maintainedSpeed, // Legacy compatibility  
        speedFeasible: validateSpeed(maintainedSpeed) === 'feasible',
        heading: actualHeading,
        headingMode: headingMode,
        calculatedHeading: calculatedHeading
      };
    }
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
 * FIXED: Recalculate speeds after waypoint drag-drop operation  
 * @param {Array} waypoints - Array of all waypoints
 * @param {string} movedWaypointId - ID of the waypoint that was moved
 * @returns {Array} Updated waypoints with recalculated speeds
 */
export const recalculateAfterDrag = (waypoints, movedWaypointId) => {
  if (!waypoints || waypoints.length < 2) return waypoints;

  const movedIndex = waypoints.findIndex(wp => wp.id === movedWaypointId);
  if (movedIndex === -1) return waypoints;

  // FIXED: Recalculate with correct FROM current TO next logic including yaw
  return waypoints.map((waypoint, index) => {
    // Recalculate speed and yaw for affected waypoints:
    // 1. The moved waypoint (if it has a next waypoint)
    // 2. The waypoint before the moved one (if it exists)
    // 3. Handle last waypoint special case
    const needsRecalc = (
      index === movedIndex || // The moved waypoint itself
      index === movedIndex - 1 // The waypoint before the moved one
    );

    if (needsRecalc) {
      if (index < waypoints.length - 1) {
        // Calculate speed and yaw FROM current TO next waypoint
        const nextWaypoint = waypoints[index + 1];
        const recalculatedSpeed = calculateSpeed(waypoint, nextWaypoint);
        const speedStatus = validateSpeed(recalculatedSpeed);
        
        // Recalculate heading (aviation standard)
        const calculatedHeading = calculateHeading(waypoint, nextWaypoint);
        let actualHeading;
        const headingMode = waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO;
        
        if (headingMode === YAW_CONSTANTS.AUTO) {
          actualHeading = calculatedHeading;
        } else {
          actualHeading = waypoint.heading !== undefined ? normalizeHeading(waypoint.heading) : (waypoint.yaw !== undefined ? normalizeHeading(waypoint.yaw) : calculatedHeading);
        }

        return {
          ...waypoint,
          estimatedSpeed: recalculatedSpeed,
          speed: recalculatedSpeed, // Legacy compatibility
          speedFeasible: speedStatus === 'feasible',
          heading: actualHeading,
          calculatedHeading: calculatedHeading
        };
      } else if (index === waypoints.length - 1 && index > 0) {
        // Last waypoint: calculate speed from previous waypoint to this one
        const prevWaypoint = waypoints[index - 1];
        const speedToHere = calculateSpeed(prevWaypoint, waypoint);
        const speedStatus = validateSpeed(speedToHere);
        
        // For last waypoint, maintain heading mode and value (aviation standard)
        let actualHeading = waypoint.heading !== undefined ? normalizeHeading(waypoint.heading) : (waypoint.yaw !== undefined ? normalizeHeading(waypoint.yaw) : YAW_CONSTANTS.DEFAULT_HEADING);
        const calculatedHeading = prevWaypoint.calculatedHeading || prevWaypoint.calculatedYaw || YAW_CONSTANTS.DEFAULT_HEADING;

        return {
          ...waypoint,
          estimatedSpeed: speedToHere,
          speed: speedToHere, // Legacy compatibility
          speedFeasible: speedStatus === 'feasible',
          heading: actualHeading,
          calculatedHeading: calculatedHeading
        };
      }
    }

    return waypoint;
  });
};

/**
 * FIXED: Calculate speed for new waypoint during creation
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

  // FIXED: For a new waypoint, we need to calculate the speed FROM the previous waypoint TO this new one
  // But we'll display this as the speed that the PREVIOUS waypoint needs to reach this new one
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
 * Calculate default heading data for new waypoint (aviation standard)
 * @param {Object} position - New waypoint position
 * @param {Object} waypointData - New waypoint data
 * @param {Array} existingWaypoints - Current waypoints array
 * @returns {Object} Heading data object with heading, headingMode, calculatedHeading
 */
export const calculateHeadingForNewWaypoint = (position, waypointData, existingWaypoints) => {
  // Default heading mode and values
  let headingMode = waypointData.headingMode || YAW_CONSTANTS.AUTO;
  let calculatedHeading = YAW_CONSTANTS.DEFAULT_HEADING;
  let actualHeading = YAW_CONSTANTS.DEFAULT_HEADING;

  if (existingWaypoints && existingWaypoints.length > 0) {
    const previousWaypoint = existingWaypoints[existingWaypoints.length - 1];
    
    // Calculate heading from previous waypoint to this new position
    calculatedHeading = calculateHeading(previousWaypoint, position);
    
    // Determine actual heading based on mode
    if (headingMode === YAW_CONSTANTS.AUTO) {
      actualHeading = calculatedHeading;
    } else {
      // Manual mode: use provided heading or default to calculated
      actualHeading = waypointData.heading !== undefined ? normalizeHeading(waypointData.heading) : calculatedHeading;
    }
  } else {
    // First waypoint: use provided heading or default
    actualHeading = waypointData.heading !== undefined ? normalizeHeading(waypointData.heading) : YAW_CONSTANTS.DEFAULT_HEADING;
    headingMode = waypointData.headingMode || YAW_CONSTANTS.MANUAL; // First waypoint defaults to manual
  }

  return {
    heading: actualHeading,
    headingMode: headingMode,
    calculatedHeading: calculatedHeading
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

    // Check speeds using corrected logic - both TO next and FROM previous
    if (i < waypoints.length - 1) {
      const nextWaypoint = waypoints[i + 1];
      const speedToNext = calculateSpeed(current, nextWaypoint);
      
      if (speedToNext > SPEED_THRESHOLDS.ABSOLUTE_MAX) {
        issues.push({
          waypoint: current.name,
          issue: 'impossible_speed',
          message: `Speed to next waypoint (${speedToNext.toFixed(1)} m/s) exceeds safe operational limits`
        });
      }
    } else if (i === waypoints.length - 1 && i > 0) {
      // For last waypoint, check the speed needed to reach it
      const speedToHere = calculateSpeed(previous, current);
      
      if (speedToHere > SPEED_THRESHOLDS.ABSOLUTE_MAX) {
        issues.push({
          waypoint: current.name,
          issue: 'impossible_speed',
          message: `Speed to reach this waypoint (${speedToHere.toFixed(1)} m/s) exceeds safe operational limits`
        });
      }
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

  // Calculate stats using corrected speed logic
  for (let i = 0; i < waypoints.length - 1; i++) {
    const curr = waypoints[i];
    const next = waypoints[i + 1];

    // Calculate segment distance and speed FROM current TO next
    const segmentSpeed = calculateSpeed(curr, next);
    const point1 = [curr.longitude, curr.latitude];
    const point2 = [next.longitude, next.latitude];
    const segmentDistance = distance(point1, point2, { units: 'meters' });
    
    totalDistance += segmentDistance;
    maxSpeed = Math.max(maxSpeed, segmentSpeed);
    maxAlt = Math.max(maxAlt, next.altitude);
    minAlt = Math.min(minAlt, next.altitude);

    // Count speed warnings
    if (validateSpeed(segmentSpeed) !== 'feasible') {
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