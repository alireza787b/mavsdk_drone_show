const INTEGER_PATTERN = /^\d+$/;
const POSITIVE_INTEGER_PATTERN = /^[1-9]\d*$/;

function toTrimmedString(value, fallback = '') {
  if (value === undefined || value === null) {
    return fallback;
  }

  return String(value).trim();
}

export function normalizeComparableId(value, fallback = '') {
  const trimmed = toTrimmedString(value, fallback);
  if (!trimmed) {
    return fallback;
  }

  if (!INTEGER_PATTERN.test(trimmed)) {
    return trimmed;
  }

  return String(Number.parseInt(trimmed, 10));
}

export function formatDroneLabel(value, fallback = 'Drone') {
  const normalized = normalizeComparableId(value);
  return normalized ? `Drone ${normalized}` : fallback;
}

export function formatShowSlotLabel(value, fallback = 'Show Slot') {
  const normalized = normalizeComparableId(value);
  return normalized ? `Show Slot ${normalized}` : fallback;
}

export function formatCompactDroneIdentity(posValue, hwValue, fallback = 'Unassigned') {
  const posId = normalizeComparableId(posValue);
  const hwId = normalizeComparableId(hwValue);

  if (posId && hwId) {
    return `P${posId}|H${hwId}`;
  }

  if (posId) {
    return `P${posId}`;
  }

  if (hwId) {
    return `H${hwId}`;
  }

  return fallback;
}

export function normalizeRuntimeIp(value) {
  const normalized = toTrimmedString(value);
  if (!normalized) {
    return '';
  }

  const lowered = normalized.toLowerCase();
  if (['unknown', 'n/a', 'none', 'null'].includes(lowered)) {
    return '';
  }

  return normalized;
}

export function areGitRevisionsEquivalent(leftValue, rightValue) {
  const left = toTrimmedString(leftValue).toLowerCase();
  const right = toTrimmedString(rightValue).toLowerCase();

  if (!left || !right) {
    return false;
  }

  if (left === right) {
    return true;
  }

  const shorter = left.length <= right.length ? left : right;
  const longer = left.length <= right.length ? right : left;
  return shorter.length >= 7 && longer.startsWith(shorter);
}

export function isPositiveIntegerId(value) {
  return POSITIVE_INTEGER_PATTERN.test(normalizeComparableId(value));
}

export function compareMissionIds(leftValue, rightValue) {
  const left = normalizeComparableId(leftValue);
  const right = normalizeComparableId(rightValue);
  const leftNumeric = POSITIVE_INTEGER_PATTERN.test(left);
  const rightNumeric = POSITIVE_INTEGER_PATTERN.test(right);

  if (leftNumeric && rightNumeric) {
    return Number.parseInt(left, 10) - Number.parseInt(right, 10);
  }

  if (leftNumeric) {
    return -1;
  }

  if (rightNumeric) {
    return 1;
  }

  return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' });
}

export function sortMissionIds(values = []) {
  return Array.from(
    new Set(
      values
        .map((value) => normalizeComparableId(value))
        .filter(Boolean)
    )
  ).sort(compareMissionIds);
}

export function normalizeDroneConfigEntry(entry = {}) {
  const hwId = normalizeComparableId(entry.hw_id);
  if (!hwId) {
    return null;
  }

  const posId = normalizeComparableId(entry.pos_id, hwId) || hwId;

  return {
    ...entry,
    hw_id: hwId,
    pos_id: posId,
    ip: toTrimmedString(entry.ip),
    mavlink_port: toTrimmedString(entry.mavlink_port),
    serial_port: entry.serial_port === undefined || entry.serial_port === null
      ? ''
      : String(entry.serial_port),
    baudrate: entry.baudrate === undefined || entry.baudrate === null
      ? ''
      : String(entry.baudrate),
  };
}

export function normalizeDroneConfigData(entries = []) {
  if (!Array.isArray(entries)) {
    return [];
  }

  return entries
    .map((entry) => normalizeDroneConfigEntry(entry))
    .filter(Boolean);
}

export function buildSuggestedHwIds(configData = []) {
  const usedIds = new Set(
    configData
      .map((drone) => normalizeComparableId(drone.hw_id))
      .filter((id) => POSITIVE_INTEGER_PATTERN.test(id))
  );

  const numericIds = Array.from(usedIds, (id) => Number.parseInt(id, 10));
  const maxId = numericIds.length > 0 ? Math.max(...numericIds) : 0;
  const suggestions = [];

  for (let candidate = 1; candidate <= maxId + 1; candidate += 1) {
    const candidateId = String(candidate);
    if (!usedIds.has(candidateId)) {
      suggestions.push(candidateId);
    }
  }

  return suggestions.length > 0 ? suggestions : ['1'];
}

export function buildKnownPositionIds(configData = [], extraIds = []) {
  return sortMissionIds([
    ...configData.map((drone) => drone.pos_id),
    ...extraIds,
  ]);
}

