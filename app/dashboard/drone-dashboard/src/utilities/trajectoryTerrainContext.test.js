import { ALTITUDE_REFERENCE } from './SpeedCalculator';
import { getSwarmTrajectoryElevationBatch } from '../services/droneApiService';
import {
  applyWaypointTerrainContext,
  resolveImportedTrajectoryTerrainContext,
  resolveWaypointTerrainContext,
  resolveMissionTrajectoryTerrain,
  resolveMissionTrajectoryTerrainBatch,
} from './trajectoryTerrainContext';

jest.mock('../services/droneApiService', () => ({ getSwarmTrajectoryElevationBatch: jest.fn() }));

describe('trajectoryTerrainContext', () => {
  beforeEach(() => { getSwarmTrajectoryElevationBatch.mockReset(); });

  it('uses canonical backend status, finite elevation, and matching coordinates, including sea level', async () => {
    getSwarmTrajectoryElevationBatch.mockImplementation(async (points) => ({
      success: true,
      results: points.map((point) => ({ ...point, status: 'ok', elevation_m: 0, source: 'backend', provider: 'terrain-provider', confidence: 'reported', sample_time: 'now' })),
    }));
    expect(await resolveMissionTrajectoryTerrain(0, 0)).toEqual({
      elevation: 0, verified: true, error: '', source: 'terrain-provider', confidence: 'reported', sample_time: 'now',
    });
    expect(getSwarmTrajectoryElevationBatch).toHaveBeenCalledWith([{ id: 'mission-terrain-0', lat: 0, lng: 0 }]);
  });

  it.each([undefined, null, NaN, Infinity, '85'])('does not verify missing or non-finite elevation (%s)', async (elevation_m) => {
    getSwarmTrajectoryElevationBatch.mockImplementation(async (points) => ({
      success: true, results: points.map((point) => ({ ...point, status: 'ok', elevation_m })),
    }));
    const patch = await resolveWaypointTerrainContext({ altitude: 160, altitudeReference: 'AGL', targetAgl: 120, groundElevation: 40 }, { latitude: 0, longitude: 0 });
    expect(patch).toEqual(expect.objectContaining({ terrainAccurate: false, altitude: 160, groundElevation: 40, terrainError: expect.any(String) }));
    expect(patch.terrainError).not.toBe('');
  });

  it('does not trust an unavailable, absent, mismatched or failed backend result', async () => {
    for (const response of [
      { success: true, results: [] },
      { success: true, results: [{ id: 'mission-terrain-0', lat: 1, lng: 0, status: 'ok', elevation_m: 50 }] },
      { success: true, results: [{ id: 'mission-terrain-0', lat: 0, lng: 0, status: 'unavailable', elevation_m: 50 }] },
      { success: false, results: [{ id: 'mission-terrain-0', lat: 0, lng: 0, status: 'ok', elevation_m: 50 }] },
    ]) {
      getSwarmTrajectoryElevationBatch.mockResolvedValue(response);
      expect((await resolveMissionTrajectoryTerrain(0, 0)).verified).toBe(false);
    }
    getSwarmTrajectoryElevationBatch.mockRejectedValue(new Error('Terrain offline'));
    expect(await resolveMissionTrajectoryTerrain(0, 0)).toEqual(expect.objectContaining({ verified: false, elevation: null, error: 'Terrain offline' }));
  });

  it('chunks large backend lookups without guessing invalid coordinates', async () => {
    getSwarmTrajectoryElevationBatch.mockImplementation(async (points) => ({
      success: true, results: points.map((point) => ({ ...point, status: 'ok', elevation_m: 10 })),
    }));
    const results = await resolveMissionTrajectoryTerrainBatch([
      ...Array.from({ length: 501 }, (_, index) => ({ latitude: 0, longitude: index / 1000 })),
      { latitude: null, longitude: 0 },
    ]);
    expect(getSwarmTrajectoryElevationBatch.mock.calls.map(([points]) => points.length)).toEqual([500, 1]);
    expect(results.slice(0, 501).every((result) => result.verified)).toBe(true);
    expect(results[501].verified).toBe(false);
  });

  it('does not turn a retained ground value into verified terrain when no result exists', () => {
    expect(applyWaypointTerrainContext({ waypoint: { altitude: 100, altitudeReference: 'agl', targetAgl: 20, groundElevation: 0 } })).toEqual(expect.objectContaining({
      altitude: 100, groundElevation: 0, terrainAccurate: false, terrainError: 'Terrain elevation unavailable.',
    }));
  });
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

  it('preserves MSL altitude and prior context rather than consuming an unverified fallback', async () => {
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
        groundElevation: 40,
        terrainAccurate: false,
        terrainSource: 'static',
        terrainError: 'Using estimated elevation data',
        targetAgl: 0,
      })
    );
  });

  it('refreshes imported legacy-verified AGL using one canonical batch and keeps MSL unchanged on failure', async () => {
    getSwarmTrajectoryElevationBatch.mockResolvedValue({ success: true, results: [] });
    const result = await resolveImportedTrajectoryTerrainContext([
      { id: 'agl', latitude: 0, longitude: 0, altitude: 200, altitudeReference: 'AGL', targetAgl: 100, groundElevation: 100, terrainAccurate: true },
      { id: 'msl', latitude: 0.001, longitude: 0, altitude: 150, altitudeReference: 'msl' },
    ]);
    expect(getSwarmTrajectoryElevationBatch).toHaveBeenCalledTimes(1);
    expect(result.waypoints[0]).toEqual(expect.objectContaining({ terrainAccurate: false, altitude: 200 }));
    expect(result.waypoints[1].altitude).toBe(150);
    expect(result.unavailableCount).toBe(1);
  });
  it('re-resolves imported terrain-backed waypoints before planner use', async () => {
    const result = await resolveImportedTrajectoryTerrainContext(
      [
        {
          id: 'wp-1',
          altitude: 320,
          altitudeReference: ALTITUDE_REFERENCE.AGL,
          targetAgl: 120,
          groundElevation: 180,
          latitude: 35.72,
          longitude: 51.27,
        },
        {
          id: 'wp-2',
          altitude: 150,
          altitudeReference: ALTITUDE_REFERENCE.MSL,
          latitude: 35.73,
          longitude: 51.28,
        },
      ],
      jest
        .fn()
        .mockResolvedValueOnce({
          elevation: 200,
          source: 'backend',
        })
    );

    expect(result.refreshedCount).toBe(1);
    expect(result.estimatedCount).toBe(0);
    expect(result.waypoints[0]).toEqual(expect.objectContaining({
      groundElevation: 200,
      targetAgl: 120,
      altitude: 320,
      terrainAccurate: true,
    }));
    expect(result.waypoints[1]).toEqual(expect.objectContaining({
      altitude: 150,
      altitudeReference: ALTITUDE_REFERENCE.MSL,
    }));
  });

});
