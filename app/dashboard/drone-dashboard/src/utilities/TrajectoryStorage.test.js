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

  it('builds export files from the current in-memory planner trajectory without requiring a prior save', () => {
    const storage = new TrajectoryStorage();
    const trajectory = {
      name: 'route-alpha',
      waypoints: [
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
      ],
      metadata: {
        exportedAt: 1234,
      },
    };

    const jsonExport = storage.buildExportFile(trajectory, 'json');
    const csvExport = storage.buildExportFile(trajectory, 'csv');
    const kmlExport = storage.buildExportFile(trajectory, 'kml');

    expect(jsonExport.filename).toBe('route_alpha.json');
    expect(jsonExport.content).toContain('"timingMode": "auto_speed"');
    expect(jsonExport.content).toContain('"altitudeReference": "agl"');

    expect(csvExport.filename).toBe('route_alpha.csv');
    expect(csvExport.content).toContain('Heading_deg,HeadingMode');
    expect(csvExport.content).toContain('90.0,auto');
    expect(csvExport.content).toContain('AltitudeReference,TargetAgl_m,GroundElevation_m,TerrainAccurate,TimingMode,PreferredSpeed_ms,CalculatedHeading_deg');
    expect(csvExport.content).toContain('agl,120.0,200.0,true,auto_speed,6.0,90.0');

    expect(kmlExport.filename).toBe('route_alpha.kml');
    expect(kmlExport.content).toContain('<name>route-alpha</name>');
    expect(kmlExport.content).toContain('Heading: 090° (Auto)');
  });

  it('parses trajectory CSVs with heading mode columns using the current planner defaults', () => {
    const storage = new TrajectoryStorage();
    const parsed = storage.parseCSV(
      [
        'Name,Latitude,Longitude,Altitude_MSL_m,TimeFromStart_s,EstimatedSpeed_ms,Heading_deg,HeadingMode',
        'Waypoint 1,35.72620000,51.27210000,320.00,24.0,5.8,90.0,auto',
        'Waypoint 2,35.72720000,51.27310000,340.00,44.0,6.2,135.0,manual',
      ].join('\n'),
      'route-alpha.csv'
    );

    expect(parsed.name).toBe('route-alpha');
    expect(parsed.waypoints).toHaveLength(2);
    expect(parsed.waypoints[0]).toEqual(
      expect.objectContaining({
        altitudeReference: ALTITUDE_REFERENCE.MSL,
        timingMode: TIMING_MODES.MANUAL_TIME,
        heading: 90,
        headingMode: 'auto',
      })
    );
    expect(parsed.waypoints[1]).toEqual(
      expect.objectContaining({
        estimatedSpeed: 6.2,
        heading: 135,
        headingMode: 'manual',
      })
    );
  });

  it('round-trips extended planner CSV metadata without breaking legacy mission columns', () => {
    const storage = new TrajectoryStorage();
    const csv = [
      'Name,Latitude,Longitude,Altitude_MSL_m,TimeFromStart_s,EstimatedSpeed_ms,Heading_deg,HeadingMode,AltitudeReference,TargetAgl_m,GroundElevation_m,TerrainAccurate,TimingMode,PreferredSpeed_ms,CalculatedHeading_deg',
      'Waypoint 1,35.72620000,51.27210000,320.00,24.0,5.8,90.0,auto,agl,120.0,200.0,true,auto_speed,6.0,90.0',
      'Waypoint 2,35.72720000,51.27310000,340.00,44.0,6.2,135.0,manual,msl,0.0,220.0,false,manual_time,0.0,135.0',
    ].join('\n');

    const parsed = storage.parseCSV(csv, 'route-alpha.csv');

    expect(parsed.waypoints[0]).toEqual(
      expect.objectContaining({
        altitudeReference: ALTITUDE_REFERENCE.AGL,
        targetAgl: 120,
        groundElevation: 200,
        terrainAccurate: true,
        timingMode: TIMING_MODES.AUTO_SPEED,
        preferredSpeed: 6,
        calculatedHeading: 90,
      })
    );

    expect(parsed.waypoints[1]).toEqual(
      expect.objectContaining({
        altitudeReference: ALTITUDE_REFERENCE.MSL,
        targetAgl: 0,
        groundElevation: 220,
        terrainAccurate: false,
        timingMode: TIMING_MODES.MANUAL_TIME,
        preferredSpeed: 0,
        calculatedHeading: 135,
      })
    );
  });

  it('rejects blank save names and normalizes whitespace on valid names', async () => {
    const storage = new TrajectoryStorage();
    const waypoints = [
      {
        id: 'wp-1',
        name: 'Waypoint 1',
        latitude: 35.7262,
        longitude: 51.2721,
        altitude: 100,
        timeFromStart: 10,
        heading: 0,
        headingMode: YAW_CONSTANTS.MANUAL,
      },
      {
        id: 'wp-2',
        name: 'Waypoint 2',
        latitude: 35.7272,
        longitude: 51.2731,
        altitude: 120,
        timeFromStart: 30,
        heading: 45,
        headingMode: YAW_CONSTANTS.AUTO,
      },
    ];

    await expect(storage.saveTrajectory('   ', waypoints)).resolves.toEqual(
      expect.objectContaining({
        success: false,
        error: 'Trajectory name is required',
      })
    );

    const saveResult = await storage.saveTrajectory('  route-alpha  ', waypoints);
    expect(saveResult.success).toBe(true);

    const loadResult = await storage.loadTrajectory('route-alpha');
    expect(loadResult.success).toBe(true);
    expect(loadResult.trajectory.name).toBe('route-alpha');
  });
});
