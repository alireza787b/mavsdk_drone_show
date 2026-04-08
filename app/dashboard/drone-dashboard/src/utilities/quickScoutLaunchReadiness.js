import { FIELD_NAMES } from '../constants/fieldMappings';
import { getDroneReadinessModel } from './droneReadiness';
import { getDroneRuntimeStatus } from './droneRuntimeStatus';
import { getDroneDisplayIdentity } from './dronePresentation';

function normalizeId(value) {
  return String(value ?? '').trim();
}

function summarizeIssue(issueMap) {
  return Object.values(issueMap);
}

export function buildQuickScoutLaunchReadiness({
  drones = [],
  targetHwIds = [],
  referenceNowMs = Date.now(),
} = {}) {
  const normalizedTargetIds = [...new Set(
    (Array.isArray(targetHwIds) ? targetHwIds : [])
      .map((value) => normalizeId(value))
      .filter(Boolean),
  )];

  const targetLookup = new Set(normalizedTargetIds);
  const targetDrones = (Array.isArray(drones) ? drones : []).filter((drone) => {
    const hwId = normalizeId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID || drone?.hw_id);
    return hwId && targetLookup.has(hwId);
  });
  const foundLookup = new Set(
    targetDrones.map((drone) => normalizeId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID || drone?.hw_id)),
  );

  const blockersByKey = {};
  const warningsByKey = {};
  const counts = {
    target: normalizedTargetIds.length,
    online: 0,
    degraded: 0,
    unavailable: 0,
    ready: 0,
    review: 0,
    blocked: 0,
    armed: 0,
  };

  normalizedTargetIds.forEach((hwId) => {
    if (foundLookup.has(hwId)) {
      return;
    }

    blockersByKey[`missing-${hwId}`] = {
      key: `missing-${hwId}`,
      label: `H${hwId}`,
      detail: 'Assigned aircraft is not present in the current fleet snapshot.',
    };
  });

  targetDrones.forEach((drone) => {
    const hwId = normalizeId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID || drone?.hw_id);
    const identity = getDroneDisplayIdentity(drone);
    const runtimeStatus = getDroneRuntimeStatus(drone, referenceNowMs);
    const readiness = getDroneReadinessModel(drone, runtimeStatus);

    if (drone?.[FIELD_NAMES.IS_ARMED]) {
      counts.armed += 1;
    }

    if (runtimeStatus.level === 'online') {
      counts.online += 1;
    } else if (runtimeStatus.level === 'degraded') {
      counts.degraded += 1;
      warningsByKey[`runtime-${hwId}`] = {
        key: `runtime-${hwId}`,
        label: identity.primary,
        detail: runtimeStatus.label,
      };
    } else {
      counts.unavailable += 1;
      counts.blocked += 1;
      blockersByKey[`runtime-${hwId}`] = {
        key: `runtime-${hwId}`,
        label: identity.primary,
        detail: runtimeStatus.label,
      };
      return;
    }

    if (readiness.isReady) {
      counts.ready += 1;
      return;
    }

    if (readiness.status === 'warning') {
      counts.review += 1;
      warningsByKey[`readiness-${hwId}`] = {
        key: `readiness-${hwId}`,
        label: identity.primary,
        detail: readiness.summary || readiness.statusLabel,
      };
      return;
    }

    counts.blocked += 1;
    blockersByKey[`readiness-${hwId}`] = {
      key: `readiness-${hwId}`,
      label: identity.primary,
      detail: readiness.summary || readiness.statusLabel,
    };
  });

  const blockers = summarizeIssue(blockersByKey);
  const warnings = summarizeIssue(warningsByKey);

  return {
    canLaunch: normalizedTargetIds.length > 0 && blockers.length === 0,
    targetHwIds: normalizedTargetIds,
    targetDrones,
    blockers,
    warnings,
    counts,
  };
}

export default buildQuickScoutLaunchReadiness;
