// Presentation and query semantics for the operator log workspace.
export function logError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') return [detail.message || detail.error, detail.ulog_capability?.detail].filter(Boolean).join(' ') || 'Request unavailable.';
  return error?.message || 'Request unavailable.';
}

export function utcInput(value) {
  if (!value?.trim()) return null;
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?Z?$/);
  if (!match) throw new Error('Use UTC: YYYY-MM-DDTHH:mm:ssZ.');
  const [, year, month, day, hour, minute, second = '0', millis = '0'] = match;
  const date = new Date(Date.UTC(+year, +month - 1, +day, +hour, +minute, +second, Number(millis.padEnd(3, '0'))));
  if (date.getUTCFullYear() !== +year || date.getUTCMonth() !== +month - 1 || date.getUTCDate() !== +day
    || date.getUTCHours() !== +hour || date.getUTCMinutes() !== +minute || date.getUTCSeconds() !== +second) throw new Error('Enter a valid UTC date and time.');
  return date.toISOString();
}

export function historyQuery({ level, component, search, start, end }) {
  const since = utcInput(start), until = utcInput(end);
  if (since && until && since >= until) throw new Error('From UTC must be before To UTC.');
  return { level: level || undefined, component: component || undefined, search: search || undefined,
    since: since || undefined, until: until || undefined };
}

export function recordTime(value) {
  if (!value) return 'Unknown time';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toISOString().replace('T', ' ').replace('Z', ' UTC');
}

export function matchesLog(entry, search) {
  if (!search) return true;
  return [entry.msg, entry.component, entry.level, entry.source, entry.drone_id, JSON.stringify(entry.extra || {})]
    .filter(value => value != null).join(' ').toLowerCase().includes(search.toLowerCase());
}
