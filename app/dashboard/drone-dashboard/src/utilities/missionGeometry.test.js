import {
  MISSION_GEOMETRY_TYPES,
  buildMissionGeoJSON,
  calculateMissionAreaSqM,
  calculateMissionPathLengthM,
  formatMetricArea,
  formatMetricDistance,
  normalizeMissionPoint,
  summarizeMissionGeometry,
  validateMissionGeometry,
} from './missionGeometry';

describe('missionGeometry shared helpers', () => {
  test('normalizes explicit mission points without rejecting zero coordinates', () => {
    expect(normalizeMissionPoint({ latitude: '0', longitude: '0' })).toEqual({ lat: 0, lng: 0 });
    expect(normalizeMissionPoint([-122.1, 37.2])).toEqual({ lat: 37.2, lng: -122.1 });
    expect(normalizeMissionPoint({ lat: '', lng: -122 })).toBeNull();
  });

  test('validates point, waypoint, polygon, and corridor requirements', () => {
    expect(validateMissionGeometry({
      type: MISSION_GEOMETRY_TYPES.POINT,
      point: { lat: 0, lng: 0 },
    }).valid).toBe(true);

    expect(validateMissionGeometry({
      type: MISSION_GEOMETRY_TYPES.WAYPOINT_SEQUENCE,
      points: [{ lat: 37, lng: -122 }],
    }).errors).toContain('Add at least two waypoints.');

    expect(validateMissionGeometry({
      type: MISSION_GEOMETRY_TYPES.POLYGON,
      points: [
        { lat: 37, lng: -122 },
        { lat: 37.001, lng: -122 },
        { lat: 37.001, lng: -122.001 },
      ],
    }).valid).toBe(true);

    const corridor = validateMissionGeometry({
      type: MISSION_GEOMETRY_TYPES.CORRIDOR,
      points: [
        { lat: 37, lng: -122 },
        { lat: 37.001, lng: -122.001 },
      ],
      corridorWidthM: 90,
    });
    expect(corridor.valid).toBe(true);
    expect(corridor.warnings).toContain('Two-point corridor is valid; add vertices for a curved shoreline or route.');
  });

  test('builds GeoJSON for reusable map previews', () => {
    const line = buildMissionGeoJSON({
      type: MISSION_GEOMETRY_TYPES.POLYLINE,
      points: [
        { lat: 37, lng: -122 },
        { lat: 37.001, lng: -122.001 },
      ],
    });
    const polygon = buildMissionGeoJSON({
      type: MISSION_GEOMETRY_TYPES.POLYGON,
      points: [
        { lat: 37, lng: -122 },
        { lat: 37.001, lng: -122 },
        { lat: 37.001, lng: -122.001 },
      ],
    });
    const corridor = buildMissionGeoJSON({
      type: MISSION_GEOMETRY_TYPES.CORRIDOR,
      points: [
        { lat: 37, lng: -122 },
        { lat: 37.001, lng: -122.001 },
        { lat: 37.002, lng: -122.001 },
      ],
      corridorWidthM: 120,
    });

    expect(line.features[0].geometry.type).toBe('LineString');
    expect(polygon.features[0].geometry.type).toBe('Polygon');
    expect(polygon.features[0].geometry.coordinates[0]).toHaveLength(4);
    expect(corridor.features[0].geometry.type).toBe('Polygon');
    expect(corridor.features[0].properties.corridorWidthM).toBe(120);
  });

  test('summarizes distance and area metrics', () => {
    const points = [
      { lat: 37, lng: -122 },
      { lat: 37.001, lng: -122.001 },
      { lat: 37.002, lng: -122 },
    ];
    const lengthM = calculateMissionPathLengthM(points);
    const areaSqM = calculateMissionAreaSqM({ type: MISSION_GEOMETRY_TYPES.POLYGON, points });
    const summary = summarizeMissionGeometry({
      type: MISSION_GEOMETRY_TYPES.CORRIDOR,
      points,
      corridorWidthM: 120,
    });

    expect(lengthM).toBeGreaterThan(0);
    expect(areaSqM).toBeGreaterThan(0);
    expect(summary.valid).toBe(true);
    expect(summary.pointCount).toBe(3);
    expect(summary.lengthM).toBeGreaterThan(0);
    expect(summary.areaSqM).toBeGreaterThan(0);
  });

  test('formats operator-facing metric labels', () => {
    expect(formatMetricDistance(45)).toBe('45 m');
    expect(formatMetricDistance(1250)).toBe('1.3 km');
    expect(formatMetricArea(900)).toBe('900 m²');
    expect(formatMetricArea(25_000)).toBe('2.5 ha');
    expect(formatMetricArea(2_500_000)).toBe('2.5 km²');
  });
});
