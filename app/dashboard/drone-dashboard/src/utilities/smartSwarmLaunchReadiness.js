import { FIELD_NAMES } from '../constants/fieldMappings';
import { getDroneDisplayIdentity } from './dronePresentation';
import { getDroneRuntimeStatus } from './droneRuntimeStatus';

export const SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M = 0.3;

function normalizeId(value) {
  return String(value ?? '').trim();
}

function isFiniteNumber(value) {
  return Number.isFinite(Number(value));
}

function buildScopedTargets({ drones = [], targetMode = 'all', selectedDrones = [], targetDroneIds = [] }) {
  if (targetMode === 'all') {
    return drones;
  }

  const scopedIds = new Set(
    (targetMode === 'selected' ? selectedDrones : targetDroneIds)
      .map((value) => normalizeId(value))
      .filter(Boolean),
  );

  return drones.filter((drone) => scopedIds.has(normalizeId(drone?.[FIELD_NAMES.HW_ID])));
}

export function buildSmartSwarmLaunchReadiness({
  drones = [],
  targetMode = 'all',
  selectedDrones = [],
  targetDroneIds = [],
  referenceNowMs = Date.now(),
  minAirborneAltitudeM = SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M,
} = {}) {
  const targetDrones = buildScopedTargets({
    drones,
    targetMode,
    selectedDrones,
    targetDroneIds,
  });

  const groundedDrones = [];
  let airborneCount = 0;

  targetDrones.forEach((drone) => {
    const runtimeStatus = getDroneRuntimeStatus(drone, referenceNowMs);
    const altitude = Number(drone?.[FIELD_NAMES.POSITION_ALT]);
    const altitudeM = isFiniteNumber(altitude) ? altitude : null;
    const isArmed = Boolean(drone?.[FIELD_NAMES.IS_ARMED]);
    const isAirborne = isArmed && altitudeM !== null && altitudeM > minAirborneAltitudeM;

    if (isAirborne) {
      airborneCount += 1;
      return;
    }

    if (runtimeStatus.level === 'offline' || runtimeStatus.level === 'unknown') {
      return;
    }

    const identity = getDroneDisplayIdentity(drone);
    groundedDrones.push({
      hwId: normalizeId(drone?.[FIELD_NAMES.HW_ID]),
      label: identity.primary,
      altitudeM,
      isArmed,
      runtimeLabel: runtimeStatus.label,
    });
  });

  return {
    targetCount: targetDrones.length,
    airborneCount,
    groundedDrones,
    groundedIds: groundedDrones.map((drone) => drone.hwId),
    minAirborneAltitudeM,
  };
}
