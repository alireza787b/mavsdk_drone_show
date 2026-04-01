import { FIELD_NAMES } from '../constants/fieldMappings';
import { getMissionConfigCustomFields, getPromotedMissionConfigField } from './missionConfigFields';

export const DRONE_SEARCH_PLACEHOLDER = 'Search or use pos 1-5 / hw 2,4';
export const DRONE_SEARCH_HELP_TEXT = 'Try free text, pos 1-5, hw 2,4, or a callsign.';

function readField(drone, key, fallback = '') {
  if (!drone || typeof drone !== 'object') {
    return fallback;
  }
  const value = drone[key];
  return value === undefined || value === null || value === '' ? fallback : String(value);
}

function normalizeToken(value) {
  return String(value || '').trim().toLowerCase();
}

function toSearchTermList(values = []) {
  return values
    .flatMap((value) => {
      if (Array.isArray(value)) {
        return value;
      }
      return [value];
    })
    .map(normalizeToken)
    .filter(Boolean);
}

function isNumericToken(value) {
  return /^-?\d+$/.test(String(value || '').trim());
}

function matchesRangeToken(candidate, token) {
  const normalizedCandidate = normalizeToken(candidate);
  const normalizedToken = normalizeToken(token);

  if (!normalizedCandidate || !normalizedToken) {
    return false;
  }

  if (!normalizedToken.includes('-')) {
    return normalizedCandidate === normalizedToken;
  }

  const [startRaw, endRaw] = normalizedToken.split('-', 2);
  if (!isNumericToken(normalizedCandidate) || !isNumericToken(startRaw) || !isNumericToken(endRaw)) {
    return false;
  }

  const candidateValue = Number(normalizedCandidate);
  const lowerBound = Math.min(Number(startRaw), Number(endRaw));
  const upperBound = Math.max(Number(startRaw), Number(endRaw));
  return candidateValue >= lowerBound && candidateValue <= upperBound;
}

function buildDroneSearchSnapshot(drone, additionalTerms = []) {
  const identity = getDroneDisplayIdentity(drone);
  const customFieldTokens = getMissionConfigCustomFields(drone)
    .map((field) => `${field.label} ${field.displayValue}`.trim())
    .filter(Boolean);

  const haystackTerms = toSearchTermList([
    identity.primary,
    identity.secondary,
    identity.alias?.label,
    identity.alias?.value,
    identity.posId,
    identity.hwId,
    ...customFieldTokens,
    ...additionalTerms,
  ]);

  return {
    haystackTerms,
    posId: normalizeToken(identity.posId),
    hwId: normalizeToken(identity.hwId),
    alias: normalizeToken(identity.alias?.value),
  };
}

function parseStructuredDroneQuery(rawQuery) {
  const query = String(rawQuery || '').trim();
  if (!query) {
    return {
      filters: [],
      plainTerms: [],
    };
  }

  const filters = [];
  const consumed = [];
  const pattern = /\b(pos(?:ition)?|slot|hw|hardware|id|alias|callsign)\s*:?\s*([^\s]+)/gi;
  let match;

  while ((match = pattern.exec(query)) !== null) {
    const keyword = normalizeToken(match[1]);
    const value = normalizeToken(match[2]);

    if (!value) {
      continue;
    }

    let field = null;
    if (keyword === 'pos' || keyword === 'position' || keyword === 'slot') {
      field = 'pos';
    } else if (keyword === 'hw' || keyword === 'hardware') {
      field = 'hw';
    } else if (keyword === 'id') {
      field = 'id';
    } else if (keyword === 'alias' || keyword === 'callsign') {
      field = 'alias';
    }

    if (!field) {
      continue;
    }

    filters.push({
      field,
      values: value.split(',').map(normalizeToken).filter(Boolean),
    });
    consumed.push(match[0]);
  }

  const plainQuery = consumed.reduce(
    (result, segment) => result.replace(segment, ' '),
    query,
  );

  return {
    filters,
    plainTerms: plainQuery
      .split(/\s+/)
      .map(normalizeToken)
      .filter(Boolean),
  };
}

function matchesStructuredFilter(snapshot, filter) {
  if (!filter?.values?.length) {
    return true;
  }

  if (filter.field === 'pos') {
    return filter.values.some((value) => matchesRangeToken(snapshot.posId, value));
  }

  if (filter.field === 'hw') {
    return filter.values.some((value) => matchesRangeToken(snapshot.hwId, value));
  }

  if (filter.field === 'id') {
    return filter.values.some((value) => (
      matchesRangeToken(snapshot.posId, value) || matchesRangeToken(snapshot.hwId, value)
    ));
  }

  if (filter.field === 'alias') {
    return filter.values.some((value) => (
      snapshot.alias.includes(value)
      || snapshot.haystackTerms.some((term) => term.includes(value))
    ));
  }

  return true;
}

export function getDroneOperatorAlias(drone) {
  const promotedField = getPromotedMissionConfigField(drone);
  if (!promotedField?.displayValue || promotedField.displayValue === 'Not set') {
    return null;
  }

  return {
    label: promotedField.label,
    value: promotedField.displayValue,
  };
}

export function getDroneDisplayIdentity(drone) {
  const posId = readField(drone, FIELD_NAMES.POS_ID);
  const hwId = readField(drone, FIELD_NAMES.HW_ID) || readField(drone, 'hw_ID');
  const alias = getDroneOperatorAlias(drone);

  if (posId && hwId) {
    return {
      primary: `Pos ${posId} · HW ${hwId}`,
      secondary: alias ? `${alias.label}: ${alias.value}` : '',
      alias,
      posId,
      hwId,
    };
  }

  if (posId) {
    return {
      primary: `Pos ${posId}`,
      secondary: alias ? `${alias.label}: ${alias.value}` : '',
      alias,
      posId,
      hwId: '',
    };
  }

  return {
    primary: hwId ? `HW ${hwId}` : 'Unassigned drone',
    secondary: alias ? `${alias.label}: ${alias.value}` : '',
    alias,
    posId: '',
    hwId,
  };
}

export function matchesDroneSearchQuery(drone, rawQuery, additionalTerms = []) {
  const query = String(rawQuery || '').trim();
  if (!query) {
    return true;
  }

  const snapshot = buildDroneSearchSnapshot(drone, additionalTerms);
  const parsedQuery = parseStructuredDroneQuery(query);
  const matchesFilters = parsedQuery.filters.every((filter) => matchesStructuredFilter(snapshot, filter));
  if (!matchesFilters) {
    return false;
  }

  if (parsedQuery.plainTerms.length === 0) {
    return true;
  }

  return parsedQuery.plainTerms.every((term) => (
    snapshot.haystackTerms.some((haystackTerm) => haystackTerm.includes(term))
  ));
}
