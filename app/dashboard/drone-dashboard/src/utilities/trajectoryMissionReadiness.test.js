import { ALTITUDE_REFERENCE } from './SpeedCalculator';
import { buildTrajectoryMissionReadiness } from './trajectoryMissionReadiness';

describe('trajectoryMissionReadiness', () => {
  test('marks a single-waypoint route as draft only', () => {
    const readiness = buildTrajectoryMissionReadiness({
      waypoints: [
        {
          id: 'wp-1',
          name: 'Waypoint 1',
          altitude: 1300,
          timeFromStart: 0,
        },
      ],
      stats: {
        speedWarnings: 0,
        speedStatusCounts: { feasible: 0, marginal: 0, impossible: 0, unknown: 0 },
        terrainCoverage: { accurate: 0, estimated: 0, unknown: 1 },
        altitudeReferenceCounts: { [ALTITUDE_REFERENCE.MSL]: 1, [ALTITUDE_REFERENCE.AGL]: 0 },
      },
    });

    expect(readiness.posture).toMatchObject({
      tone: 'danger',
      label: 'Draft only',
      transferLabel: 'Send Draft to Leader',
    });
    expect(readiness.blockers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: 'single_waypoint' }),
      ]),
    );
  });

  test('surfaces time conflicts as blockers and terrain caveats as advisories', () => {
    const readiness = buildTrajectoryMissionReadiness({
      waypoints: [
        {
          id: 'wp-1',
          name: 'Waypoint 1',
          latitude: 35.7,
          longitude: 51.2,
          altitude: 1300,
          timeFromStart: 20,
        },
        {
          id: 'wp-2',
          name: 'Waypoint 2',
          latitude: 35.71,
          longitude: 51.21,
          altitude: 1320,
          timeFromStart: 10,
        },
      ],
      stats: {
        speedWarnings: 1,
        speedStatusCounts: { feasible: 0, marginal: 1, impossible: 0, unknown: 0 },
        terrainCoverage: { accurate: 0, estimated: 1, unknown: 0 },
        altitudeReferenceCounts: { [ALTITUDE_REFERENCE.MSL]: 1, [ALTITUDE_REFERENCE.AGL]: 1 },
      },
    });

    expect(readiness.posture.tone).toBe('danger');
    expect(readiness.blockers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: 'time_conflict' }),
      ]),
    );
    expect(readiness.advisories).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ tone: 'warning' }),
      ]),
    );
    expect(readiness.notes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ tone: 'info' }),
      ]),
    );
  });

  test('marks internally consistent paths as ready to process', () => {
    const readiness = buildTrajectoryMissionReadiness({
      waypoints: [
        {
          id: 'wp-1',
          name: 'Waypoint 1',
          latitude: 35.7,
          longitude: 51.2,
          altitude: 1300,
          timeFromStart: 0,
        },
        {
          id: 'wp-2',
          name: 'Waypoint 2',
          latitude: 35.701,
          longitude: 51.201,
          altitude: 1310,
          timeFromStart: 20,
        },
      ],
      stats: {
        speedWarnings: 0,
        speedStatusCounts: { feasible: 1, marginal: 0, impossible: 0, unknown: 0 },
        terrainCoverage: { accurate: 2, estimated: 0, unknown: 0 },
        altitudeReferenceCounts: { [ALTITUDE_REFERENCE.MSL]: 2, [ALTITUDE_REFERENCE.AGL]: 0 },
      },
    });

    expect(readiness.posture).toMatchObject({
      tone: 'success',
      label: 'Ready to process',
      transferLabel: 'Send to Leader',
    });
    expect(readiness.blockers).toHaveLength(0);
    expect(readiness.advisories).toHaveLength(0);
  });
});
