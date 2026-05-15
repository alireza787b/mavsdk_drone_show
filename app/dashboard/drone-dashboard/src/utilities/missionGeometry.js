import { area as turfArea } from '@turf/area';
import { buffer as turfBuffer } from '@turf/buffer';
import { lineString as turfLineString, point as turfPoint, polygon as turfPolygon } from '@turf/helpers';

export const MISSION_GEOMETRY_TYPES = Object.freeze({
  POINT: 'point',
  WAYPOINT_SEQUENCE: 'waypoint_sequence',
  POLYLINE: 'polyline',
  POLYGON: 'polygon',
  CORRIDOR: 'corridor',
});

const EARTH_RADIUS_M = 6378137;

const toFiniteNumber = (value) => {
  if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

export function normalizeMissionPoint(point) {
  if (!point) {
    return null;
  }

  if (Array.isArray(point)) {
    const lng = toFiniteNumber(point[0]);
    const lat = toFiniteNumber(point[1]);
    return lat === null || lng === null ? null : { lat, lng };
  }

  const lat = toFiniteNumber(point.lat ?? point.latitude);
  const lng = toFiniteNumber(point.lng ?? point.lon ?? point.longitude);
  return lat === null || lng === null ? null : { lat, lng };
}

export function normalizeMissionPoints(points = []) {
  return (Array.isArray(points) ? points : [])
    .map(normalizeMissionPoint)
    .filter(Boolean);
}

export function haversineDistanceM(start, end) {
  const first = normalizeMissionPoint(start);
  const second = normalizeMissionPoint(end);
  if (!first || !second) {
    return 0;
  }

  const lat1 = (first.lat * Math.PI) / 180;
  const lat2 = (second.lat * Math.PI) / 180;
  const dLat = ((second.lat - first.lat) * Math.PI) / 180;
  const dLng = ((second.lng - first.lng) * Math.PI) / 180;
  const a = (
    (Math.sin(dLat / 2) ** 2)
    + Math.cos(lat1) * Math.cos(lat2) * (Math.sin(dLng / 2) ** 2)
  );
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return EARTH_RADIUS_M * c;
}

export function calculateMissionPathLengthM(points = []) {
  const normalized = normalizeMissionPoints(points);
  if (normalized.length < 2) {
    return 0;
  }

  return normalized.reduce((total, point, index) => {
    if (index === 0) {
      return total;
    }
    return total + haversineDistanceM(normalized[index - 1], point);
  }, 0);
}

function closePolygonRing(points = []) {
  const normalized = normalizeMissionPoints(points);
  if (normalized.length < 3) {
    return normalized;
  }

  const first = normalized[0];
  const last = normalized[normalized.length - 1];
  const closed = first.lat === last.lat && first.lng === last.lng
    ? normalized
    : [...normalized, first];
  return closed;
}

export function buildMissionGeoJSON({
  type,
  points = [],
  point = null,
  corridorWidthM = null,
  properties = {},
} = {}) {
  if (type === MISSION_GEOMETRY_TYPES.POINT) {
    const normalizedPoint = normalizeMissionPoint(point || points[0]);
    if (!normalizedPoint) {
      return null;
    }
    return {
      type: 'FeatureCollection',
      features: [
        turfPoint([normalizedPoint.lng, normalizedPoint.lat], {
          missionGeometryType: type,
          ...properties,
        }),
      ],
    };
  }

  const normalizedPoints = normalizeMissionPoints(points);

  if (type === MISSION_GEOMETRY_TYPES.WAYPOINT_SEQUENCE || type === MISSION_GEOMETRY_TYPES.POLYLINE) {
    if (normalizedPoints.length < 2) {
      return null;
    }
    return {
      type: 'FeatureCollection',
      features: [
        turfLineString(normalizedPoints.map((entry) => [entry.lng, entry.lat]), {
          missionGeometryType: type,
          ...properties,
        }),
      ],
    };
  }

  if (type === MISSION_GEOMETRY_TYPES.POLYGON) {
    const ring = closePolygonRing(normalizedPoints);
    if (ring.length < 4) {
      return null;
    }
    return {
      type: 'FeatureCollection',
      features: [
        turfPolygon([ring.map((entry) => [entry.lng, entry.lat])], {
          missionGeometryType: type,
          ...properties,
        }),
      ],
    };
  }

  if (type === MISSION_GEOMETRY_TYPES.CORRIDOR) {
    const width = toFiniteNumber(corridorWidthM);
    if (normalizedPoints.length < 2 || width === null || width <= 0) {
      return null;
    }

    const centerLine = turfLineString(normalizedPoints.map((entry) => [entry.lng, entry.lat]));
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
            missionGeometryType: type,
            corridorWidthM: width,
            ...properties,
          },
        },
      ],
    };
  }

  return null;
}

