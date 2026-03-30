import {
  formatTrajectoryDuration,
  getTrajectoryMissionClockSeconds,
  getTrajectoryRouteEntryDelaySeconds,
  getTrajectoryRouteMotionSeconds,
  getWaypointMissionClockSeconds,
  getWaypointRouteEntryDelaySeconds,
  getWaypointRouteMotionSeconds,
} from './trajectoryTimingPresentation';

describe('trajectoryTimingPresentation', () => {
  test('formats short and minute-scale durations consistently', () => {
    expect(formatTrajectoryDuration(12)).toBe('12s');
    expect(formatTrajectoryDuration(83)).toBe('1m 23s');
  });

  test('derives mission clock, route entry, and route motion from trajectory stats', () => {
    const stats = {
      totalTime: 95,
      routeEntryDelaySeconds: 12,
    };

    expect(getTrajectoryMissionClockSeconds(stats)).toBe(95);
    expect(getTrajectoryRouteEntryDelaySeconds(stats)).toBe(12);
    expect(getTrajectoryRouteMotionSeconds(stats)).toBe(83);
  });

  test('prefers explicit route motion when provided in trajectory stats', () => {
    const stats = {
      totalTime: 95,
      routeEntryDelaySeconds: 12,
      routeMotionTime: 80,
    };

    expect(getTrajectoryRouteMotionSeconds(stats)).toBe(80);
  });

  test('derives mission clock, route entry, and route motion from planner waypoints', () => {
    const waypoints = [
      { timeFromStart: 12 },
      { timeFromStart: 42 },
    ];

    expect(getWaypointMissionClockSeconds(waypoints)).toBe(42);
    expect(getWaypointRouteEntryDelaySeconds(waypoints)).toBe(12);
    expect(getWaypointRouteMotionSeconds(waypoints)).toBe(30);
  });
});
