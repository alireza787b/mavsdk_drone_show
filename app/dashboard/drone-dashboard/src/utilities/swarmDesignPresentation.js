import { normalizeComparableId } from './missionIdentityUtils';

const nameOf = (aircraft) => String(aircraft.callsign || '').trim() || String(aircraft.alias || '').trim();

export function aircraftIdentity(aircraft) {
  const hw = normalizeComparableId(aircraft.hw_id);
  const pos = normalizeComparableId(aircraft.pos_id);
  return [hw && `H${hw}`, pos && `P${pos}`].filter(Boolean).join(' · ');
}

export function buildAircraftLabels(aircraft, showIds = false) {
  const counts = new Map();
  aircraft.forEach((entry) => {
    const name = nameOf(entry).toLocaleLowerCase();
    if (name) counts.set(name, (counts.get(name) || 0) + 1);
  });
  return Object.fromEntries(aircraft.map((entry) => {
    const name = nameOf(entry);
    const hardware = `H${normalizeComparableId(entry.hw_id)}`;
    const label = showIds ? [name, aircraftIdentity(entry)].filter(Boolean).join(' · ')
      : name ? `${name}${counts.get(name.toLocaleLowerCase()) > 1 ? ` · ${hardware}` : ''}` : hardware;
    return [String(entry.hw_id), label];
  }));
}

/** Presentation only: never quantize the underlying draft or API payload. */
export function formatFormationDistance(value) {
  if (value === '' || value == null || !Number.isFinite(Number(value))) return value ?? '';
  const n = Number(value), magnitude = Math.abs(n);
  const digits = magnitude < 10 ? 2 : magnitude < 1000 ? 1 : 0;
  return String(Number(n.toFixed(digits)) || 0);
}