export function findDuplicatePositionAssignment(configData = [], currentHwId, candidatePosId) {
  const normalizedHwId = normalizeComparableId(currentHwId);
  const normalizedPosId = normalizeComparableId(candidatePosId);

  if (!normalizedPosId) {
    return null;
  }

  return (
    configData.find((drone) => (
      normalizeComparableId(drone.pos_id) === normalizedPosId &&
      normalizeComparableId(drone.hw_id) !== normalizedHwId
    )) || null
  );
}

export function getDuplicateAssignments(configData = []) {
  const duplicateHwLookup = new Map();
  const duplicatePosLookup = new Map();

  configData.forEach((drone) => {
    const hwId = normalizeComparableId(drone.hw_id);
    const posId = normalizeComparableId(drone.pos_id, hwId);

    if (hwId) {
      const hwEntry = duplicateHwLookup.get(hwId) || [];
      hwEntry.push(posId || hwId);
      duplicateHwLookup.set(hwId, hwEntry);
    }

    if (posId) {
      const posEntry = duplicatePosLookup.get(posId) || [];
      posEntry.push(hwId);
      duplicatePosLookup.set(posId, posEntry);
    }
  });

  return {
    duplicateHwIds: Array.from(duplicateHwLookup.entries())
      .filter(([, posIds]) => posIds.length > 1)
      .map(([hw_id, pos_ids]) => ({ hw_id, pos_ids: sortMissionIds(pos_ids) }))
      .sort((left, right) => compareMissionIds(left.hw_id, right.hw_id)),
    duplicatePosIds: Array.from(duplicatePosLookup.entries())
      .filter(([, hwIds]) => hwIds.length > 1)
      .map(([pos_id, hw_ids]) => ({ pos_id, hw_ids: sortMissionIds(hw_ids) }))
      .sort((left, right) => compareMissionIds(left.pos_id, right.pos_id)),
  };
}

export function getRoleSwaps(configData = []) {
  return configData
    .map((drone) => normalizeDroneConfigEntry(drone))
    .filter(Boolean)
    .filter((drone) => drone.hw_id !== drone.pos_id)
    .sort((left, right) => compareMissionIds(left.hw_id, right.hw_id));
}

export function getHeartbeatTimestamp(heartbeat) {
  const timestamp = heartbeat?.last_heartbeat ?? heartbeat?.timestamp;
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function getOnlineDroneCount(heartbeats = {}, staleThresholdSeconds = 20) {
  const now = Date.now();

  return Object.values(heartbeats).filter((heartbeat) => {
    const timestamp = getHeartbeatTimestamp(heartbeat);
    if (timestamp === null) {
      return false;
    }

    return Math.floor((now - timestamp) / 1000) < staleThresholdSeconds;
  }).length;
}

export function buildPendingEnrollmentCandidates(
  configData = [],
  heartbeats = {},
  onlineThresholdSeconds = 20,
  offlineThresholdSeconds = 60,
) {
  const now = Date.now();
  const configuredHwIds = new Set(
    normalizeDroneConfigData(configData)
      .map((drone) => normalizeComparableId(drone.hw_id))
      .filter(Boolean)
  );

  return Object.entries(heartbeats)
    .map(([fallbackHwId, heartbeat]) => {
      const hwId = normalizeComparableId(heartbeat?.hw_id ?? fallbackHwId);
      if (!hwId || configuredHwIds.has(hwId)) {
        return null;
      }

      const timestamp = getHeartbeatTimestamp(heartbeat);
      const heartbeatAgeSec = timestamp === null
        ? null
        : Math.floor((now - timestamp) / 1000);

      let heartbeatStatus = 'Unknown';
      let heartbeatTone = 'neutral';
      if (heartbeatAgeSec !== null) {
        if (heartbeatAgeSec < onlineThresholdSeconds) {
          heartbeatStatus = 'Online';
          heartbeatTone = 'good';
        } else if (heartbeatAgeSec < offlineThresholdSeconds) {
          heartbeatStatus = 'Stale';
          heartbeatTone = 'warning';
        } else {
          heartbeatStatus = 'Offline';
          heartbeatTone = 'danger';
        }
      }

      return {
        hw_id: hwId,
        pos_id: normalizeComparableId(heartbeat?.pos_id),
        detected_pos_id: normalizeComparableId(heartbeat?.detected_pos_id),
        ip: normalizeRuntimeIp(heartbeat?.ip),
        mavlink_port: toTrimmedString(heartbeat?.mavlink_port),
        heartbeatAgeSec,
        heartbeatStatus,
        heartbeatTone,
      };
    })
    .filter(Boolean)
    .sort((left, right) => compareMissionIds(left.hw_id, right.hw_id));
}

export function toBackendConfigDrone(drone = {}) {
  const normalized = normalizeDroneConfigEntry(drone);
  if (!normalized) {
    return null;
  }

  const coerceInteger = (value) => {
    const comparable = normalizeComparableId(value);
    if (INTEGER_PATTERN.test(comparable)) {
      return Number.parseInt(comparable, 10);
    }
    return value;
  };

  return {
    ...normalized,
    hw_id: coerceInteger(normalized.hw_id),
    pos_id: coerceInteger(normalized.pos_id),
    mavlink_port: coerceInteger(normalized.mavlink_port),
    baudrate: coerceInteger(normalized.baudrate),
  };
}
