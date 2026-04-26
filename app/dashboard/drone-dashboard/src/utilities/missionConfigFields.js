import {
  normalizeComparableId,
  normalizeDroneConfigEntry,
} from './missionIdentityUtils';

export const CORE_IDENTITY_FIELDS = ['hw_id', 'pos_id'];
export const CORE_CONNECTIVITY_FIELDS = ['ip', 'mavlink_port', 'serial_port', 'baudrate'];
export const CORE_MISSION_CONFIG_FIELDS = [
  ...CORE_IDENTITY_FIELDS,
  ...CORE_CONNECTIVITY_FIELDS,
];

export const TRANSIENT_MISSION_CONFIG_FIELDS = [
  'isNew',
  'x',
  'y',
  'custom_fields',
];

export const RESERVED_MISSION_CONFIG_FIELDS = new Set([
  ...CORE_MISSION_CONFIG_FIELDS,
  ...TRANSIENT_MISSION_CONFIG_FIELDS,
]);

export const CUSTOM_FIELD_TYPES = {
  TEXT: 'text',
  NUMBER: 'number',
  BOOLEAN: 'boolean',
  JSON: 'json',
  COLOR: 'color',
};

export const CUSTOM_FIELD_TYPE_OPTIONS = [
  { value: CUSTOM_FIELD_TYPES.TEXT, label: 'Text' },
  { value: CUSTOM_FIELD_TYPES.NUMBER, label: 'Number' },
  { value: CUSTOM_FIELD_TYPES.BOOLEAN, label: 'Boolean' },
  { value: CUSTOM_FIELD_TYPES.JSON, label: 'JSON' },
  { value: CUSTOM_FIELD_TYPES.COLOR, label: 'Color' },
];

const FIELD_LABEL_OVERRIDES = {
  hw_id: 'Hardware ID',
  pos_id: 'Position ID',
  ip: 'IP Address',
  mavlink_port: 'MAVLink Port',
  serial_port: 'Serial Port',
  baudrate: 'Baudrate',
  callsign: 'Callsign',
  display_name: 'Display Name',
  nickname: 'Nickname',
  marker_color: 'Marker Color',
  role_hint: 'Role Hint',
};

const PROMOTED_CUSTOM_FIELD_KEYS = ['callsign', 'display_name', 'nickname', 'name', 'alias'];
const CUSTOM_FIELD_KEY_PATTERN = /^[a-z][a-z0-9_]*$/;
const HEX_COLOR_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const ACRONYM_WORDS = new Set(['id', 'ip', 'gps', 'gcs', 'mavlink', 'rtl', 'udp', 'tcp']);

export const DEFAULT_MARKER_COLOR = '#00d4ff';

export const MISSION_CUSTOM_FIELD_TEMPLATES = [
  {
    key: 'callsign',
    label: 'Callsign',
    type: CUSTOM_FIELD_TYPES.TEXT,
    defaultValue: '',
    placeholder: 'VIPER-01',
    description: 'Operator alias shown on cards, maps, and reports without changing hardware or show slot IDs.',
  },
  {
    key: 'marker_color',
    label: 'Marker Color',
    type: CUSTOM_FIELD_TYPES.COLOR,
    defaultValue: DEFAULT_MARKER_COLOR,
    placeholder: DEFAULT_MARKER_COLOR,
    description: 'Optional map/globe marker color. Use #RGB or #RRGGBB.',
  },
  {
    key: 'notes',
    label: 'Notes',
    type: CUSTOM_FIELD_TYPES.TEXT,
    defaultValue: '',
    placeholder: 'Battery swapped, payload note, or test context',
    description: 'Short operator note preserved in config JSON.',
  },
  {
    key: 'role_hint',
    label: 'Role Hint',
    type: CUSTOM_FIELD_TYPES.TEXT,
    defaultValue: '',
    placeholder: 'leader, follower, scout, spare',
    description: 'Human-readable planning hint only; it does not override mission or swarm logic.',
  },
];

export const CUSTOM_FIELD_TEMPLATE_OPTIONS = [
  ...MISSION_CUSTOM_FIELD_TEMPLATES.map((template) => ({
    value: template.key,
    label: template.label,
  })),
  { value: '__custom__', label: 'Custom field' },
];

let customFieldDraftCounter = 0;

function nextCustomFieldDraftId() {
  customFieldDraftCounter += 1;
  return `custom-field-${customFieldDraftCounter}`;
}

export function humanizeMissionConfigFieldKey(key) {
  if (!key) {
    return 'Field';
  }

  const normalizedKey = String(key).trim();
  if (!normalizedKey) {
    return 'Field';
  }

  if (FIELD_LABEL_OVERRIDES[normalizedKey]) {
    return FIELD_LABEL_OVERRIDES[normalizedKey];
  }

  const expanded = normalizedKey
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim();

  return expanded
    .split(/\s+/)
    .map((word) => {
      const lowered = word.toLowerCase();
      if (ACRONYM_WORDS.has(lowered)) {
        return lowered.toUpperCase();
      }
      return lowered.charAt(0).toUpperCase() + lowered.slice(1);
    })
    .join(' ');
}

