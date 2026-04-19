import {
  buildMissionConfigFormState,
  createMissionCustomFieldDraftFromTemplate,
  CUSTOM_FIELD_TEMPLATE_OPTIONS,
  CUSTOM_FIELD_TYPES,
  getMissionConfigCustomFields,
  getMissionCustomFieldTemplate,
  getPromotedMissionConfigField,
  normalizeMissionCustomFieldKey,
  serializeMissionConfigFormState,
  validateMissionCustomFields,
} from './missionConfigFields';

describe('missionConfigFields', () => {
  test('extracts and sorts additional fields separately from core mission fields', () => {
    const fields = getMissionConfigCustomFields({
      hw_id: '1',
      pos_id: '2',
      ip: '10.0.0.1',
      mavlink_port: '14550',
      serial_port: '',
      baudrate: '0',
      notes: 'Battery swapped',
      callsign: 'TEST-01',
      maintenance_tag: 'A2',
    });

    expect(fields.map((field) => field.key)).toEqual([
      'callsign',
      'maintenance_tag',
      'notes',
    ]);
  });

  test('promotes callsign as the preferred operator alias', () => {
    const promoted = getPromotedMissionConfigField({
      hw_id: 1,
      pos_id: 1,
      ip: '10.0.0.1',
      mavlink_port: 14550,
      callsign: 'VIPER-1',
      nickname: 'Backup Name',
    });

    expect(promoted).toEqual(expect.objectContaining({
      key: 'callsign',
      value: 'VIPER-1',
    }));
  });

  test('builds editable form state without dropping additional fields', () => {
    const formState = buildMissionConfigFormState({
      hw_id: 1,
      pos_id: 4,
      ip: '10.0.0.1',
      mavlink_port: 14550,
      serial_port: '',
      baudrate: 0,
      callsign: 'TEST-01',
      marker_color: '#00d4ff',
      battery_cycles: 17,
      metadata: { hangar: 'B', ready: true },
    });

    expect(formState.custom_fields).toEqual([
      expect.objectContaining({ key: 'callsign', type: CUSTOM_FIELD_TYPES.TEXT, value: 'TEST-01' }),
      expect.objectContaining({ key: 'battery_cycles', type: CUSTOM_FIELD_TYPES.NUMBER, value: '17' }),
      expect.objectContaining({ key: 'marker_color', type: CUSTOM_FIELD_TYPES.COLOR, value: '#00d4ff' }),
      expect.objectContaining({ key: 'metadata', type: CUSTOM_FIELD_TYPES.JSON }),
    ]);
  });

  test('serializes editable form state back to flat config fields', () => {
    const serialized = serializeMissionConfigFormState({
      hw_id: '7',
      pos_id: '9',
      ip: '10.0.0.7',
      mavlink_port: '14557',
      serial_port: '',
      baudrate: '0',
      isNew: false,
      custom_fields: [
        { id: 'c1', key: 'callsign', type: CUSTOM_FIELD_TYPES.TEXT, value: 'VIPER-7' },
        { id: 'c2', key: 'battery_cycles', type: CUSTOM_FIELD_TYPES.NUMBER, value: '24' },
        { id: 'c3', key: 'ready', type: CUSTOM_FIELD_TYPES.BOOLEAN, value: true },
        { id: 'c4', key: 'marker_color', type: CUSTOM_FIELD_TYPES.COLOR, value: '#ff9800' },
      ],
    });

    expect(serialized).toEqual(expect.objectContaining({
      hw_id: '7',
      pos_id: '9',
      callsign: 'VIPER-7',
      battery_cycles: 24,
      ready: true,
      marker_color: '#ff9800',
    }));
  });

  test('normalizes custom field keys to lowercase snake_case', () => {
    expect(normalizeMissionCustomFieldKey('Call Sign')).toBe('call_sign');
    expect(normalizeMissionCustomFieldKey('batteryCycles')).toBe('battery_cycles');
  });

  test('rejects duplicate and reserved additional field keys', () => {
    const validation = validateMissionCustomFields([
      { id: 'a', key: 'my_field', type: CUSTOM_FIELD_TYPES.TEXT, value: 'A' },
      { id: 'b', key: 'My Field', type: CUSTOM_FIELD_TYPES.TEXT, value: 'B' },
      { id: 'c', key: 'hw_id', type: CUSTOM_FIELD_TYPES.TEXT, value: 'bad' },
    ]);

    expect(validation.isValid).toBe(false);
    // 'my_field' and 'My Field' both normalize to 'my_field' — duplicate
    expect(validation.errorsById.a.key).toMatch(/unique/i);
    expect(validation.errorsById.b.key).toMatch(/unique/i);
    // 'hw_id' is a reserved core field
    expect(validation.errorsById.c.key).toMatch(/reserved/i);
  });

  test('provides predefined optional field templates for operator-friendly config edits', () => {
    expect(CUSTOM_FIELD_TEMPLATE_OPTIONS.map((option) => option.value)).toEqual(
      expect.arrayContaining(['callsign', 'marker_color', 'notes', 'role_hint', '__custom__'])
    );

    const markerTemplate = getMissionCustomFieldTemplate('Marker Color');
    expect(markerTemplate).toEqual(expect.objectContaining({
      key: 'marker_color',
      type: CUSTOM_FIELD_TYPES.COLOR,
    }));

    expect(createMissionCustomFieldDraftFromTemplate('marker_color')).toEqual(
      expect.objectContaining({
        key: 'marker_color',
        type: CUSTOM_FIELD_TYPES.COLOR,
        value: '#00d4ff',
      })
    );
  });

  test('validates marker color fields as hex colors', () => {
    const validation = validateMissionCustomFields([
      { id: 'good', key: 'marker_color', type: CUSTOM_FIELD_TYPES.COLOR, value: '#0af' },
      { id: 'bad', key: 'marker_color_bad', type: CUSTOM_FIELD_TYPES.COLOR, value: 'blue' },
    ]);

    expect(validation.isValid).toBe(false);
    expect(validation.errorsById.good).toBeUndefined();
    expect(validation.errorsById.bad.value).toMatch(/#RGB/i);
  });
});
