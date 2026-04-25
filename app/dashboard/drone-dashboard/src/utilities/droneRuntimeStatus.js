import { DRONE_RUNTIME_CLOCK_PROP } from '../constants/fieldMappings';

// Keep link-state conservative without flickering on slower VPSes or brief polling gaps.
const LIVE_TELEMETRY_THRESHOLD_MS = 10_000;
const HEARTBEAT_GRACE_THRESHOLD_MS = 35_000;
const OFFLINE_CONFIRMED_THRESHOLD_MS = 60_000;
const CLIENT_CLOCK_SKEW_TOLERANCE_MS = 30_000;
const MS_PER_SECOND = 1_000;
const UNIX_MS_THRESHOLD = 1_000_000_000_000;

function normalizeTimestampMs(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }

  if (numeric >= UNIX_MS_THRESHOLD) {
    return numeric;
  }

  return numeric * MS_PER_SECOND;
}

function toAgeSeconds(nowMs, timestampMs) {
  if (timestampMs === null) {
    return null;
  }

  return Math.max(0, Math.round((nowMs - timestampMs) / MS_PER_SECOND));
}

function formatAge(ageSeconds, label) {
  if (ageSeconds === null) {
    return `${label}: unavailable`;
  }

  return `${label}: ${ageSeconds}s ago`;
}

function formatClockOffset(offsetMs) {
  const magnitudeSeconds = Math.round(Math.abs(offsetMs) / MS_PER_SECOND);
  if (magnitudeSeconds === 0) {
    return null;
  }

  return `Browser clock offset: ${offsetMs > 0 ? '+' : '-'}${magnitudeSeconds}s vs GCS`;
}

export function getDroneReferenceNowMs(drone, nowMs = Date.now()) {
  const runtimeClock = drone?.[DRONE_RUNTIME_CLOCK_PROP];
  if (!runtimeClock) {
    return nowMs;
  }

  const referenceNowMs = Number(runtimeClock.referenceNowMs);
  const receivedAtMs = Number(runtimeClock.receivedAtMs);
  if (Number.isFinite(referenceNowMs) && Number.isFinite(receivedAtMs)) {
    const elapsedMs = Math.max(0, nowMs - receivedAtMs);
    return referenceNowMs + elapsedMs;
  }

  const referenceTimestampMs = Number(runtimeClock.referenceTimestampMs);
  if (!Number.isFinite(referenceTimestampMs) || !Number.isFinite(receivedAtMs)) {
    return nowMs;
  }

  const elapsedMs = Math.max(0, nowMs - receivedAtMs);
  const calibratedNowMs = referenceTimestampMs + elapsedMs;

  if (Math.abs(nowMs - calibratedNowMs) > CLIENT_CLOCK_SKEW_TOLERANCE_MS) {
    return calibratedNowMs;
  }

  return nowMs;
}

export function getDroneRuntimeStatus(drone, nowMs = Date.now()) {
  const referenceNowMs = getDroneReferenceNowMs(drone, nowMs);
  const calibratedClockOffsetMs = nowMs - referenceNowMs;
  const clockOffsetNote = Math.abs(calibratedClockOffsetMs) > CLIENT_CLOCK_SKEW_TOLERANCE_MS
    ? formatClockOffset(calibratedClockOffsetMs)
    : null;
  const telemetryTimestamp = normalizeTimestampMs(
    drone?.telemetry_available === false
      ? drone?.update_time
      : (drone?.update_time ?? drone?.timestamp)
  );
  const heartbeatTimestamp = normalizeTimestampMs(drone?.heartbeat_last_seen);
  const telemetryAgeSec = toAgeSeconds(referenceNowMs, telemetryTimestamp);
  const heartbeatAgeSec = toAgeSeconds(referenceNowMs, heartbeatTimestamp);

  const hasLiveTelemetry =
    telemetryTimestamp !== null && referenceNowMs - telemetryTimestamp <= LIVE_TELEMETRY_THRESHOLD_MS;
  const hasRecentHeartbeat =
    heartbeatTimestamp !== null && referenceNowMs - heartbeatTimestamp <= HEARTBEAT_GRACE_THRESHOLD_MS;

  if (hasLiveTelemetry) {
    return {
      level: 'online',
      indicatorClass: 'active',
      label: 'Live telemetry',
      tooltip: [formatAge(telemetryAgeSec, 'Telemetry'), formatAge(heartbeatAgeSec, 'Heartbeat'), clockOffsetNote].filter(Boolean).join(' | '),
      telemetryAgeSec,
      heartbeatAgeSec,
    };
  }

  if (hasRecentHeartbeat) {
    return {
      level: 'degraded',
      indicatorClass: 'degraded',
      label: 'Heartbeat only',
      tooltip: ['Telemetry delayed.', formatAge(telemetryAgeSec, 'Telemetry'), formatAge(heartbeatAgeSec, 'Heartbeat'), clockOffsetNote].filter(Boolean).join(' | '),
      telemetryAgeSec,
      heartbeatAgeSec,
    };
  }

  if (telemetryTimestamp !== null || heartbeatTimestamp !== null) {
    const newestTimestamp = Math.max(telemetryTimestamp ?? 0, heartbeatTimestamp ?? 0);
    const linkAgeMs = newestTimestamp > 0 ? referenceNowMs - newestTimestamp : null;
    const recentlyLost = linkAgeMs !== null && linkAgeMs <= OFFLINE_CONFIRMED_THRESHOLD_MS;
    return {
      level: 'offline',
      indicatorClass: recentlyLost ? 'lost' : 'offline',
      label: recentlyLost ? 'Link lost' : 'Offline',
      tooltip: [
        recentlyLost ? 'Recent link loss.' : 'No recent telemetry or heartbeat.',
        formatAge(telemetryAgeSec, 'Telemetry'),
        formatAge(heartbeatAgeSec, 'Heartbeat'),
        clockOffsetNote,
      ].filter(Boolean).join(' | '),
      telemetryAgeSec,
      heartbeatAgeSec,
    };
  }

  return {
    level: 'unknown',
    indicatorClass: 'never-seen',
    label: 'Never seen',
    tooltip: 'No telemetry or heartbeat received yet.',
    telemetryAgeSec: null,
    heartbeatAgeSec: null,
  };
}
