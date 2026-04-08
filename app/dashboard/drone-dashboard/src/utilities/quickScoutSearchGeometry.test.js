import {
  buildCorridorGeoJSON,
  buildCorridorPathGeoJSON,
  buildLastKnownPointGeoJSON,
  calculateCorridorAreaSqM,
  calculateCircularAreaSqM,
  hasFiniteLatLng,
  normalizeSearchPath,
} from './quickScoutSearchGeometry';

describe('quickScoutSearchGeometry', () => {
  it('detects valid search centers including zero coordinates', () => {
    expect(hasFiniteLatLng({ lat: 0, lng: 0 })).toBe(true);
    expect(hasFiniteLatLng({ lat: 37.0, lng: -122.0 })).toBe(true);
    expect(hasFiniteLatLng({ lat: null, lng: -122.0 })).toBe(false);
  });

  it('calculates circular area in square meters', () => {
    expect(calculateCircularAreaSqM(120)).toBeCloseTo(Math.PI * 120 * 120, 6);
    expect(calculateCircularAreaSqM(0)).toBe(0);
  });

  it('normalizes corridor path points', () => {
    expect(normalizeSearchPath([
      { lat: '37.0', lng: '-122.0' },
      { lat: null, lng: -122.2 },
      { lat: 37.2, lng: -122.2 },
    ])).toEqual([
      { lat: 37, lng: -122 },
      { lat: 37.2, lng: -122.2 },
    ]);
  });

  it('builds a closed polygon for last known point preview', () => {
    const geojson = buildLastKnownPointGeoJSON({ lat: 37.0, lng: -122.0 }, 150, 24);
    expect(geojson).not.toBeNull();
    expect(geojson.features).toHaveLength(1);
    expect(geojson.features[0].geometry.type).toBe('Polygon');
    expect(geojson.features[0].geometry.coordinates[0]).toHaveLength(25);
  });

  it('builds a corridor line and buffered polygon preview', () => {
    const path = [
      { lat: 37.0, lng: -122.0 },
      { lat: 37.001, lng: -122.002 },
      { lat: 37.003, lng: -122.003 },
    ];

    const line = buildCorridorPathGeoJSON(path);
    const corridor = buildCorridorGeoJSON(path, 90);

    expect(line).not.toBeNull();
    expect(line.features[0].geometry.type).toBe('LineString');
    expect(corridor).not.toBeNull();
    expect(corridor.features[0].geometry.type).toBe('Polygon');
    expect(calculateCorridorAreaSqM(path, 90)).toBeGreaterThan(0);
  });
});
