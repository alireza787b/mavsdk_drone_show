import { buildQuickScoutLaunchReadiness } from './quickScoutLaunchReadiness';

const readyDrone = {
  hw_id: '1',
  hw_ID: '1',
  pos_id: 1,
  is_armed: false,
  is_ready_to_arm: true,
  readiness_status: 'ready',
  readiness_summary: 'Ready to fly',
  readiness_checks: [],
  preflight_blockers: [],
  preflight_warnings: [],
  status_messages: [],
  preflight_last_update: Date.now(),
  update_time: Date.now(),
  heartbeat_last_seen: Date.now(),
};

describe('buildQuickScoutLaunchReadiness', () => {
  it('allows launch when the full package target set is online and ready', () => {
    const readiness = buildQuickScoutLaunchReadiness({
      drones: [readyDrone],
      targetHwIds: ['1'],
      referenceNowMs: Date.now(),
    });

    expect(readiness.canLaunch).toBe(true);
    expect(readiness.counts.ready).toBe(1);
    expect(readiness.blockers).toHaveLength(0);
  });

  it('blocks launch when an assigned aircraft is missing from the live fleet snapshot', () => {
    const readiness = buildQuickScoutLaunchReadiness({
      drones: [readyDrone],
      targetHwIds: ['1', '2'],
      referenceNowMs: Date.now(),
    });

    expect(readiness.canLaunch).toBe(false);
    expect(readiness.blockers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: 'missing-2',
        }),
      ]),
    );
  });

  it('treats degraded telemetry as a warning, not an immediate launch block', () => {
    const degradedDrone = {
      ...readyDrone,
      update_time: Date.now() - 12_000,
      heartbeat_last_seen: Date.now() - 2_000,
    };

    const readiness = buildQuickScoutLaunchReadiness({
      drones: [degradedDrone],
      targetHwIds: ['1'],
      referenceNowMs: Date.now(),
    });

    expect(readiness.canLaunch).toBe(true);
    expect(readiness.warnings).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: 'runtime-1',
        }),
      ]),
    );
  });

  it('blocks launch when a target drone is not ready', () => {
    const blockedDrone = {
      ...readyDrone,
      readiness_status: 'blocked',
      readiness_summary: 'GPS fix unavailable',
      is_ready_to_arm: false,
      preflight_blockers: [
        {
          source: 'telemetry',
          severity: 'error',
          message: 'GPS fix unavailable',
          timestamp: Date.now(),
        },
      ],
    };

    const readiness = buildQuickScoutLaunchReadiness({
      drones: [blockedDrone],
      targetHwIds: ['1'],
      referenceNowMs: Date.now(),
    });

    expect(readiness.canLaunch).toBe(false);
    expect(readiness.blockers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: 'readiness-1',
          detail: 'GPS fix unavailable',
        }),
      ]),
    );
  });
});
