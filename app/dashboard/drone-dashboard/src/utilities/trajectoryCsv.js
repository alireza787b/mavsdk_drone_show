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
];

function toNumber(value, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function escapeCsvValue(value) {
  const stringValue = String(value ?? '');
  if (/[",\n\r]/.test(stringValue)) {
    return `"${stringValue.replace(/"/g, '""')}"`;
  }
  return stringValue;
}

export function trajectoryWaypointToCsvRow(waypoint = {}) {
  return [
    waypoint.name,
    toNumber(waypoint.latitude).toFixed(8),
    toNumber(waypoint.longitude).toFixed(8),
    toNumber(waypoint.altitude).toFixed(2),
    toNumber(waypoint.timeFromStart).toFixed(1),
    toNumber(waypoint.estimatedSpeed).toFixed(1),
    toNumber(waypoint.heading ?? waypoint.yaw).toFixed(1),
    waypoint.headingMode || waypoint.yawMode || 'auto',
    waypoint.altitudeReference || 'msl',
    toNumber(waypoint.targetAgl).toFixed(1),
    toNumber(waypoint.groundElevation).toFixed(1),
    waypoint.terrainAccurate !== false ? 'true' : 'false',
    waypoint.timingMode || 'manual_time',
    toNumber(waypoint.preferredSpeed).toFixed(1),
    toNumber(waypoint.calculatedHeading).toFixed(1),
  ];
}

export function serializeTrajectoryCsv(waypoints = []) {
  return [TRAJECTORY_CSV_HEADERS, ...waypoints.map(trajectoryWaypointToCsvRow)]
    .map((row) => row.map(escapeCsvValue).join(','))
    .join('\n');
}
