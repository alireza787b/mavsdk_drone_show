const EARTH_RADIUS_M = 6378137;

function hasFiniteCoordinate(value) {
  if (value === null || value === undefined || value === '') {
    return false;
  }
  return Number.isFinite(Number(value));
}

export function hasFiniteLatLng(point) {
  return hasFiniteCoordinate(point?.lat) && hasFiniteCoordinate(point?.lng);
}

export function calculateCircularAreaSqM(radiusM) {
  const radius = Number(radiusM);
  if (!Number.isFinite(radius) || radius <= 0) {
    return 0;
  }
  return Math.PI * radius * radius;
}

export function buildLastKnownPointGeoJSON(center, radiusM, steps = 48) {
  if (!hasFiniteLatLng(center)) {
    return null;
  }

  const radius = Number(radiusM);
  if (!Number.isFinite(radius) || radius <= 0) {
    return null;
  }

  const baseLat = Number(center.lat);
  const baseLng = Number(center.lng);
  const safeSteps = Math.max(12, Math.floor(Number(steps) || 0));
  const cosLat = Math.cos((baseLat * Math.PI) / 180);
  const coordinates = [];

  for (let index = 0; index <= safeSteps; index += 1) {
    const angle = (2 * Math.PI * index) / safeSteps;
    const east = radius * Math.cos(angle);
    const north = radius * Math.sin(angle);
    const dLat = (north / EARTH_RADIUS_M) * (180 / Math.PI);
    const dLng = (east / (EARTH_RADIUS_M * Math.max(Math.abs(cosLat), 1e-6))) * (180 / Math.PI);
    coordinates.push([baseLng + dLng, baseLat + dLat]);
  }

  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {
          template: 'last_known_point',
          radius_m: radius,
        },
        geometry: {
          type: 'Polygon',
          coordinates: [coordinates],
        },
      },
    ],
  };
}