export function normalizeMissionCustomFieldKey(value) {
  return String(value || '')
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^a-zA-Z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
}

export function getMissionCustomFieldTemplate(key) {
  const normalizedKey = normalizeMissionCustomFieldKey(key);
  return MISSION_CUSTOM_FIELD_TEMPLATES.find((template) => template.key === normalizedKey) || null;
}

export function inferMissionCustomFieldType(value, key = '') {
  const template = getMissionCustomFieldTemplate(key);
  if (template) {
    return template.type;
  }

  if (typeof value === 'boolean') {
    return CUSTOM_FIELD_TYPES.BOOLEAN;
  }

  if (typeof value === 'number' && Number.isFinite(value)) {
    return CUSTOM_FIELD_TYPES.NUMBER;
  }

  if (value !== null && typeof value === 'object') {
    return CUSTOM_FIELD_TYPES.JSON;
  }

  return CUSTOM_FIELD_TYPES.TEXT;
}

export function isReservedMissionConfigField(key) {
  return RESERVED_MISSION_CONFIG_FIELDS.has(normalizeMissionCustomFieldKey(key));
}

export function formatMissionCustomFieldValue(value, type = inferMissionCustomFieldType(value)) {
  if (type === CUSTOM_FIELD_TYPES.BOOLEAN) {
    return value ? 'True' : 'False';
  }

  if (type === CUSTOM_FIELD_TYPES.NUMBER) {
    return String(value);
  }

  if (type === CUSTOM_FIELD_TYPES.COLOR) {
    return String(value || '').trim() || 'Not set';
  }

  if (type === CUSTOM_FIELD_TYPES.JSON) {
    if (Array.isArray(value)) {
      return `Array (${value.length})`;
    }
    if (value && typeof value === 'object') {
      return `Object (${Object.keys(value).length} keys)`;
    }
  }

  const text = value === undefined || value === null ? '' : String(value).trim();
  return text || 'Not set';
}

function getPromotedFieldPriority(key) {
  const normalized = normalizeMissionCustomFieldKey(key);
  const index = PROMOTED_CUSTOM_FIELD_KEYS.indexOf(normalized);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

export function getMissionConfigCustomFields(drone = {}) {
  if (!drone || typeof drone !== 'object') {
    return [];
  }

  return Object.entries(drone)
    .filter(([key]) => !RESERVED_MISSION_CONFIG_FIELDS.has(key))
    .map(([key, value]) => {
      const type = inferMissionCustomFieldType(value, key);
      const template = getMissionCustomFieldTemplate(key);
      return {
        key,
        label: template?.label || humanizeMissionConfigFieldKey(key),
        type,
        value,
        displayValue: formatMissionCustomFieldValue(value, type),
        description: template?.description || null,
        isTemplate: Boolean(template),
        isPromoted: getPromotedFieldPriority(key) !== Number.MAX_SAFE_INTEGER,
      };
    })
    .sort((left, right) => {
      const leftPriority = getPromotedFieldPriority(left.key);
      const rightPriority = getPromotedFieldPriority(right.key);
      if (leftPriority !== rightPriority) {
        return leftPriority - rightPriority;
      }
      return left.label.localeCompare(right.label, undefined, {
        numeric: true,
        sensitivity: 'base',
      });
    });
}

export function getPromotedMissionConfigField(drone = {}) {
  return getMissionConfigCustomFields(drone).find((field) => field.isPromoted) || null;
}

export function createMissionCustomFieldDraft(overrides = {}) {
  return {
    id: nextCustomFieldDraftId(),
    key: '',
    type: CUSTOM_FIELD_TYPES.TEXT,
    value: '',
    ...overrides,
  };
}

export function createMissionCustomFieldDraftFromTemplate(templateKey, overrides = {}) {
  const template = getMissionCustomFieldTemplate(templateKey);
  if (!template) {
    return createMissionCustomFieldDraft(overrides);
  }

  return createMissionCustomFieldDraft({
    key: template.key,
    type: template.type,
    value: template.defaultValue,
    ...overrides,
  });
}

export function coerceMissionCustomFieldValueForEditor(type, value) {
  if (type === CUSTOM_FIELD_TYPES.BOOLEAN) {
    if (typeof value === 'boolean') {
      return value;
    }
    return String(value).toLowerCase() === 'true';
  }

  if (type === CUSTOM_FIELD_TYPES.NUMBER) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return String(value);
    }
    const candidate = String(value ?? '').trim();
    return candidate;
  }

  if (type === CUSTOM_FIELD_TYPES.COLOR) {
    return String(value ?? '').trim() || DEFAULT_MARKER_COLOR;
  }

  if (type === CUSTOM_FIELD_TYPES.JSON) {
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) {
        return '{}';
      }
      try {
        JSON.parse(trimmed);
        return trimmed;
      } catch {
        return JSON.stringify(value);
      }
    }
    return JSON.stringify(value ?? {}, null, 2);
  }

  return value === undefined || value === null ? '' : String(value);
}

