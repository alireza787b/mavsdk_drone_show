import {
  candidateMatchesDrone,
  describeOriginReference,
  findOriginReferenceTelemetry,
} from './originReference';

const readyTelemetry = (overrides = {}) => ({
  hw_id: '2',
  telemetry_available: true,
  is_armed: false,
  position_lat: 48.8566406,
  position_long: 2.359282,
  position_alt: 50.704,
  global_position_valid: true,
  global_position_age_ms: 250,
  gps_fix_type: 3,
  telemetry_stale_threshold_ms: 15_000,
  ...overrides,
});

describe('origin reference telemetry policy', () => {
  test('normalizes hardware identity while requiring the map key and row identity to agree', () => {
    const telemetry = {
      '02': readyTelemetry({ hw_id: 2 }),
      '3': readyTelemetry({ hw_id: '99' }),
    };

    expect(findOriginReferenceTelemetry(telemetry, '2')).toBe(telemetry['02']);
    expect(findOriginReferenceTelemetry(telemetry, 3)).toBeNull();
  });

  test('distinguishes a raw 3D receiver fix from a usable PX4 global position', () => {
    const status = describeOriginReference({
      '2': readyTelemetry({
        position_lat: 0,
        position_long: 0,
        position_alt: 0,
        global_position_valid: false,
        global_position_age_ms: null,
        gps_raw_valid: true,
        position_unavailable_reason: 'GPS fix present, waiting for valid PX4 global position.',
      }),
    }, '2');

    expect(status).toEqual({
      eligible: false,
      label: '3D fix · map pending',
      detail: 'GPS fix present, waiting for valid PX4 global position.',
    });
  });

  test.each([
    [
      'unavailable telemetry',
      { telemetry_available: false, telemetry_error: 'Telemetry link is stale.' },
      'Telemetry unavailable',
    ],
    [
      'armed reference',
      { is_armed: true },
      'Drone armed',
    ],
    [
      'missing absolute altitude',
      { position_alt: null },
      'Global position incomplete',
    ],
    [
      'default coordinates',
      { position_lat: 0, position_long: 0 },
      'Global position incomplete',
    ],
    [
      'stale global position',
      { global_position_age_ms: 15_001 },
      'Global position stale',
    ],
    [
      'missing global-position age',
      { global_position_age_ms: null },
      'Global position stale',
    ],
  ])('rejects %s', (_name, overrides, label) => {
    expect(describeOriginReference({ '2': readyTelemetry(overrides) }, '2')).toMatchObject({
      eligible: false,
      label,
    });
  });

  test('accepts fresh finite MSL telemetry, including a zero latitude or zero altitude', () => {
    const status = describeOriginReference({
      '2': readyTelemetry({
        position_lat: 0,
        position_long: 2.359282,
        position_alt: 0,
        global_position_age_ms: 0,
      }),
    }, 2);

    expect(status).toMatchObject({
      eligible: true,
      label: 'Reference ready',
    });
    expect(status.detail).toContain('0.0s old');
  });

  test('matches a preview only to the currently selected normalized hardware identity', () => {
    const preview = {
      origin: { lat: 48.8566, lon: 2.3592, alt: 50.7 },
      reference: { hw_id: 2 },
    };

    expect(candidateMatchesDrone(preview, '02')).toBe(true);
    expect(candidateMatchesDrone(preview, '1')).toBe(false);
    expect(candidateMatchesDrone({ reference: { hw_id: 2 } }, '2')).toBe(false);
    expect(candidateMatchesDrone(null, '2')).toBe(false);
  });
});