export function calculateMissionAreaSqM({ type, points = [], corridorWidthM = null } = {}) {
  const geojson = buildMissionGeoJSON({ type, points, corridorWidthM });
  const feature = geojson?.features?.[0];
  if (!feature || !['Polygon', 'MultiPolygon'].includes(feature.geometry?.type)) {
    return 0;
  }
  return turfArea(feature);
}

export function validateMissionGeometry({
  type,
  point = null,
  points = [],
  corridorWidthM = null,
} = {}) {
  const normalizedPoint = normalizeMissionPoint(point || points[0]);
  const normalizedPoints = normalizeMissionPoints(points);
  const errors = [];
  const warnings = [];

  switch (type) {
    case MISSION_GEOMETRY_TYPES.POINT:
      if (!normalizedPoint) {
        errors.push('Select a valid point.');
      }
      break;
    case MISSION_GEOMETRY_TYPES.WAYPOINT_SEQUENCE:
      if (normalizedPoints.length < 2) {
        errors.push('Add at least two waypoints.');
      }
      break;
    case MISSION_GEOMETRY_TYPES.POLYLINE:
      if (normalizedPoints.length < 2) {
        errors.push('Draw at least two path points.');
      }
      break;
    case MISSION_GEOMETRY_TYPES.POLYGON:
      if (normalizedPoints.length < 3) {
        errors.push('Draw at least three area vertices.');
      }
      break;
    case MISSION_GEOMETRY_TYPES.CORRIDOR: {
      const width = toFiniteNumber(corridorWidthM);
      if (normalizedPoints.length < 2) {
        errors.push('Draw at least two corridor vertices.');
      }
      if (width === null || width <= 0) {
        errors.push('Set a positive corridor width.');
      }
      if (normalizedPoints.length === 2) {
        warnings.push('Two-point corridor is valid; add vertices for a curved shoreline or route.');
      }
      break;
    }
    default:
      errors.push('Choose a mission geometry type.');
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
    point: normalizedPoint,
    points: normalizedPoints,
  };
}

export function summarizeMissionGeometry({
  type,
  point = null,
  points = [],
  corridorWidthM = null,
} = {}) {
  const validation = validateMissionGeometry({ type, point, points, corridorWidthM });
  const normalizedPoints = validation.points;
  const lengthM = calculateMissionPathLengthM(normalizedPoints);
  const areaSqM = calculateMissionAreaSqM({ type, points: normalizedPoints, corridorWidthM });

  return {
    ...validation,
    type,
    pointCount: type === MISSION_GEOMETRY_TYPES.POINT && validation.point
      ? 1
      : normalizedPoints.length,
    lengthM,
    areaSqM,
    corridorWidthM: toFiniteNumber(corridorWidthM),
  };
}

export function formatMetricDistance(meters = 0) {
  const value = toFiniteNumber(meters) ?? 0;
  if (value >= 1000) {
    return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} km`;
  }
  return `${Math.round(value)} m`;
}

export function formatMetricArea(squareMeters = 0) {
  const value = toFiniteNumber(squareMeters) ?? 0;
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)} km²`;
  }
  if (value >= 10_000) {
    return `${(value / 10_000).toFixed(value >= 100_000 ? 0 : 1)} ha`;
  }
  return `${Math.round(value)} m²`;
}
