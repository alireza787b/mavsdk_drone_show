import { buildSmartSwarmLaunchReadiness, SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M } from './smartSwarmLaunchReadiness';

describe('buildSmartSwarmLaunchReadiness', () => {
  test('flags selected drones that are not yet airborne', () => {
    const now = Date.now();
    const drones = [
      {
        hw_id: '1',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: false,
        position_alt: 0.05,
      },
      {
        hw_id: '2',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: true,
        position_alt: 2.5,
      },
      {
        hw_id: '3',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: true,
        position_alt: 0.1,
      },
    ];

    const readiness = buildSmartSwarmLaunchReadiness({
      drones,
      targetMode: 'selected',
      selectedDrones: ['1', '2', '3'],
      referenceNowMs: now,
    });

    expect(readiness.targetCount).toBe(3);
    expect(readiness.airborneCount).toBe(1);
    expect(readiness.groundedIds).toEqual(['1', '3']);
    expect(readiness.minAirborneAltitudeM).toBe(SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M);
  });

  test('ignores offline targets instead of misclassifying them as grounded', () => {
    const now = Date.now();
    const drones = [
      {
        hw_id: '1',
        update_time: now - 60_000,
        heartbeat_last_seen: now - 60_000,
        is_armed: false,
        position_alt: 0,
      },
      {
        hw_id: '2',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: false,
        position_alt: 0.05,
      },
    ];

    const readiness = buildSmartSwarmLaunchReadiness({
      drones,
      targetMode: 'all',
      referenceNowMs: now,
    });

    expect(readiness.targetCount).toBe(2);
    expect(readiness.groundedIds).toEqual(['2']);
  });
});
