import { ALTITUDE_REFERENCE, TIMING_MODES, YAW_CONSTANTS } from './SpeedCalculator';
import { TrajectoryStorage } from './TrajectoryStorage';

describe('TrajectoryStorage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('preserves timing and terrain planning metadata through save/load', async () => {
    const storage = new TrajectoryStorage();

    const saveResult = await storage.saveTrajectory('timing-check', [
      {
        id: 'wp-1',
        name: 'Waypoint 1',
        latitude: 35.7262,
        longitude: 51.2721,
        altitude: 320,
        altitudeReference: ALTITUDE_REFERENCE.AGL,
        targetAgl: 120,
        timeFromStart: 24,
        timingMode: TIMING_MODES.AUTO_SPEED,
        preferredSpeed: 6,
        estimatedSpeed: 5.8,
        speedFeasible: true,
        groundElevation: 200,
        terrainAccurate: true,
        heading: 90,
        headingMode: YAW_CONSTANTS.AUTO,
        calculatedHeading: 90,
      },
    ]);

    expect(saveResult.success).toBe(true);

    const loadResult = await storage.loadTrajectory('timing-check');
    expect(loadResult.success).toBe(true);
    expect(loadResult.trajectory.waypoints[0]).toEqual(expect.objectContaining({
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 6,
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      targetAgl: 120,
      groundElevation: 200,
      terrainAccurate: true,
      headingMode: YAW_CONSTANTS.AUTO,
    }));
  });
});
