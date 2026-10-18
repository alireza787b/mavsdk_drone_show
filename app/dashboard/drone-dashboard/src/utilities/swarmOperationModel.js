import { SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M } from './smartSwarmLaunchReadiness';

export function memberLabel(member) {
  return `Drone ${member.hw_id}${member.callsign ? ` · ${member.callsign}` : ''}`;
}

export function movementSummary(member) {
  if (String(member.follow) === '0') return 'Leader · pilot controlled';
  const body = member.frame === 'body';
  const x = Number(member.offset_x || 0);
  const y = Number(member.offset_y || 0);
  const z = Number(member.offset_z || 0);
  return `→ Drone ${member.follow} · ${[
    x && `${Math.abs(x)} m ${body ? (x > 0 ? 'ahead' : 'behind') : (x > 0 ? 'north' : 'south')}`,
    y && `${Math.abs(y)} m ${body ? (y > 0 ? 'right' : 'left') : (y > 0 ? 'east' : 'west')}`,
    z ? `${Math.abs(z)} m ${z > 0 ? 'above' : 'below'}` : 'same height',
  ].filter(Boolean).join(' · ')}`;
}

// Advisory state, not an additional admission gate. Armed is never airborne by itself.
export function memberFlightState(member) {
  if (!member?.available) return 'Unknown';
  if (member.armed === false) return 'Grounded';
  const mode = Number(member.flight_mode);
  const subMode = (mode >>> 24) & 255;
  const mainMode = (mode >>> 16) & 255;
  if (member.armed === true && mainMode === 4) {
    if (subMode === 2) return 'Taking off';
    if (subMode === 5) return 'Returning';
    if (subMode === 6) return 'Landing';
  }
  const report = member.altitude_report;
  const rawHeight = report
    ? (report.source === 'relative_home' && report.stale !== true ? report.relative_home_m : null)
    : member.relative_altitude_m;
  const height = rawHeight === null || rawHeight === undefined ? NaN : Number(rawHeight);
  if (member.armed === true && member.landed_state !== 'ON_GROUND'
      && Number.isFinite(height) && height >= SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M) return 'Airborne';
  return member.armed === true ? 'Armed' : 'Unknown';
}

export function takeoffTargets(members) {
  const states = members.map(memberFlightState);
  // Never silently relaunch or omit an unknown aircraft in a mixed fleet.
  if (states.some((s) => ['Airborne', 'Taking off', 'Returning', 'Landing'].includes(s))) {
    if (states.includes('Unknown') || states.includes('Armed')) return [];
    return members.filter((m) => memberFlightState(m) === 'Grounded').map((m) => m.hw_id);
  }
  return members.map((m) => m.hw_id);
}
