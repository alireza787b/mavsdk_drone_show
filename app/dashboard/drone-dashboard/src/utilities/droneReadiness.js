import { FIELD_NAMES } from '../constants/fieldMappings';
import { getDroneReferenceNowMs } from './droneRuntimeStatus';

const STATUS_LABELS = {
  ready: 'Ready to Fly',
  blocked: 'Not Ready',
  warning: 'Review Warnings',
  unknown: 'Unverified',
};
const READINESS_SNAPSHOT_GRACE_THRESHOLD_MS = 90_000;

function normalizeMessages(messages) {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages
    .filter((message) => message && typeof message === 'object')
    .map((message) => ({
      source: message.source || 'telemetry',
      severity: message.severity || 'warning',
      message: message.message || 'Unknown status message',
      timestamp: Number(message.timestamp) || 0,
    }));
}

function normalizeChecks(checks) {
  if (!Array.isArray(checks)) {
    return [];
  }

  return checks
    .filter((check) => check && typeof check === 'object')
    .map((check) => ({
      id: check.id || 'check',
      label: check.label || 'Check',
      ready: Boolean(check.ready),
      detail: check.detail || '',
    }));
}

function dedupeMessages(messages) {
  const seen = new Set();

  return messages.filter((message) => {
    const key = `${message.source}:${message.message.trim().toLowerCase()}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function getAvailabilityGuard(runtimeStatus, canUseLastSnapshot = false) {
  if (!runtimeStatus || runtimeStatus.level === 'online') {
    return null;
  }

  if (runtimeStatus.level === 'degraded') {
    return {
      source: 'link',
      severity: 'warning',
      message: canUseLastSnapshot
        ? 'Telemetry is delayed. Showing the last readiness snapshot until live telemetry returns.'
        : 'Telemetry is delayed. Readiness cannot be trusted until live telemetry returns.',
      timestamp: Date.now(),
    };
  }

  return {
    source: 'link',
    severity: 'error',
    message: canUseLastSnapshot
      ? 'Telemetry link is stale or lost. Showing the last readiness snapshot; verify the link before launch.'
      : 'Telemetry link is stale or lost. Readiness is currently unavailable.',
    timestamp: Date.now(),
  };
}

function hasFreshReadinessSnapshot(drone, runtimeStatus) {
  const lastUpdateMs = Number(drone?.[FIELD_NAMES.PREFLIGHT_LAST_UPDATE]) || null;
  if (!lastUpdateMs) {
    return false;
  }

  const referenceNowMs = getDroneReferenceNowMs(drone, Date.now());
  if (runtimeStatus?.level === 'online') {
    return true;
  }

  return referenceNowMs - lastUpdateMs <= READINESS_SNAPSHOT_GRACE_THRESHOLD_MS;
}

export function getDroneReadinessModel(drone, runtimeStatus = null) {
  const blockers = normalizeMessages(drone?.[FIELD_NAMES.PREFLIGHT_BLOCKERS]);
  const warnings = normalizeMessages(drone?.[FIELD_NAMES.PREFLIGHT_WARNINGS]);
  const statusMessages = normalizeMessages(drone?.[FIELD_NAMES.STATUS_MESSAGES]);
  const checks = normalizeChecks(drone?.[FIELD_NAMES.READINESS_CHECKS]);

  const statusMessageKeys = new Set([
    ...blockers.map((message) => message.message.trim().toLowerCase()),
    ...warnings.map((message) => message.message.trim().toLowerCase()),
  ]);

  const recentMessages = dedupeMessages(statusMessages)
    .filter((message) => !statusMessageKeys.has(message.message.trim().toLowerCase()))
    .sort((left, right) => right.timestamp - left.timestamp);

  let status = drone?.[FIELD_NAMES.READINESS_STATUS] || (
    drone?.[FIELD_NAMES.IS_READY_TO_ARM] ? 'ready' : 'blocked'
  );
  let summary = drone?.[FIELD_NAMES.READINESS_SUMMARY]
    || (status === 'ready' ? 'Ready to fly' : 'Preflight checks are not complete.');
  let visibleBlockers = blockers;
  let visibleWarnings = warnings;

  const canUseLastSnapshot = hasFreshReadinessSnapshot(drone, runtimeStatus) && status !== 'unknown';
  const availabilityGuard = getAvailabilityGuard(runtimeStatus, canUseLastSnapshot);
  if (availabilityGuard) {
    if (canUseLastSnapshot) {
      visibleWarnings = dedupeMessages([availabilityGuard, ...warnings])
        .sort((left, right) => right.timestamp - left.timestamp);
    } else {
      status = 'unknown';
      summary = availabilityGuard.message;
      visibleBlockers = [availabilityGuard, ...blockers];
    }
  }

  const issueCount = visibleBlockers.length + visibleWarnings.length;

  return {
    status,
    summary,
    statusLabel: STATUS_LABELS[status] || STATUS_LABELS.unknown,
    blockers: visibleBlockers,
    warnings: visibleWarnings,
    recentMessages,
    checks,
    issueCount,
    isReady: status === 'ready' && visibleBlockers.length === 0,
    updatedAt: Number(drone?.[FIELD_NAMES.PREFLIGHT_LAST_UPDATE]) || null,
  };
}
