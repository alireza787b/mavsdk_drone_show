import {
  YAW_CONSTANTS,
  calculateHeadingForNewWaypoint,
  calculateTrajectoryStats,
  calculateWaypointSpeeds,
  suggestOptimalTime,
  validateWaypointSequence,
} from './SpeedCalculator';

describe('SpeedCalculator', () => {
  test('calculateWaypointSpeeds assigns speed to the outgoing leg and preserves manual final heading', () => {
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

    expect(result[0].estimatedSpeed).toBeCloseTo(14.9, 1);
    expect(result[0].heading).toBeCloseTo(0, 1);

    expect(result[1].estimatedSpeed).toBeCloseTo(9.1, 1);
    expect(result[1].headingMode).toBe(YAW_CONSTANTS.AUTO);
    expect(result[1].heading).toBeCloseTo(90, 0);

    expect(result[2].estimatedSpeed).toBeCloseTo(result[1].estimatedSpeed, 1);
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

  test('validateWaypointSequence flags time conflicts and impossible speeds', () => {
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
      timeFromStart: 0,
    };
    const toWaypoint = {
      latitude: 35.001,
      longitude: 51.0,
      altitude: 200,
      timeFromStart: 10,
    };

    const stats = calculateTrajectoryStats([fromWaypoint, toWaypoint]);
    expect(stats.totalDistance).toBeGreaterThan(140);
    expect(stats.totalDistance).toBeCloseTo(149.5, 0);
    expect(stats.avgSpeed).toBeCloseTo(14.9, 1);
    expect(stats.speedWarnings).toBe(1);

    const suggestedTime = suggestOptimalTime(
      fromWaypoint,
      { latitude: 35.001, longitude: 51.0 },
      10,
      200
    );
    expect(suggestedTime).toBe(15);
  });
});
