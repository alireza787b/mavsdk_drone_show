import { serializeTrajectoryCsv, TRAJECTORY_CSV_HEADERS } from './trajectoryCsv';

describe('trajectoryCsv', () => {
  const core = { latitude: 0, longitude: 0, altitude: 100, timeFromStart: 0 };

  it.each(['', ' ', null, undefined, true, [], {}, '12garbage', Infinity])('rejects invalid coordinates instead of inventing zero (%s)', (latitude) => {
    expect(() => serializeTrajectoryCsv([{ ...core, latitude }])).toThrow(/latitude.*explicit finite number/);
  });

  it('preserves explicit sea-level and zero coordinates', () => {
    expect(serializeTrajectoryCsv([{ ...core, altitude: 0 }])).toContain(',0.00000000,0.00000000,0.00,0.0,');
  });
  it('keeps existing flight columns stable and appends optional terrain provenance', () => {
    expect(TRAJECTORY_CSV_HEADERS.slice(0, 15)).toEqual([
      'Name', 'Latitude', 'Longitude', 'Altitude_MSL_m', 'TimeFromStart_s',
      'EstimatedSpeed_ms', 'Heading_deg', 'HeadingMode', 'AltitudeReference',
      'TargetAgl_m', 'GroundElevation_m', 'TerrainAccurate', 'TimingMode',
      'PreferredSpeed_ms', 'CalculatedHeading_deg',
    ]);
    expect(TRAJECTORY_CSV_HEADERS.slice(15)).toEqual([
      'TerrainError', 'TerrainSource', 'TerrainConfidence', 'TerrainSampleTime',
    ]);
  });

  it.each([undefined, false, 'true', null])('does not serialize %s as verified terrain', (terrainAccurate) => {
    const csv = serializeTrajectoryCsv([{ ...core, name: 'WP1', terrainAccurate }]);
    expect(csv.split('\n')[1].split(',')[11]).toBe('false');
  });

  it('preserves explicit verification alongside escaped provenance rather than dropping an error', () => {
    const csv = serializeTrajectoryCsv([{
      ...core, name: 'WP1', terrainAccurate: true, altitudeReference: 'AGL',
      terrainError: 'Unavailable, retry', terrainSource: 'Service "A"',
    }]);
    expect(csv).toContain(',agl,0.0,0.0,true,');
    expect(csv).toContain('"Unavailable, retry","Service ""A"""');
  });

  it('serializes the shared leader-route CSV contract with escaped names', () => {
    const csv = serializeTrajectoryCsv([
      {
        name: 'WP, Harbor',
        latitude: 35,
        longitude: 51.25,
        altitude: 120,
        timeFromStart: 30,
        estimatedSpeed: 8,
        heading: 90,
        headingMode: 'auto',
        altitudeReference: 'agl',
        targetAgl: 50,
        groundElevation: 70,
        terrainAccurate: true,
        timingMode: 'manual_time',
        preferredSpeed: 8,
        calculatedHeading: 90,
      },
    ]);

    expect(csv.split('\n')[0]).toBe(TRAJECTORY_CSV_HEADERS.join(','));
    expect(csv).toContain('"WP, Harbor",35.00000000,51.25000000,120.00,30.0,8.0,90.0,auto,agl,50.0,70.0,true,manual_time,8.0,90.0');
  });
});
