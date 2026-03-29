import { ALTITUDE_REFERENCE } from './SpeedCalculator';
import {
  applyWaypointTerrainContext,
  resolveWaypointTerrainContext,
} from './trajectoryTerrainContext';

describe('trajectoryTerrainContext', () => {
  it('preserves Target AGL intent by recomputing stored MSL altitude at new terrain', () => {
    const patch = applyWaypointTerrainContext({
      waypoint: {
        altitude: 160,
        altitudeReference: ALTITUDE_REFERENCE.AGL,
        targetAgl: 120,
        groundElevation: 40,
      },
      latitude: 35.72,
      longitude: 51.27,
      terrainResult: {
        elevation: 85,
        source: 'backend',
      },
    });

    expect(patch).toEqual(
      expect.objectContaining({
        latitude: 35.72,
        longitude: 51.27,
        groundElevation: 85,
        terrainAccurate: true,
        targetAgl: 120,
        altitude: 205,
      })
    );
  });

  it('keeps stored MSL altitude intact while updating derived terrain context', () => {
    const patch = applyWaypointTerrainContext({
      waypoint: {
        altitude: 150,
        altitudeReference: ALTITUDE_REFERENCE.MSL,
        targetAgl: 0,
        groundElevation: 20,
      },
      latitude: 35.73,
      longitude: 51.28,
      terrainResult: {
        elevation: 90,
        source: 'backend',
      },
    });

    expect(patch).toEqual(
      expect.objectContaining({
        groundElevation: 90,
        terrainAccurate: true,
        targetAgl: 60,
      })
    );
  });

  it('marks estimated terrain when the resolver falls back', async () => {
    const patch = await resolveWaypointTerrainContext(
      {
        altitude: 150,
        altitudeReference: ALTITUDE_REFERENCE.MSL,
        groundElevation: 40,
      },
      {
        latitude: 35.74,
        longitude: 51.29,
      },
      jest.fn().mockResolvedValue({
        elevation: 95,
        source: 'static',
        error: 'Using estimated elevation data',
      })
    );

    expect(patch).toEqual(
      expect.objectContaining({
        groundElevation: 95,
        terrainAccurate: false,
        terrainSource: 'static',
        terrainError: 'Using estimated elevation data',
        targetAgl: 55,
      })
    );
  });
});
