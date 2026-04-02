import { normalizeComparableId } from './missionIdentityUtils';

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
    noAutoDetection,
    noHeartbeatData,
    allMatch,
    configAssignedMatchNoAuto,
    anyMismatch,
  } = slotStatus;

  if (noHeartbeatData) {
    return {
      ...slotStatus,
      tone: 'pending',
      headline: 'Awaiting runtime slot check',
      detail: configStr
        ? `Mission config is staged for ${formatSlotValue(configStr)}.`
        : 'Mission config does not include a confirmed slot yet.',
      footnote: 'Heartbeat and auto-detect values appear after the drone reports live slot data.',
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
      footnote: 'Auto-detect is unavailable in the current runtime.',
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
      footnote: noAutoDetection ? 'Auto-detect is unavailable in the current runtime.' : '',
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
