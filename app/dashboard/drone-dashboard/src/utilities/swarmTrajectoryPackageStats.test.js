import {
  formatSwarmTrajectoryAltitudeEnvelope,
  formatSwarmTrajectoryMissionSeconds,
  formatSwarmTrajectoryPackageTimingSummary,
  normalizeSwarmTrajectoryPackageStats,
} from './swarmTrajectoryPackageStats';

describe('swarmTrajectoryPackageStats', () => {
  test('normalizes backend snake_case package stats into shared frontend shape', () => {
    expect(normalizeSwarmTrajectoryPackageStats({
      available: true,
      drone_count: 3,
      route_entry_time_s: 26.4,
      mission_clock_s: 46.4,
      route_motion_time_s: 20.0,
      max_altitude_msl_m: 1305.09,
      min_altitude_msl_m: 1290.09,
      altitude_window_m: 15.0,
    })).toEqual({
      available: true,
      droneCount: 3,
      routeEntryTimeS: 26.4,
      missionClockS: 46.4,
      routeMotionTimeS: 20,
      maxAltitudeMslM: 1305.09,
      minAltitudeMslM: 1290.09,
      altitudeWindowM: 15,
    });
  });

  test('formats mission timing and altitude envelope consistently across launch surfaces', () => {
    const packageStats = {
      available: true,
      drone_count: 3,
      route_entry_time_s: 26.4,
      mission_clock_s: 46.4,
      route_motion_time_s: 20.0,
      max_altitude_msl_m: 1305.09,
      min_altitude_msl_m: 1290.09,
      altitude_window_m: 15.0,
    };

    expect(formatSwarmTrajectoryMissionSeconds(46.4)).toBe('46.4s');
    expect(formatSwarmTrajectoryPackageTimingSummary(packageStats)).toBe(
      '46.4s mission clock • entry 26.4s • motion 20.0s',
    );
    expect(formatSwarmTrajectoryAltitudeEnvelope(packageStats)).toBe(
      '1290.1-1305.1 m MSL • window 15.0 m',
    );
  });
});
