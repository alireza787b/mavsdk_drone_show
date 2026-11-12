import { getHeartbeatTimestamp, normalizeComparableId } from './missionIdentityUtils';
import { getDroneReferenceNowMs } from './droneRuntimeStatus';

// Slot fields on a configured-but-unseen heartbeat row are placeholders, not
// assignment observations. Liveness of telemetry alone cannot validate them.
export function getMissionSlotEvidence(heartbeat, nowMs = Date.now()) {
  const timestamp = getHeartbeatTimestamp(heartbeat);
  const now = getDroneReferenceNowMs(heartbeat, nowMs);
  const ageSec = timestamp === null ? null : Math.max(0, (now - timestamp) / 1000);
  const presence = heartbeat?.presence;
  const threshold = presence?.thresholds?.live_sec;
  const liveSec = Number.isFinite(threshold) && threshold > 0 ? threshold : 20;
  const state = presence?.state || heartbeat?.presence_state;
  const fresh = ageSec !== null && ageSec <= liveSec
    && presence?.heartbeat_recent !== false
    && !['never_seen', 'offline', 'stale', 'recently_lost'].includes(state);
  return {
    fresh, ageSec,
    assignedPosId: fresh ? normalizeComparableId(heartbeat?.pos_id) : '',
    autoPosId: fresh ? normalizeComparableId(heartbeat?.detected_pos_id) : '',
  };
}

function formatSlotValue(value) {
  return value ? `P${value}` : 'Unavailable';
}

function buildSlotChip(label, value, tone = 'neutral') {
  return {
    label,
    rawValue: value || '',
    value: formatSlotValue(value),
    tone: value ? tone : 'missing',
  };
}

export function determineMissionSlotStatus(configPosId, assignedPosId, autoPosId) {
  const configStr = normalizeComparableId(configPosId);
  const assignedStr = normalizeComparableId(assignedPosId);
  const autoStr = normalizeComparableId(autoPosId);

  const noAutoDetection = autoStr === '0' || !autoStr;
  const effectiveAutoStr = noAutoDetection ? '' : autoStr;
  const noHeartbeatData = !assignedStr && !effectiveAutoStr;
  const allMatch = (
    configStr
    && assignedStr
    && effectiveAutoStr
    && configStr === assignedStr
    && assignedStr === effectiveAutoStr
  );
  const configAssignedMatchNoAuto = (
    configStr
    && assignedStr
    && configStr === assignedStr
    && noAutoDetection
  );
  const anyMismatch = (
    !allMatch
    && !configAssignedMatchNoAuto
    && !noHeartbeatData
    && (
      (assignedStr && configStr !== assignedStr)
      || (effectiveAutoStr && configStr !== effectiveAutoStr)
      || (assignedStr && effectiveAutoStr && assignedStr !== effectiveAutoStr)
    )
  );

  return {
    configStr,
    assignedStr,
    autoStr: effectiveAutoStr,
    noAutoDetection,
    noHeartbeatData,
    allMatch,
    configAssignedMatchNoAuto,
    anyMismatch,
  };
}

export function buildMissionSlotStatusPresentation(configPosId, assignedPosId, autoPosId) {
  const slotStatus = determineMissionSlotStatus(configPosId, assignedPosId, autoPosId);
  const {
    configStr,
    assignedStr,
    autoStr,
    noHeartbeatData,
    allMatch,
    configAssignedMatchNoAuto,
    anyMismatch,
  } = slotStatus;

  if (noHeartbeatData) {
    return {
      ...slotStatus,
      tone: 'pending',
      headline: 'Slot not checked',
      detail: configStr
        ? `Mission config is staged for ${formatSlotValue(configStr)}.`
        : 'Mission config does not include a confirmed slot yet.',
      footnote: 'Connect the aircraft for a live slot check.',
      chips: [
        buildSlotChip('Cfg', configStr, 'aligned'),
      ],
      actions: {},
    };
  }

  if (allMatch) {
    return {
      ...slotStatus,
      tone: 'verified',
      headline: 'Slot verified',
      detail: 'Configured, heartbeat, and auto-detected sources agree.',
      footnote: '',
      chips: [
        buildSlotChip('Cfg', configStr, 'aligned'),
        buildSlotChip('HB', assignedStr, 'aligned'),
        buildSlotChip('Auto', autoStr, 'aligned'),
      ],
      actions: {},
    };
  }

  if (configAssignedMatchNoAuto) {
    return {
      ...slotStatus,
      tone: 'verified',
      headline: 'Slot confirmed',
      detail: 'Mission config matches the live heartbeat slot.',
      footnote: '',
      chips: [
        buildSlotChip('Cfg', configStr, 'aligned'),
        buildSlotChip('HB', assignedStr, 'aligned'),
      ],
      actions: {},
    };
  }

  if (anyMismatch) {
    return {
      ...slotStatus,
      tone: 'review',
      headline: 'Slot mismatch',
      detail: 'Configured and live slot sources disagree. Review before flight.',
      footnote: '',
      chips: [
        buildSlotChip('Cfg', configStr, 'configured'),
        buildSlotChip('HB', assignedStr, assignedStr && assignedStr === configStr ? 'aligned' : 'attention'),
        buildSlotChip('Auto', autoStr, autoStr && autoStr === configStr ? 'aligned' : 'attention'),
      ],
      actions: {
        acceptAutoValue: autoStr && autoStr !== '0' && autoStr !== configStr ? autoStr : '',
        acceptAssignedValue: assignedStr && assignedStr !== configStr ? assignedStr : '',
      },
    };
  }

  return {
    ...slotStatus,
    tone: 'pending',
    headline: 'Slot review pending',
    detail: configStr ? `Mission config is staged for ${formatSlotValue(configStr)}.` : 'Slot data is incomplete.',
    footnote: '',
    chips: [
      buildSlotChip('Cfg', configStr, 'aligned'),
      buildSlotChip('HB', assignedStr),
      buildSlotChip('Auto', autoStr),
    ],
    actions: {},
  };
}
