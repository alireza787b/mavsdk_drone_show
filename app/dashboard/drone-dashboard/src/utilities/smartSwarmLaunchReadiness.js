import { FIELD_NAMES } from '../constants/fieldMappings';
import { getDroneDisplayIdentity } from './dronePresentation';
import { getDroneRuntimeStatus } from './droneRuntimeStatus';
import { toFiniteTelemetryNumber } from './telemetryAltitude';

// Keep the UI preview aligned with AIRBORNE_MIN_RELATIVE_ALTITUDE_M in
// src/action_safety.py. The node repeats this check from authoritative MAVSDK
// streams immediately before Smart Swarm begins.
export const SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M = 0.5;

function normalizeId(value) {
  return String(value ?? '').trim();
}

function resolveHomeRelativeAltitude(drone) {
  const report = drone?.[FIELD_NAMES.ALTITUDE_REPORT];
  if (!report || typeof report !== 'object') {
    return null;
  }
  const source = String(report.source || 'unavailable');
  if (source !== 'relative_home' || report.stale === true) {
    return null;
  }
  return toFiniteTelemetryNumber(report.relative_home_m ?? report.display_m);
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
  const unavailableDrones = [];
  let airborneCount = 0;

  targetDrones.forEach((drone) => {
    const runtimeStatus = getDroneRuntimeStatus(drone, referenceNowMs);
    const altitudeM = resolveHomeRelativeAltitude(drone);
    const isArmed = Boolean(drone?.[FIELD_NAMES.IS_ARMED]);
    const isAirborne = isArmed && altitudeM !== null && altitudeM >= minAirborneAltitudeM;

    if (runtimeStatus.level === 'offline' || runtimeStatus.level === 'unknown') {
      const identity = getDroneDisplayIdentity(drone);
      unavailableDrones.push({
        hwId: normalizeId(drone?.[FIELD_NAMES.HW_ID]),
        label: identity.primary,
        runtimeLabel: runtimeStatus.label,
      });
      return;
    }

    if (isAirborne) {
      airborneCount += 1;
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
    unavailableDrones,
    unavailableIds: unavailableDrones.map((drone) => drone.hwId),
    minAirborneAltitudeM,
  };
}
