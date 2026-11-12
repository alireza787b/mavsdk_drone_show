/** Display hints never change the value sent back to PX4. */
export function formatParameterValue(value, row = {}, { exact = false } = {}) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value);
  if (exact || row.value_type === 'int') return String(value);
  const hint = row.decimal_places;
  const decimals = hint !== null && hint !== undefined && hint !== '' && Number.isInteger(Number(hint))
    ? Math.min(10, Math.max(0, Number(hint))) : 4;
  const rounded = value.toFixed(decimals).replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1').replace(/^-0$/, '0');
  return Number(rounded) === 0 && value !== 0 ? String(Number(value.toPrecision(4))) : rounded;
}

export function parseParameterValue(value, type) {
  const text = String(value ?? '').trim();
  if (type === 'custom') return String(value ?? '');
  const pattern = type === 'int' ? /^[+-]?\d+$/ : /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
  if (!pattern.test(text)) throw new Error(type === 'int' ? 'Enter a whole integer.' : 'Enter a finite number.');
  const number = Number(text);
  if (!Number.isFinite(number) || (type === 'int' && (!Number.isInteger(number) || number < -2147483648 || number > 2147483647))) {
    throw new Error(type === 'int' ? 'Enter a signed 32-bit integer.' : 'Enter a finite number.');
  }
  if (type === 'float' && (!Number.isFinite(Math.fround(number)) || (number !== 0 && Math.fround(number) === 0))) {
    throw new Error('Value is outside the nonzero 32-bit float range.');
  }
  return number;
}

/** Match the native parameter transport, never an arbitrary absolute epsilon. */
export function parameterValuesMatch(type, requested, actual) {
  if (type !== 'float') return requested === actual;
  if (typeof requested !== 'number' || typeof actual !== 'number') return false;
  const left = Math.fround(requested), right = Math.fround(actual);
  return Number.isFinite(left) && Number.isFinite(right)
    && !(requested !== 0 && left === 0) && !(actual !== 0 && right === 0) && left === right;
}

export function formatParameterRange(row) {
  const min = row.min_value != null, max = row.max_value != null;
  if (!min && !max) return 'Not declared';
  if (min && max) return `${formatParameterValue(row.min_value, row)} – ${formatParameterValue(row.max_value, row)}`;
  return `${min ? '≥' : '≤'} ${formatParameterValue(min ? row.min_value : row.max_value, row)}`;
}

export const parameterKey = row => `${row.component_id || 1}:${row.name}`;

export function parameterOutcome(result) {
  if (result?.outcome) return result.outcome;
  if (result?.verified === true) return 'verified';
  if (result?.applied === true) return 'written_unverified';
  if (result?.error) return 'failed';
  return 'unknown';
}

export const OUTCOME_LABELS = {
  verified: 'Verified', written_unverified: 'Written · unverified', verification_failed: 'Readback mismatch',
  failed: 'Failed', unknown: 'Outcome unconfirmed', not_attempted: 'Not attempted',
  pending: 'Pending', unchanged: 'Already matches', rejected: 'Rejected',
};

export function snapshotState(snapshot, now = Date.now()) {
  if (!snapshot?.created_at) return 'No snapshot';
  return snapshot.stale_after_ms && now - snapshot.created_at > snapshot.stale_after_ms ? 'Snapshot stale' : 'Snapshot current';
}

export function snapshotAge(snapshot, now = Date.now()) {
  if (!snapshot?.created_at) return 'Not fetched';
  const seconds = Math.max(0, Math.floor((now - snapshot.created_at) / 1000));
  return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`;
}
