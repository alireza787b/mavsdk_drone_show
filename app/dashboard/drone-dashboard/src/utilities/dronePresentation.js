import { FIELD_NAMES } from '../constants/fieldMappings';
import { getMissionConfigCustomFields, getPromotedMissionConfigField } from './missionConfigFields';

function readField(drone, key, fallback = '') {
  if (!drone || typeof drone !== 'object') {
    return fallback;
  }
  const value = drone[key];
  return value === undefined || value === null || value === '' ? fallback : String(value);
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

export function matchesDroneSearchQuery(drone, rawQuery) {
  const query = String(rawQuery || '').trim().toLowerCase();
  if (!query) {
    return true;
  }

  const identity = getDroneDisplayIdentity(drone);
  const customFieldTokens = getMissionConfigCustomFields(drone)
    .map((field) => `${field.label} ${field.displayValue}`.trim())
    .filter(Boolean);

  const haystack = [
    identity.primary,
    identity.secondary,
    identity.alias?.value,
    identity.posId,
    identity.hwId,
    ...customFieldTokens,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  return haystack.includes(query);
}
