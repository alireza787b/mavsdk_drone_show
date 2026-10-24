import { px4LandedState } from './px4LandedState';

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
  const landed = px4LandedState(member.landed_state);
  if (member.armed === false) return landed === 'ON_GROUND' ? 'Grounded' : 'Disarmed';
  const mode = Number(member.flight_mode);
  const subMode = (mode >>> 24) & 255;
  const mainMode = (mode >>> 16) & 255;
  if (member.armed === true && mainMode === 4) {
    if (subMode === 2) return 'Taking off';
    if (subMode === 5) return 'Returning';
    if (subMode === 6) return 'Landing';
  }
  if (member.armed === true && landed === 'TAKING_OFF') return 'Taking off';
  if (member.armed === true && landed === 'LANDING') return 'Landing';
  if (member.armed === true && landed === 'IN_AIR') return 'Airborne';
  return member.armed === true ? 'Armed' : 'Unknown';
}

export function takeoffTargets(members) {
  const states = members.map(memberFlightState);
  // Never silently relaunch or omit an unknown aircraft in a mixed fleet.
  if (states.some((s) => ['Airborne', 'Taking off', 'Returning', 'Landing'].includes(s))) {
    if (states.includes('Unknown') || states.includes('Armed')) return [];
    return members.filter((m) => ['Grounded', 'Disarmed'].includes(memberFlightState(m))).map((m) => m.hw_id);
  }
  return members.map((m) => m.hw_id);
}

// A receipt is not a confirmed Hold. Keep each aircraft's terminal action fact
// visible, and stop presenting it as Held when live mode evidence changes.
export function holdNodeStatus(member, execution) {
  const result = execution?.action_result;
  const outcome = result?.final_vehicle_state?.outcome;
  if (member.available && result?.success === true) {
    if (outcome === 'disarmed' && member.armed === false) {
      return { label: memberFlightState(member), tone: 'neutral', symbol: '—' };
    }
    const mode = Number(member.flight_mode);
    if (outcome === 'held' && member.armed === true
        && ((mode >>> 16) & 255) === 4 && ((mode >>> 24) & 255) === 3) {
      return { label: 'Held', tone: 'warning', symbol: 'Ⅱ' };
    }
  }
  return { label: 'Hold unconfirmed', tone: 'warning', symbol: '?' };
}
