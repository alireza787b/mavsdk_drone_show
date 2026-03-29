import {
  ALTITUDE_REFERENCE,
  TIMING_MODES,
  YAW_CONSTANTS,
  buildTrajectoryAttentionItems,
  calculateHeadingForNewWaypoint,
  calculateTrajectoryStats,
  calculateWaypointSpeeds,
  suggestOptimalTime,
  validateWaypointSequence,
} from './SpeedCalculator';

describe('SpeedCalculator', () => {
  test('calculateWaypointSpeeds assigns speed and auto heading to the arrival leg while preserving manual final heading', () => {
    const waypoints = [
      {
        id: 'wp-1',
        name: 'Waypoint 1',
        latitude: 35.0,
        longitude: 51.0,
        altitude: 100,
        timeFromStart: 0,
        headingMode: YAW_CONSTANTS.AUTO,
      },
      {
        id: 'wp-2',
        name: 'Waypoint 2',
        latitude: 35.001,
        longitude: 51.0,
        altitude: 200,
        timeFromStart: 10,
        headingMode: YAW_CONSTANTS.AUTO,
      },
      {
        id: 'wp-3',
        name: 'Waypoint 3',
        latitude: 35.001,
        longitude: 51.001,
        altitude: 200,
        timeFromStart: 20,
        headingMode: YAW_CONSTANTS.MANUAL,
        heading: 270,
      },
    ];

    const result = calculateWaypointSpeeds(waypoints);

    expect(result[0].estimatedSpeed).toBe(0);
    expect(result[0].headingMode).toBe(YAW_CONSTANTS.MANUAL);
    expect(result[0].heading).toBeCloseTo(0, 1);

    expect(result[1].estimatedSpeed).toBe(15);
    expect(result[1].headingMode).toBe(YAW_CONSTANTS.AUTO);
    expect(result[1].heading).toBeCloseTo(0, 0);

    expect(result[2].estimatedSpeed).toBeCloseTo(9.1, 1);
    expect(result[2].calculatedHeading).toBeCloseTo(90, 0);
    expect(result[2].headingMode).toBe(YAW_CONSTANTS.MANUAL);
    expect(result[2].heading).toBe(270);
  });

  test('calculateHeadingForNewWaypoint defaults the first waypoint to manual north and later waypoints to auto heading', () => {
    const first = calculateHeadingForNewWaypoint(
      { latitude: 35.0, longitude: 51.0 },
      {},
      []
    );
    expect(first).toEqual({
      heading: 0,
      headingMode: YAW_CONSTANTS.MANUAL,
      calculatedHeading: 0,
    });

    const second = calculateHeadingForNewWaypoint(
      { latitude: 35.0, longitude: 51.001 },
      { headingMode: YAW_CONSTANTS.AUTO },
      [{ latitude: 35.0, longitude: 51.0 }]
    );
    expect(second.headingMode).toBe(YAW_CONSTANTS.AUTO);
    expect(second.heading).toBeCloseTo(90, 0);
    expect(second.calculatedHeading).toBeCloseTo(90, 0);
  });

  test('validateWaypointSequence flags time conflicts and impossible speeds on separate invalid legs', () => {
    const result = validateWaypointSequence([
      {
        name: 'Waypoint 1',
        latitude: 35.0,
        longitude: 51.0,
        altitude: 100,
        timeFromStart: 10,
      },
      {
        name: 'Waypoint 2',
        latitude: 35.01,
        longitude: 51.0,
        altitude: 100,
        timeFromStart: 10,
      },
      {
        name: 'Waypoint 3',
        latitude: 35.02,
        longitude: 51.0,
        altitude: 100,
        timeFromStart: 20,
      },
    ]);

    expect(result.valid).toBe(false);
    expect(result.issues.map((issue) => issue.issue)).toEqual(
      expect.arrayContaining(['time_conflict', 'impossible_speed'])
    );
  });

  test('calculateTrajectoryStats and suggestOptimalTime use 3D path distance', () => {
    const fromWaypoint = {
      latitude: 35.0,
      longitude: 51.0,
      altitude: 100,
      altitudeReference: ALTITUDE_REFERENCE.MSL,
      groundElevation: 80,
      terrainAccurate: true,
      timingMode: TIMING_MODES.MANUAL_TIME,
      timeFromStart: 0,
      headingMode: YAW_CONSTANTS.MANUAL,
    };
    const toWaypoint = {
      latitude: 35.001,
      longitude: 51.0,
      altitude: 200,
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      targetAgl: 120,
      groundElevation: 85,
      terrainAccurate: false,
      timingMode: TIMING_MODES.AUTO_SPEED,
      timeFromStart: 10,
      headingMode: YAW_CONSTANTS.AUTO,
    };

    const stats = calculateTrajectoryStats([fromWaypoint, toWaypoint]);
    expect(stats.totalDistance).toBeGreaterThan(140);
    expect(stats.totalDistance).toBeCloseTo(149.5, 0);
    expect(stats.avgSpeed).toBe(15);
    expect(stats.speedWarnings).toBe(1);
    expect(stats.maxSpeedStatus).toBe('marginal');
    expect(stats.minAgl).toBe(20);
    expect(stats.maxAgl).toBe(115);
    expect(stats.timingModeCounts).toEqual({
      [TIMING_MODES.AUTO_SPEED]: 1,
      [TIMING_MODES.MANUAL_TIME]: 1,
    });
    expect(stats.altitudeReferenceCounts).toEqual({
      [ALTITUDE_REFERENCE.MSL]: 1,
      [ALTITUDE_REFERENCE.AGL]: 1,
    });
    expect(stats.headingModeCounts).toEqual({
      [YAW_CONSTANTS.AUTO]: 1,
      [YAW_CONSTANTS.MANUAL]: 1,
    });
    expect(stats.terrainCoverage).toEqual({
      accurate: 1,
      estimated: 1,
      unknown: 0,
    });
    expect(stats.speedStatusCounts.marginal).toBe(1);

    const suggestedTime = suggestOptimalTime(
      fromWaypoint,
      { latitude: 35.001, longitude: 51.0 },
      10,
      200
    );
    expect(suggestedTime).toBe(15);
  });

  test('buildTrajectoryAttentionItems surfaces speed, terrain, and AGL caveats from shared stats truth', () => {
    const items = buildTrajectoryAttentionItems({
      speedWarnings: 2,
      altitudeReferenceCounts: {
        [ALTITUDE_REFERENCE.MSL]: 1,
        [ALTITUDE_REFERENCE.AGL]: 2,
      },
      terrainCoverage: {
        accurate: 1,
        estimated: 1,
        unknown: 1,
      },
      speedStatusCounts: {
        feasible: 1,
        marginal: 2,
        impossible: 0,
        unknown: 0,
      },
    });

    expect(items).toEqual([
      expect.objectContaining({
        tone: 'warning',
        text: '2 legs require elevated speed review.',
      }),
      expect.objectContaining({
        tone: 'warning',
        text: '2 waypoints use estimated or missing terrain data.',
      }),
      expect.objectContaining({
        tone: 'info',
        text: 'AGL entries are stored as MSL after applying the current ground estimate.',
      }),
    ]);
  });
});
