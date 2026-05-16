import {
  TIMING_MODES,
  YAW_CONSTANTS,
  buildSwarmLeaderCsv,
  buildTerrainStatusFromResults,
  normalizeDraftWaypoint,
  reflowDraftWaypoints,
  validateDraftWaypoints,
} from './swarmTrajectoryDraft';

describe('swarmTrajectoryDraft', () => {
  it('exports processor-compatible leader CSV with explicit zero coordinates preserved', () => {
    const csv = buildSwarmLeaderCsv([
      normalizeDraftWaypoint({
        id: 'a',
        latitude: 0,
        longitude: 0,
        altitude: 100,
        timeFromStart: 0,
        estimatedSpeed: 8,
      }, 0),
      normalizeDraftWaypoint({
        id: 'b',
        latitude: 0.001,
        longitude: 0.002,
        altitude: 110,
        timeFromStart: 30,
        estimatedSpeed: 8,
      }, 1),
    ]);

    expect(csv).toContain('Name,Latitude,Longitude,Altitude_MSL_m,TimeFromStart_s,EstimatedSpeed_ms,Heading_deg,HeadingMode');
    expect(csv).toContain('WP1,0.00000000,0.00000000,100.00,0.0,0.0,0.0,manual');
    expect(csv).toContain('WP2,0.00100000,0.00200000,110.00,30.0,');
    expect(csv).toContain(',auto,MSL,');
  });

  it('reflows auto-speed map waypoints into ETA, speed, and yaw fields', () => {
    const route = reflowDraftWaypoints([
      normalizeDraftWaypoint({
        id: 'a',
        latitude: 35,
        longitude: 51,
        altitude: 100,
        timeFromStart: 0,
        headingMode: YAW_CONSTANTS.MANUAL,
      }, 0),
      normalizeDraftWaypoint({
        id: 'b',
        latitude: 35.01,
        longitude: 51.02,
        altitude: 120,
        timingMode: TIMING_MODES.AUTO_SPEED,
        preferredSpeed: 8,
        headingMode: YAW_CONSTANTS.AUTO,
      }, 1),
    ]);

    expect(route[0]).toEqual(expect.objectContaining({
      name: 'WP1',
      estimatedSpeed: 0,
      headingMode: YAW_CONSTANTS.MANUAL,
    }));
    expect(route[1].timeFromStart).toBeGreaterThan(0);
    expect(route[1].estimatedSpeed).toBeGreaterThan(0);
    expect(route[1].heading).toBeGreaterThan(0);
    expect(route[1]).toEqual(expect.objectContaining({
      timingMode: TIMING_MODES.AUTO_SPEED,
      headingMode: YAW_CONSTANTS.AUTO,
    }));
  });

  it('blocks non-increasing manual route times', () => {
    const route = reflowDraftWaypoints([
      { latitude: 35, longitude: 51, altitude: 100, timeFromStart: 20 },
      {
        latitude: 35.001,
        longitude: 51.002,
        altitude: 100,
        timeFromStart: 20,
        timingMode: TIMING_MODES.MANUAL_TIME,
      },
    ]);

    expect(validateDraftWaypoints(route).join(' ')).toMatch(/Arrival time must be after waypoint 1/);
  });

  it('blocks incomplete or invalid leader routes before upload', () => {
    expect(validateDraftWaypoints([])).toContain('Add at least two waypoints before assigning a leader route.');
    expect(() => buildSwarmLeaderCsv([
      { latitude: 91, longitude: 0, altitude: 100, timeFromStart: 0 },
      { latitude: 35, longitude: 51, altitude: 100, timeFromStart: 20 },
    ])).toThrow(/Latitude must be between -90 and 90/);
  });

  it('summarizes terrain lookup state for waypoint authoring', () => {
    expect(buildTerrainStatusFromResults([]).status).toBe('neutral');
    const ready = buildTerrainStatusFromResults([
      { status: 'ok', source: 'opentopodata' },
      { status: 'ok', source: 'opentopodata' },
    ]);
    expect(ready.status).toBe('success');
    expect(ready.detail).toContain('via opentopodata');
    expect(buildTerrainStatusFromResults([{ status: 'ok' }, { status: 'unavailable' }]).status).toBe('warning');
    expect(buildTerrainStatusFromResults([{ status: 'unavailable' }]).status).toBe('danger');
  });
});
