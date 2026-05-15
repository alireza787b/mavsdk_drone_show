const REQUIRED_CSV_HEADERS = [
  'Name',
  'Latitude',
  'Longitude',
  'Altitude_MSL_m',
  'TimeFromStart_s',
  'EstimatedSpeed_ms',
  'Heading_deg',
  'HeadingMode',
  'AltitudeReference',
  'TargetAgl_m',
  'GroundElevation_m',
  'TerrainAccurate',
  'TimingMode',
  'PreferredSpeed_ms',
  'CalculatedHeading_deg',
];

export const SWARM_TRAJECTORY_ALTITUDE_MODES = {
  MSL: 'fixed_msl',
  AGL: 'agl',
  IMPORTED: 'imported',
};

export function toFiniteNumber(value, fallback = null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

export function normalizeDraftWaypoint(raw = {}, index = 0) {
  const latitude = toFiniteNumber(raw.latitude ?? raw.lat);
  const longitude = toFiniteNumber(raw.longitude ?? raw.lng ?? raw.lon);
  const altitude = toFiniteNumber(raw.altitude ?? raw.altitudeMsl ?? raw.alt_msl);
  const timeFromStart = toFiniteNumber(raw.timeFromStart ?? raw.time_s ?? raw.time, index * 30);
  const estimatedSpeed = toFiniteNumber(raw.estimatedSpeed ?? raw.preferredSpeed, 8);
  const heading = toFiniteNumber(raw.heading ?? raw.yaw ?? raw.yaw_deg, 0);
  const targetAgl = toFiniteNumber(raw.targetAgl, 0);
  const groundElevation = toFiniteNumber(raw.groundElevation, 0);

  return {
    id: raw.id || `wp-${Date.now()}-${index}`,
    name: raw.name || `WP${index + 1}`,
    latitude,
    longitude,
    altitude,
    timeFromStart,
    estimatedSpeed,
    heading,
    headingMode: raw.headingMode || 'auto',
    altitudeReference: raw.altitudeReference || 'MSL',
    targetAgl,
    groundElevation,
    terrainAccurate: raw.terrainAccurate !== false,
    timingMode: raw.timingMode || 'manual_time',
    preferredSpeed: toFiniteNumber(raw.preferredSpeed, estimatedSpeed),
    calculatedHeading: toFiniteNumber(raw.calculatedHeading, heading),
  };
}

export function validateDraftWaypoint(waypoint = {}) {
  const errors = [];
  if (!Number.isFinite(waypoint.latitude) || waypoint.latitude < -90 || waypoint.latitude > 90) {
    errors.push('Latitude must be between -90 and 90.');
  }
  if (!Number.isFinite(waypoint.longitude) || waypoint.longitude < -180 || waypoint.longitude > 180) {
    errors.push('Longitude must be between -180 and 180.');
  }
  if (!Number.isFinite(waypoint.altitude) || waypoint.altitude <= 0) {
    errors.push('Altitude MSL must be greater than 0 m.');
  }
  if (!Number.isFinite(waypoint.timeFromStart) || waypoint.timeFromStart < 0) {
    errors.push('Mission time must be 0 seconds or greater.');
  }
  return errors;
}

export function validateDraftWaypoints(waypoints = []) {
  const errors = [];
  if (waypoints.length < 2) {
    errors.push('Add at least two waypoints before assigning a leader route.');
  }
  waypoints.forEach((waypoint, index) => {
    validateDraftWaypoint(waypoint).forEach((error) => {
      errors.push(`Waypoint ${index + 1}: ${error}`);
    });
  });
  return errors;
}

function escapeCsvValue(value) {
  const stringValue = String(value ?? '');
  if (/[",\n\r]/.test(stringValue)) {
    return `"${stringValue.replace(/"/g, '""')}"`;
  }
  return stringValue;
}

export function buildSwarmLeaderCsv(waypoints = []) {
  const normalized = waypoints.map((waypoint, index) => normalizeDraftWaypoint(waypoint, index));
  const errors = validateDraftWaypoints(normalized);
  if (errors.length) {
    throw new Error(errors.join(' '));
  }

  const rows = normalized.map((waypoint) => [
    waypoint.name,
    waypoint.latitude.toFixed(8),
    waypoint.longitude.toFixed(8),
    waypoint.altitude.toFixed(2),
    waypoint.timeFromStart.toFixed(1),
    waypoint.estimatedSpeed.toFixed(1),
    waypoint.heading.toFixed(1),
    waypoint.headingMode,
    waypoint.altitudeReference,
    waypoint.targetAgl.toFixed(1),
    waypoint.groundElevation.toFixed(1),
    waypoint.terrainAccurate ? 'true' : 'false',
    waypoint.timingMode,
    waypoint.preferredSpeed.toFixed(1),
    waypoint.calculatedHeading.toFixed(1),
  ]);

  return [REQUIRED_CSV_HEADERS, ...rows]
    .map((row) => row.map(escapeCsvValue).join(','))
    .join('\n');
}

export function buildTerrainStatusFromResults(results = []) {
  if (!results.length) {
    return {
      status: 'neutral',
      label: 'Terrain not queried',
      detail: 'MSL route authoring does not require terrain lookup.',
    };
  }
  const resolved = results.filter((result) => result.status === 'ok').length;
  if (resolved === results.length) {
    return {
      status: 'success',
      label: 'Terrain ready',
      detail: `${resolved}/${results.length} waypoint elevations resolved.`,
    };
  }
  return {
    status: resolved > 0 ? 'warning' : 'danger',
    label: resolved > 0 ? 'Terrain partial' : 'Terrain unavailable',
    detail: `${resolved}/${results.length} waypoint elevations resolved.`,
  };
}
