import {
  buildSwarmLeaderCsv,
  buildTerrainStatusFromResults,
  normalizeDraftWaypoint,
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
    expect(csv).toContain('WP1,0.00000000,0.00000000,100.00,0.0,8.0,0.0,auto');
    expect(csv).toContain('WP2,0.00100000,0.00200000,110.00,30.0,8.0,0.0,auto');
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
    expect(buildTerrainStatusFromResults([{ status: 'ok' }, { status: 'ok' }]).status).toBe('success');
    expect(buildTerrainStatusFromResults([{ status: 'ok' }, { status: 'unavailable' }]).status).toBe('warning');
    expect(buildTerrainStatusFromResults([{ status: 'unavailable' }]).status).toBe('danger');
  });
});
