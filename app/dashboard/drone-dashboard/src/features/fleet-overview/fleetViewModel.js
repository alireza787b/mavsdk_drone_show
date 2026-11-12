import { DRONE_RUNTIME_CLOCK_PROP } from '../../constants/fieldMappings';
import { getDroneRuntimeStatus, getDroneReferenceNowMs } from '../../utilities/droneRuntimeStatus';
import { getBatteryPresentation } from '../../utilities/batteryPresentation';
import { getDroneDisplayIdentity } from '../../utilities/dronePresentation';
import { resolveMslAltitude } from '../../utilities/telemetryAltitude';
import { px4LandedState } from '../../utilities/px4LandedState';
import { classifyNodeBootStatus } from '../../utilities/fleetOpsViewModel';
import { getFlightModeName } from '../../constants/px4FlightModes';
import { getCommandMetadata } from '../../constants/missionCatalog';
import { getFriendlyMissionName } from '../../utilities/missionUtils';
import { getAircraftAvailability } from './fleetAvailability';
import { uniqueTargetIds } from './targetSelection';
import { getFleetNetworkStatus } from './fleetNetworkStatus';

const SAMPLE_CURRENT_MS = 10000;
const GPS_LABELS = ['No GPS', 'No fix', '2D fix', '3D fix', 'DGPS', 'RTK float', 'RTK fixed', 'Static', 'PPP'];
const FLIGHT_LABELS = { ON_GROUND: 'Grounded', IN_AIR: 'Airborne', TAKING_OFF: 'Taking off', LANDING: 'Landing' };

function numberOrNull(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && !value.trim()) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function sampleIsCurrent(drone, prefix, nowMs) {
  const age = numberOrNull(drone[`${prefix}_age_ms`]);
  const timestamp = numberOrNull(drone[`${prefix}_timestamp_ms`]);
  const receivedAt = numberOrNull(drone[DRONE_RUNTIME_CLOCK_PROP]?.receivedAtMs);
  const elapsed = receivedAt === null ? 0 : Math.max(0, nowMs - receivedAt);
  if (age !== null && (age < 0 || age + elapsed > SAMPLE_CURRENT_MS)) return false;
  if (timestamp !== null && (timestamp <= 0 || getDroneReferenceNowMs(drone, nowMs) - timestamp > SAMPLE_CURRENT_MS)) return false;
  return true;
}

// The legacy altitude helper accepts null/empty as zero. Sanitize at this boundary
// without altering its other consumers or discarding genuine zero measurements.
function altitudeEvidence(drone) {
  const safe = { ...drone };
  ['position_alt', 'altitude', 'gps_raw_altitude_m', 'local_position_down'].forEach((key) => {
    safe[key] = numberOrNull(drone[key]) ?? undefined;
  });
  if (drone.altitude_report && typeof drone.altitude_report === 'object') {
    safe.altitude_report = {
      ...drone.altitude_report,
      display_m: numberOrNull(drone.altitude_report.display_m) ?? undefined,
    };
  }
  const altitude = resolveMslAltitude(safe);
  if (altitude.source === 'unavailable') return { ...altitude, value: null, trustedForMap: false };
  return altitude;
}

