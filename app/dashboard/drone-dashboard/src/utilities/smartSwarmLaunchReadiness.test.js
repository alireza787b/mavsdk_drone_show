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
        altitude_report: { source: 'relative_home', relative_home_m: 0.05, stale: false },
      },
      {
        hw_id: '2',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: true,
        altitude_report: { source: 'relative_home', relative_home_m: 2.5, stale: false },
      },
      {
        hw_id: '3',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: true,
        altitude_report: { source: 'relative_home', relative_home_m: 0.1, stale: false },
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

  test('reports offline targets separately from grounded targets', () => {
    const now = Date.now();
    const drones = [
      {
        hw_id: '1',
        update_time: now - 60_000,
        heartbeat_last_seen: now - 60_000,
        is_armed: false,
        altitude_report: { source: 'relative_home', relative_home_m: 0, stale: false },
      },
      {
        hw_id: '2',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: false,
        altitude_report: { source: 'relative_home', relative_home_m: 0.05, stale: false },
      },
    ];

    const readiness = buildSmartSwarmLaunchReadiness({
      drones,
      targetMode: 'all',
      referenceNowMs: now,
    });

    expect(readiness.targetCount).toBe(2);
    expect(readiness.groundedIds).toEqual(['2']);
    expect(readiness.unavailableIds).toEqual(['1']);
  });

  test('reports a selected target missing from the fleet snapshot as unavailable', () => {
    const now = Date.now();
    const readiness = buildSmartSwarmLaunchReadiness({
      drones: [{
        hw_id: '1',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: true,
        altitude_report: { source: 'relative_home', relative_home_m: 2.5, stale: false },
      }],
      targetMode: 'selected',
      selectedDrones: ['1', '2'],
      referenceNowMs: now,
    });

    expect(readiness.targetCount).toBe(2);
    expect(readiness.airborneCount).toBe(1);
    expect(readiness.unavailableDrones).toEqual([{
      hwId: '2',
      label: 'H2',
      runtimeLabel: 'Missing from fleet telemetry',
    }]);
  });

  test('never treats absolute MSL altitude as airborne height', () => {
    const now = Date.now();
    const readiness = buildSmartSwarmLaunchReadiness({
      drones: [{
        hw_id: '1',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: true,
        position_alt: 1278,
        altitude_report: {
          source: 'absolute_msl',
          display_m: 1278,
          relative_home_m: null,
          stale: false,
        },
      }],
      referenceNowMs: now,
    });

    expect(readiness.airborneCount).toBe(0);
    expect(readiness.groundedIds).toEqual(['1']);
  });

  test('accepts only a fresh home-relative altitude report', () => {
    const now = Date.now();
    const readiness = buildSmartSwarmLaunchReadiness({
      drones: [{
        hw_id: '1',
        update_time: now,
        heartbeat_last_seen: now,
        is_armed: true,
        altitude_report: {
          source: 'relative_home',
          display_m: 4,
          relative_home_m: 4,
          stale: false,
        },
      }],
      referenceNowMs: now,
    });

    expect(readiness.airborneCount).toBe(1);
    expect(readiness.groundedIds).toEqual([]);
  });

  test('matches the node airborne threshold at the 0.5 m boundary', () => {
    const now = Date.now();
    const base = {
      update_time: now,
      heartbeat_last_seen: now,
      is_armed: true,
    };
    const readiness = buildSmartSwarmLaunchReadiness({
      drones: [
        {
          ...base,
          hw_id: '1',
          altitude_report: { source: 'relative_home', relative_home_m: 0.49, stale: false },
        },
        {
          ...base,
          hw_id: '2',
          altitude_report: { source: 'relative_home', relative_home_m: 0.5, stale: false },
        },
      ],
      referenceNowMs: now,
    });

    expect(SMART_SWARM_MIN_AIRBORNE_ALTITUDE_M).toBe(0.5);
    expect(readiness.groundedIds).toEqual(['1']);
    expect(readiness.airborneCount).toBe(1);
  });
});
