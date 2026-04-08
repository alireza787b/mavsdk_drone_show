import {
  buildLastKnownPointGeoJSON,
  calculateCircularAreaSqM,
  hasFiniteLatLng,
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

  it('builds a closed polygon for last known point preview', () => {
    const geojson = buildLastKnownPointGeoJSON({ lat: 37.0, lng: -122.0 }, 150, 24);
    expect(geojson).not.toBeNull();
    expect(geojson.features).toHaveLength(1);
    expect(geojson.features[0].geometry.type).toBe('Polygon');
    expect(geojson.features[0].geometry.coordinates[0]).toHaveLength(25);
  });
});
