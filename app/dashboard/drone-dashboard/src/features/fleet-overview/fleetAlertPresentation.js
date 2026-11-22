import { FaExclamationCircle, FaExclamationTriangle } from 'react-icons/fa';

export const ALERT_LEVELS = [
  ['danger', 'Warning', FaExclamationCircle],
  ['warning', 'Caution', FaExclamationTriangle],
];

export function distinctAlertConditions(entries) {
  const distinct = new Map();
  entries.forEach((entry) => {
    const reason = typeof entry.reason === 'string' ? entry.reason.trim() : '';
    if (!reason) return;
    const key = JSON.stringify([entry.aircraftId, reason.replace(/\s+/g, ' ').toLowerCase()]);
    const previous = distinct.get(key);
    if (!previous || (entry.observed !== false && previous.observed === false)
      || ((entry.observed === false) === (previous.observed === false)
        && entry.tone === 'danger' && previous.tone !== 'danger')) {
      distinct.set(key, { ...entry, reason, displayKey: key });
    }
  });
  return [...distinct.values()].sort((a, b) => Number(b.tone === 'danger') - Number(a.tone === 'danger'));
}

export function alertScope(entries, selected) {
  return selected === 'all' ? entries : entries.filter((entry) => entry.tone === selected);
}
