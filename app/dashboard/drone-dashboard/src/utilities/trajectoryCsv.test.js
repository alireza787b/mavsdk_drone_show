import { serializeTrajectoryCsv, TRAJECTORY_CSV_HEADERS } from './trajectoryCsv';

describe('trajectoryCsv', () => {
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