/** Pure presentation only. No displayed state grants command admission. */
export function buildAircraftViewModel(drone, nowMs, displayPolicy) {
  if (!Number.isFinite(nowMs)) throw new TypeError('Fleet presentation requires an explicit nowMs clock');
  const [id] = uniqueTargetIds([drone?.hw_id ?? drone?.hw_ID]);
  if (!id) return null;
  const identity = getDroneDisplayIdentity({ ...drone, hw_id: id });
  const runtime = getDroneRuntimeStatus(drone, nowMs);
  const availability = getAircraftAvailability(drone, nowMs, displayPolicy);
  const current = drone.telemetry_available !== false && runtime.level === 'online';
  const boot = classifyNodeBootStatus(drone.node_boot_status, getDroneReferenceNowMs(drone, nowMs));
  const hasTelemetry = runtime.telemetryAgeSec !== null;
  const armed = current && typeof drone.is_armed === 'boolean' ? drone.is_armed : null;
  const flightState = current ? (FLIGHT_LABELS[px4LandedState(drone.landed_state)] || 'Unknown') : 'Unknown';
  const decodedMode = getFlightModeName(drone.flight_mode);
  const modeKnown = hasTelemetry && !/^(?:Unknown|No Data|Invalid Mode|Auto\.\d+)/.test(decodedMode);
  const missionMetadata = hasTelemetry ? getCommandMetadata(drone.mission) : null;
  const nativeBlockers = Array.isArray(drone.preflight_blockers) && drone.preflight_blockers.length > 0;
  const readinessStatus = !current ? 'unknown' : nativeBlockers ? 'blocked'
    : ['ready', 'warning', 'blocked'].includes(drone.readiness_status) ? drone.readiness_status : 'unknown';
  const battery = getBatteryPresentation(drone);
  const batteryAvailable = battery.remaining !== null || (battery.voltage !== null && battery.voltage > 0);
  const batteryCurrent = current && sampleIsCurrent(drone, 'battery', nowMs);
  const altitude = altitudeEvidence(drone);
  const altitudeCurrent = current && !altitude.stale && (
    altitude.source !== 'absolute_msl' || sampleIsCurrent(drone, altitude.trustedForMap ? 'global_position' : 'gps_raw', nowMs)
  );
  const rawFixType = numberOrNull(drone.gps_fix_type);
  const fixType = Number.isInteger(rawFixType) && rawFixType >= 0 && rawFixType < GPS_LABELS.length ? rawFixType : null;
  const satellites = numberOrNull(drone.satellites_visible);
  const gpsCurrent = current && sampleIsCurrent(drone, 'gps_raw', nowMs);
  const latitude = numberOrNull(drone.position_lat);
  const longitude = numberOrNull(drone.position_long);
  const coordinatesValid = latitude !== null && longitude !== null
    && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180;
  const globalValid = coordinatesValid && drone.global_position_valid !== false
    && (drone.global_position_valid === true || latitude !== 0 || longitude !== 0);
  const positionCurrent = current && globalValid && sampleIsCurrent(drone, 'global_position', nowMs);

  const issues = [];
  if (!current && boot.ageSec !== null && (boot.active || boot.state === 'error')) {
    issues.push({ key: 'boot', tone: boot.tone, label: boot.label });
  }
  // A configured but never-observed aircraft is not a new loss-of-link alarm.
  // Once observed, losing it remains an actionable condition even if filtered out.
  if (!current && (hasTelemetry || availability.ageSec !== null || boot.active || boot.state === 'error')) issues.push({
    key: 'telemetry', tone: runtime.indicatorClass === 'offline' ? 'danger' : 'warning',
    label: runtime.level === 'online' ? 'Telemetry unavailable' : runtime.label,
  });
  if (batteryCurrent && ['warning', 'danger'].includes(battery.tone)) {
    issues.push({ key: 'battery', tone: battery.tone, label: `Battery: ${battery.label}` });
  }
  if (current) {
    [['preflight_blockers', 'danger'], ['preflight_warnings', 'warning']].forEach(([field, tone]) => {
      (Array.isArray(drone[field]) ? drone[field] : []).forEach((issue) => {
        if (typeof issue?.message === 'string' && issue.message.trim()) {
          issues.push({ key: `${field}:${issue.message}`, tone, label: issue.message });
        }
      });
    });
    if (drone.readiness_status === 'blocked' && !issues.some((issue) => issue.key.startsWith('preflight_blockers:'))) {
      issues.push({ key: 'readiness', tone: 'warning', label: drone.readiness_summary || 'Preflight blocked' });
    }
  }
  const distinctIssues = Array.from(new Map(issues.map((issue) => [issue.key, issue])).values())
    .sort((left, right) => Number(right.tone === 'danger') - Number(left.tone === 'danger'));

  return {
    id, raw: drone, identity,
    label: identity.alias?.value || `Aircraft ${id}`,
    runtime, availability, boot, current, armed, flightState,
    flightMode: { label: modeKnown ? decodedMode : 'Unknown', known: modeKnown,
      current: current && modeKnown, stale: !current && hasTelemetry && modeKnown },
    mission: { label: missionMetadata ? getFriendlyMissionName(drone.mission) : 'Unknown', known: Boolean(missionMetadata),
      value: missionMetadata?.value ?? null, current: current && Boolean(missionMetadata),
      stale: !current && hasTelemetry && Boolean(missionMetadata) },
    network: getFleetNetworkStatus(drone.heartbeat_network_info, availability.available && !availability.stale),
    readiness: { status: readinessStatus, label: { ready: 'Ready', warning: 'Warning', blocked: 'Blocked', unknown: 'Unknown' }[readinessStatus],
      summary: current && readinessStatus !== 'unknown' ? drone.readiness_summary || '' : '' },
    battery: {
      ...battery, current: batteryCurrent && batteryAvailable,
      stale: batteryAvailable && !batteryCurrent, available: batteryAvailable,
      text: batteryAvailable ? battery.text : 'Unknown',
    },
    altitude: {
      ...altitude, current: altitudeCurrent && altitude.value !== null,
      stale: altitude.value !== null && !altitudeCurrent,
      trustedForMap: Boolean(altitude.trustedForMap && positionCurrent && altitudeCurrent),
    },
    gps: {
      fixType,
      label: GPS_LABELS[fixType] || 'Unknown',
      satellites: Number.isInteger(satellites) && satellites >= 0 && satellites < 255 ? satellites : null,
      hdop: numberOrNull(drone.hdop), vdop: numberOrNull(drone.vdop),
      current: gpsCurrent && fixType !== null, stale: !gpsCurrent && fixType !== null,
    },
    position: {
      latitude: globalValid ? latitude : null,
      longitude: globalValid ? longitude : null,
      current: Boolean(positionCurrent),
      stale: Boolean(globalValid && !positionCurrent),
      reason: positionCurrent ? null : drone.position_unavailable_reason || 'No current trusted position',
    },
    lastKnown: hasTelemetry && !current,
    issues: distinctIssues, attention: distinctIssues.length > 0,
  };
}

