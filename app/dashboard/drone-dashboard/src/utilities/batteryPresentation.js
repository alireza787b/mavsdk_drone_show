import { FIELD_NAMES } from '../constants/fieldMappings';

const CHARGE_STATES = {
  0: { className: '', tone: 'muted', label: 'State unavailable' },
  1: { className: 'good', tone: 'good', label: 'OK' },
  2: { className: 'warning', tone: 'warning', label: 'Low' },
  3: { className: 'critical', tone: 'danger', label: 'Critical' },
  4: { className: 'critical', tone: 'danger', label: 'Emergency' },
  5: { className: 'critical', tone: 'danger', label: 'Failed' },
  6: { className: 'critical', tone: 'danger', label: 'Unhealthy' },
  7: { className: 'good', tone: 'good', label: 'Charging' },
};

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

/** Present battery evidence without guessing chemistry or cell count. */
export function getBatteryPresentation(drone = {}) {
  const voltage = finiteNumber(drone[FIELD_NAMES.BATTERY_VOLTAGE]);
  const rawRemaining = finiteNumber(drone[FIELD_NAMES.BATTERY_REMAINING_PERCENT]);
  const remaining = rawRemaining !== null && rawRemaining >= 0 && rawRemaining <= 100
    ? rawRemaining
    : null;
  const chargeState = finiteNumber(drone[FIELD_NAMES.BATTERY_CHARGE_STATE]);
  const faultBitmask = finiteNumber(drone[FIELD_NAMES.BATTERY_FAULT_BITMASK]);
  const ageMs = finiteNumber(drone[FIELD_NAMES.BATTERY_AGE_MS]);

  let status = CHARGE_STATES[chargeState] || CHARGE_STATES[0];
  if (faultBitmask !== null && faultBitmask !== 0) {
    status = {
      className: 'critical',
      tone: 'danger',
      label: `Fault 0x${Math.trunc(faultBitmask).toString(16).toUpperCase()}`,
    };
  }

  const parts = [];
  if (remaining !== null) parts.push(`${Math.round(remaining)}%`);
  if (voltage !== null && voltage > 0) parts.push(`${voltage.toFixed(1)}V`);
  const text = parts.length > 0 ? parts.join(' · ') : 'N/A';
  const ageText = ageMs !== null ? `${(Math.max(0, ageMs) / 1000).toFixed(1)}s old` : 'age unavailable';
  const help = remaining !== null
    ? `Autopilot state of charge; ${status.label}; sample ${ageText}. Voltage is informational and is not used to infer pack capacity.`
    : `State of charge unavailable; ${status.label}; sample ${ageText}. Voltage alone is not used to infer pack capacity.`;

  return {
    class: status.className,
    tone: status.tone,
    label: status.label,
    text,
    help,
    remaining,
    voltage,
    chargeState,
    faultBitmask,
    ageMs,
  };
}
