import { getDroneReferenceNowMs } from './droneRuntimeStatus';

export const PX4_TAKEOFF_MODE = (2 << 24) | (4 << 16);

export function px4ArmingVerdict(drone, now, takeoff = false) {
  const report = takeoff ? drone?.px4_takeoff_arming_report : drone?.px4_arming_report;
  const expectedMode = takeoff ? PX4_TAKEOFF_MODE : drone?.flight_mode;
  if (drone?.is_armed === true || [2, 3, 4].includes(drone?.landed_state) || report?.source !== 'px4_events' || typeof report.can_arm !== 'boolean'
      || !Number.isInteger(expectedMode) || report.custom_mode !== expectedMode
      || typeof report.mode !== 'string' || !report.mode.trim()
      || !/^[0-9a-f]{24}$/.test(report.revision)
      || !Number.isInteger(report.expires_at_gcs_ms)
      || (Number.isInteger(report.expires_at_gcs_monotonic_ms)
        ? !(Number.isFinite(report.local_deadline_ms) && report.local_deadline_ms > performance.now())
        : report.expires_at_gcs_ms <= getDroneReferenceNowMs(drone, now))) return null;
  return { ...report, label: report.can_arm ? 'PX4 can arm' : 'PX4 cannot arm' };
}
