export const TRAJECTORY_CSV_HEADERS = [
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
  'TerrainError',
  'TerrainSource',
  'TerrainConfidence',
  'TerrainSampleTime',
];

function toNumber(value, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

export function trajectoryWaypointCore(waypoint = {}, index = 0) {
  const finite = (value, field) => {
    if ((typeof value !== 'number' && typeof value !== 'string')
        || (typeof value === 'string' && value.trim() === '') || !Number.isFinite(Number(value))) {
      throw new Error(`Waypoint ${index + 1}: ${field} must be an explicit finite number.`);
    }
    return Number(value);
  };
  const latitude = finite(waypoint.latitude, 'latitude');
  const longitude = finite(waypoint.longitude, 'longitude');
  const altitude = finite(waypoint.altitude, 'MSL altitude');
  const timeFromStart = finite(waypoint.timeFromStart ?? waypoint.time, 'arrival time');
  if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
    throw new Error(`Waypoint ${index + 1}: latitude or longitude is outside its valid range.`);
  }
  if (timeFromStart < 0) throw new Error(`Waypoint ${index + 1}: arrival time cannot be negative.`);
  return { latitude, longitude, altitude, timeFromStart };
}

function escapeCsvValue(value) {
  const stringValue = String(value ?? '');
  if (/[",\n\r]/.test(stringValue)) {
    return `"${stringValue.replace(/"/g, '""')}"`;
  }
  return stringValue;
}

export function trajectoryWaypointToCsvRow(waypoint = {}, index = 0) {
  const core = trajectoryWaypointCore(waypoint, index);
  return [
    waypoint.name,
    core.latitude.toFixed(8),
    core.longitude.toFixed(8),
    core.altitude.toFixed(2),
    core.timeFromStart.toFixed(1),
    toNumber(waypoint.estimatedSpeed).toFixed(1),
    toNumber(waypoint.heading ?? waypoint.yaw).toFixed(1),
    waypoint.headingMode || waypoint.yawMode || 'auto',
    String(waypoint.altitudeReference || 'msl').toLowerCase(),
    toNumber(waypoint.targetAgl).toFixed(1),
    toNumber(waypoint.groundElevation).toFixed(1),
    waypoint.terrainAccurate === true ? 'true' : 'false',
    waypoint.timingMode || 'manual_time',
    toNumber(waypoint.preferredSpeed).toFixed(1),
    toNumber(waypoint.calculatedHeading).toFixed(1),
    waypoint.terrainError,
    waypoint.terrainSource,
    waypoint.terrainConfidence,
    waypoint.terrainSampleTime,
  ];
}

export function serializeTrajectoryCsv(waypoints = []) {
  return [TRAJECTORY_CSV_HEADERS, ...waypoints.map(trajectoryWaypointToCsvRow)]
    .map((row) => row.map(escapeCsvValue).join(','))
    .join('\n');
}