/** Preserve prior identity order; append new identities deterministically, never by severity. */
export function buildFleetViewModel(drones = [], { nowMs, previousOrder = [], displayPolicy } = {}) {
  if (!Number.isFinite(nowMs)) throw new TypeError('Fleet presentation requires an explicit nowMs clock');
  const byId = new Map();
  drones.forEach((drone) => {
    const aircraft = buildAircraftViewModel(drone, nowMs, displayPolicy);
    if (aircraft && !byId.has(aircraft.id)) byId.set(aircraft.id, aircraft);
  });
  const retained = uniqueTargetIds(previousOrder).filter((id) => byId.has(id));
  const retainedSet = new Set(retained);
  const added = Array.from(byId.keys()).filter((id) => !retainedSet.has(id))
    .sort((left, right) => left.localeCompare(right, 'en', { numeric: true }));
  const order = [...retained, ...added];
  const aircraft = order.map((id) => byId.get(id));
  const summary = {
    total: aircraft.length,
    current: aircraft.filter((item) => item.current).length,
    available: aircraft.filter((item) => item.availability.available).length,
    stale: aircraft.filter((item) => item.availability.stale).length,
    unavailable: aircraft.filter((item) => !item.current).length,
    attention: aircraft.filter((item) => item.attention).length,
    armed: aircraft.filter((item) => item.armed === true).length,
    disarmed: aircraft.filter((item) => item.armed === false).length,
    armUnknown: aircraft.filter((item) => item.armed === null).length,
    airborne: aircraft.filter((item) => item.flightState === 'Airborne').length,
    grounded: aircraft.filter((item) => item.flightState === 'Grounded').length,
    unmappable: aircraft.filter((item) => !item.position.current).length,
  };
  return { aircraft, byId, order, summary };
}
