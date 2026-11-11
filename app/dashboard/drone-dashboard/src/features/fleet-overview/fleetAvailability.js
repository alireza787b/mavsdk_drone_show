import { DRONE_RUNTIME_CLOCK_PROP } from '../../constants/fieldMappings';
import { getDroneReferenceNowMs } from '../../utilities/droneRuntimeStatus';

export const DEFAULT_FLEET_AVAILABILITY_POLICY = Object.freeze({ stale_sec: 10, available_sec: 60 });

function finiteNumber(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function timestampMs(value) {
  const number = finiteNumber(value);
  if (number === null || number <= 0) return null;
  return number < 1_000_000_000_000 ? number * 1000 : number;
}

function threshold(value, fallback) {
  const number = finiteNumber(value);
  return number !== null && number >= 0 ? number : fallback;
}

/** Heartbeat presence is advisory visibility/selection evidence, never flight readiness. */
export function getAircraftAvailability(drone, nowMs, policy = DEFAULT_FLEET_AVAILABILITY_POLICY) {
  const unknown = { available: false, stale: false, ageSec: null, label: 'Unknown', tone: 'muted' };
  if (!Number.isFinite(nowMs)) return unknown;
  const referenceNowMs = getDroneReferenceNowMs(drone, nowMs);
  if (!Number.isFinite(referenceNowMs) || referenceNowMs <= 0) return unknown;

  const presence = drone?.presence;
  // An explicit canonical receipt wins, even when invalid. Never replace it
  // with a newer node timestamp or an HTTP/telemetry response timestamp.
  const canonicalReceipt = presence && Object.prototype.hasOwnProperty.call(presence, 'heartbeat_received_at_gcs_ms');
  const rawTimestamp = canonicalReceipt ? presence.heartbeat_received_at_gcs_ms : drone?.heartbeat_last_seen;
  const timestamp = timestampMs(rawTimestamp);
  let ageSec = null;
  if (timestamp !== null) {
    if (timestamp > referenceNowMs) return unknown;
    ageSec = (referenceNowMs - timestamp) / 1000;
  } else if (rawTimestamp !== null && rawTimestamp !== undefined) {
    return unknown;
  } else if (!canonicalReceipt) {
    // An age-only snapshot must have its original receipt clock. A repeated
    // render or failed refresh cannot restart the heartbeat's age.
    const age = finiteNumber(presence?.heartbeat_age_sec);
    const clock = drone?.[DRONE_RUNTIME_CLOCK_PROP];
    const receivedAtMs = finiteNumber(clock?.receivedAtMs);
    const serverNowMs = finiteNumber(clock?.referenceNowMs);
    if (age !== null && age >= 0 && receivedAtMs !== null && receivedAtMs > 0
      && serverNowMs !== null && serverNowMs > 0) {
      ageSec = age + Math.max(0, nowMs - receivedAtMs) / 1000;
    }
  }
  if (ageSec === null) return unknown;

  const availableSec = threshold(policy?.available_sec, DEFAULT_FLEET_AVAILABILITY_POLICY.available_sec);
  const staleSec = Math.min(availableSec, threshold(policy?.stale_sec, DEFAULT_FLEET_AVAILABILITY_POLICY.stale_sec));
  const available = ageSec <= availableSec;
  const stale = available && ageSec > staleSec;
  return { available, stale, ageSec,
    label: !available ? 'Offline' : stale ? 'Stale' : 'Fresh',
    tone: !available ? 'danger' : stale ? 'warning' : 'good' };
}
