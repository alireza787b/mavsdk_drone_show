import { FIELD_NAMES } from '../constants/fieldMappings';
import { getDroneReadinessModel } from './droneReadiness';

describe('getDroneReadinessModel', () => {
  it('returns ready when telemetry is live and no blockers exist', () => {
    const drone = {
      [FIELD_NAMES.IS_READY_TO_ARM]: true,
      [FIELD_NAMES.READINESS_STATUS]: 'ready',
      [FIELD_NAMES.READINESS_SUMMARY]: 'Ready to fly',
      [FIELD_NAMES.PREFLIGHT_BLOCKERS]: [],
      [FIELD_NAMES.PREFLIGHT_WARNINGS]: [],
      [FIELD_NAMES.STATUS_MESSAGES]: [],
      [FIELD_NAMES.READINESS_CHECKS]: [],
    };

    const result = getDroneReadinessModel(drone, { level: 'online' });

    expect(result.isReady).toBe(true);
    expect(result.status).toBe('ready');
    expect(result.summary).toBe('Ready to fly');
  });

  it('adds a link guard when telemetry is stale', () => {
    const nowMs = Date.now();
    const drone = {
      [FIELD_NAMES.IS_READY_TO_ARM]: true,
      [FIELD_NAMES.READINESS_STATUS]: 'ready',
      [FIELD_NAMES.READINESS_SUMMARY]: 'Ready to fly',
      [FIELD_NAMES.PREFLIGHT_BLOCKERS]: [],
      [FIELD_NAMES.PREFLIGHT_WARNINGS]: [],
      [FIELD_NAMES.STATUS_MESSAGES]: [],
      [FIELD_NAMES.READINESS_CHECKS]: [],
      [FIELD_NAMES.PREFLIGHT_LAST_UPDATE]: nowMs,
    };

    const result = getDroneReadinessModel(drone, {
      level: 'degraded',
      telemetryAgeSec: 12,
      heartbeatAgeSec: 3,
    });

    expect(result.isReady).toBe(true);
    expect(result.status).toBe('ready');
    expect(result.blockers).toHaveLength(0);
    expect(result.warnings[0].source).toBe('link');
  });

  it('falls back to unknown when link is stale and no recent readiness snapshot exists', () => {
    const nowMs = Date.now();
    const drone = {
      [FIELD_NAMES.IS_READY_TO_ARM]: true,
      [FIELD_NAMES.READINESS_STATUS]: 'ready',
      [FIELD_NAMES.READINESS_SUMMARY]: 'Ready to fly',
      [FIELD_NAMES.PREFLIGHT_BLOCKERS]: [],
      [FIELD_NAMES.PREFLIGHT_WARNINGS]: [],
      [FIELD_NAMES.STATUS_MESSAGES]: [],
      [FIELD_NAMES.READINESS_CHECKS]: [],
      [FIELD_NAMES.PREFLIGHT_LAST_UPDATE]: nowMs - 180_000,
    };

    const result = getDroneReadinessModel(drone, {
      level: 'offline',
      telemetryAgeSec: 120,
      heartbeatAgeSec: 140,
    });

    expect(result.isReady).toBe(false);
    expect(result.status).toBe('unknown');
    expect(result.blockers[0].source).toBe('link');
  });
});
