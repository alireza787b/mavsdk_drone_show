import { area as turfArea } from '@turf/area';
import { buffer as turfBuffer } from '@turf/buffer';
import { lineString as turfLineString } from '@turf/helpers';

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

export function normalizeSearchPath(path = []) {
  return (Array.isArray(path) ? path : []).filter(hasFiniteLatLng).map((point) => ({
    lat: Number(point.lat),
    lng: Number(point.lng),
  }));
}

export function calculateSearchPathLengthM(path = []) {
  const normalizedPath = normalizeSearchPath(path);
  if (normalizedPath.length < 2) {
    return 0;
  }

  let total = 0;
  for (let index = 1; index < normalizedPath.length; index += 1) {
    const previous = normalizedPath[index - 1];
    const current = normalizedPath[index];
    const lat1 = (previous.lat * Math.PI) / 180;
    const lat2 = (current.lat * Math.PI) / 180;
    const dLat = ((current.lat - previous.lat) * Math.PI) / 180;
    const dLng = ((current.lng - previous.lng) * Math.PI) / 180;

    const a = (
      (Math.sin(dLat / 2) ** 2)
      + Math.cos(lat1) * Math.cos(lat2) * (Math.sin(dLng / 2) ** 2)
    );
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    total += EARTH_RADIUS_M * c;
  }

  return total;
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

export function buildCorridorPathGeoJSON(path = []) {
  const normalizedPath = normalizeSearchPath(path);
  if (normalizedPath.length < 2) {
    return null;
  }

  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {
          template: 'corridor_search',
        },
        geometry: {
          type: 'LineString',
          coordinates: normalizedPath.map((point) => [point.lng, point.lat]),
        },
      },
    ],
  };
}

export function buildCorridorGeoJSON(path = [], corridorWidthM) {
  const normalizedPath = normalizeSearchPath(path);
  const width = Number(corridorWidthM);
  if (normalizedPath.length < 2 || !Number.isFinite(width) || width <= 0) {
    return null;
  }

  const centerLine = turfLineString(normalizedPath.map((point) => [point.lng, point.lat]));
  const buffered = turfBuffer(centerLine, width / 2000, {
    units: 'kilometers',
    steps: 32,
  });

  return {
    type: 'FeatureCollection',
    features: [
      {
        ...buffered,
        properties: {
          ...(buffered.properties || {}),
          template: 'corridor_search',
          corridor_width_m: width,
        },
      },
    ],
  };
}

export function calculateCorridorAreaSqM(path = [], corridorWidthM) {
  const corridorGeojson = buildCorridorGeoJSON(path, corridorWidthM);
  if (!corridorGeojson?.features?.[0]) {
    return 0;
  }
  return turfArea(corridorGeojson.features[0]);
}