export function buildMissionConfigFormState(drone = {}) {
  const normalized = normalizeDroneConfigEntry(drone) || {
    hw_id: '',
    pos_id: '',
    ip: '',
    mavlink_port: '',
    serial_port: '',
    baudrate: '0',
  };

  return {
    hw_id: normalizeComparableId(normalized.hw_id),
    pos_id: normalizeComparableId(normalized.pos_id, normalized.hw_id),
    ip: normalized.ip || '',
    mavlink_port:
      normalized.mavlink_port !== undefined && normalized.mavlink_port !== null
        ? String(normalized.mavlink_port)
        : '',
    serial_port: normalized.serial_port ?? '',
    baudrate:
      normalized.baudrate !== undefined && normalized.baudrate !== null
        ? String(normalized.baudrate)
        : '0',
    isNew: Boolean(drone.isNew),
    custom_fields: getMissionConfigCustomFields(drone).map((field) =>
      createMissionCustomFieldDraft({
        key: field.key,
        type: field.type,
        value: coerceMissionCustomFieldValueForEditor(field.type, field.value),
      })
    ),
  };
}

function parseMissionCustomFieldDraftValue(field) {
  switch (field.type) {
    case CUSTOM_FIELD_TYPES.NUMBER:
      return Number(field.value);
    case CUSTOM_FIELD_TYPES.BOOLEAN:
      return field.value === true || String(field.value).toLowerCase() === 'true';
    case CUSTOM_FIELD_TYPES.JSON:
      return JSON.parse(String(field.value || '{}'));
    case CUSTOM_FIELD_TYPES.COLOR:
      return String(field.value ?? '').trim();
    default:
      return String(field.value ?? '');
  }
}

export function serializeMissionConfigFormState(formState = {}) {
  const serialized = {
    hw_id: formState.hw_id,
    pos_id: formState.pos_id,
    ip: formState.ip,
    mavlink_port: formState.mavlink_port,
    serial_port: formState.serial_port,
    baudrate: formState.baudrate,
    isNew: Boolean(formState.isNew),
  };

  const customFields = Array.isArray(formState.custom_fields) ? formState.custom_fields : [];

  customFields.forEach((field) => {
    const normalizedKey = normalizeMissionCustomFieldKey(field.key);
    if (!normalizedKey) {
      return;
    }
    serialized[normalizedKey] = parseMissionCustomFieldDraftValue(field);
  });

  return serialized;
}

export function validateMissionCustomFields(customFields = []) {
  const errorsById = {};
  const keyOwners = new Map();

  customFields.forEach((field) => {
    const fieldErrors = {};
    const rawKey = String(field.key || '').trim();
    const normalizedKey = normalizeMissionCustomFieldKey(rawKey);

    if (!rawKey) {
      fieldErrors.key = 'Field name is required.';
    } else if (!CUSTOM_FIELD_KEY_PATTERN.test(normalizedKey)) {
      fieldErrors.key = 'Use lowercase snake_case starting with a letter.';
    } else if (isReservedMissionConfigField(normalizedKey)) {
      fieldErrors.key = 'That field name is reserved by the system.';
    } else if (keyOwners.has(normalizedKey)) {
      fieldErrors.key = 'Each additional field name must be unique.';
      const existingOwnerId = keyOwners.get(normalizedKey);
      errorsById[existingOwnerId] = {
        ...(errorsById[existingOwnerId] || {}),
        key: 'Each additional field name must be unique.',
      };
    } else {
      keyOwners.set(normalizedKey, field.id);
    }

    if (field.type === CUSTOM_FIELD_TYPES.NUMBER) {
      const candidate = String(field.value ?? '').trim();
      if (!candidate) {
        fieldErrors.value = 'Enter a number.';
      } else if (!Number.isFinite(Number(candidate))) {
        fieldErrors.value = 'Number value is invalid.';
      }
    }

    if (field.type === CUSTOM_FIELD_TYPES.COLOR || normalizedKey === 'marker_color') {
      const candidate = String(field.value ?? '').trim();
      if (!candidate) {
        fieldErrors.value = 'Enter a marker color.';
      } else if (!HEX_COLOR_PATTERN.test(candidate)) {
        fieldErrors.value = 'Use #RGB or #RRGGBB.';
      }
    }

    if (field.type === CUSTOM_FIELD_TYPES.JSON) {
      try {
        JSON.parse(String(field.value || '{}'));
      } catch {
        fieldErrors.value = 'JSON value is invalid.';
      }
    }

    if (Object.keys(fieldErrors).length > 0) {
      errorsById[field.id] = fieldErrors;
    }
  });

  return {
    isValid: Object.keys(errorsById).length === 0,
    errorsById,
  };
}
