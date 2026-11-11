import { attachDroneRuntimeClock } from '../../constants/fieldMappings';
import { DEFAULT_FLEET_AVAILABILITY_POLICY, getAircraftAvailability } from './fleetAvailability';

const NOW = 1780000000000;
const heartbeat = (ageSec, extra = {}) => ({ heartbeat_last_seen: NOW - ageSec * 1000, ...extra });
const availability = (drone, nowMs = NOW, policy) => getAircraftAvailability(drone, nowMs, policy);

describe('heartbeat-only aircraft availability', () => {
  test.each([
    [0, true, false, 'Fresh'],
    [10, true, false, 'Fresh'],
    [10.001, true, true, 'Stale'],
    [60, true, true, 'Stale'],
    [60.001, false, false, 'Offline'],
  ])('classifies a %ss heartbeat without rounding across a boundary', (ageSec, available, stale, label) => {
    expect(availability(heartbeat(ageSec))).toEqual({ available, stale, ageSec, label,
      tone: !available ? 'danger' : stale ? 'warning' : 'good' });
  });

  test('never treats a successful HTTP/telemetry sample or arming state as a heartbeat', () => {
    expect(availability({ update_time: NOW / 1000, timestamp: NOW, telemetry_available: true,
      is_armed: true, presence: { state: 'live', fresh: true, source: 'telemetry', last_seen_ms: NOW } }))
      .toMatchObject({ available: false, stale: false, ageSec: null, label: 'Unknown' });
    expect(availability(heartbeat(70, { update_time: NOW / 1000, telemetry_available: true })))
      .toMatchObject({ available: false, ageSec: 70, label: 'Offline' });
  });

  test.each([null, undefined, '', ' ', 'not-a-timestamp', false, true, {}, [], 0, -1, Infinity, NaN, NOW + 1])(
    'does not invent freshness from missing, invalid or future evidence %p', (heartbeat_last_seen) => {
      expect(availability({ heartbeat_last_seen })).toMatchObject({ available: false, ageSec: null, label: 'Unknown' });
    });

  test.each([NOW - 5000, (NOW - 5000) / 1000, String(NOW - 5000), String((NOW - 5000) / 1000)])(
    'accepts numeric epoch seconds/milliseconds %p', (heartbeat_last_seen) => {
      expect(availability({ heartbeat_last_seen })).toMatchObject({ available: true, stale: false, ageSec: 5 });
    });

  test('canonical trusted GCS receipt overrides raw node/legacy timestamps', () => {
    expect(availability({ heartbeat_last_seen: NOW, presence: {
      heartbeat_received_at_gcs_ms: NOW - 70000, heartbeat_sent_at_node_ms: NOW,
    } })).toMatchObject({ available: false, ageSec: 70, label: 'Offline' });
    expect(availability({ heartbeat_last_seen: NOW - 70000, presence: {
      heartbeat_received_at_gcs_ms: NOW - 5000, heartbeat_sent_at_node_ms: NOW + 100000,
    } })).toMatchObject({ available: true, ageSec: 5 });
  });

  test.each([null, '', 'bad', NOW + 1000])('an explicit unusable canonical receipt cannot fall back to fresher evidence %p', (receipt) => {
    const drone = attachDroneRuntimeClock({ heartbeat_last_seen: NOW, presence: {
      heartbeat_received_at_gcs_ms: receipt, heartbeat_age_sec: 0,
    } }, { serverNowMs: NOW, receivedAtMs: NOW });
    expect(availability(drone)).toMatchObject({ available: false, ageSec: null, label: 'Unknown' });
  });

  test('ages unchanged cached heartbeat evidence against the calibrated GCS clock', () => {
    const browserNow = NOW + 3600000;
    const drone = attachDroneRuntimeClock(heartbeat(5), { serverNowMs: NOW, receivedAtMs: browserNow });
    expect(availability(drone, browserNow)).toMatchObject({ available: true, stale: false, ageSec: 5 });
    expect(availability(drone, browserNow + 6000)).toMatchObject({ available: true, stale: true, ageSec: 11 });
    expect(availability(drone, browserNow + 56000)).toMatchObject({ available: false, ageSec: 61 });
  });

  test('age-only native presence requires its calibrated receipt clock and keeps aging', () => {
    const drone = { presence: { heartbeat_age_sec: 8 } };
    expect(availability(drone)).toMatchObject({ available: false, ageSec: null });
    attachDroneRuntimeClock(drone, { serverNowMs: NOW, receivedAtMs: NOW + 50000 });
    expect(availability(drone, NOW + 50000)).toMatchObject({ available: true, stale: false, ageSec: 8 });
    expect(availability(drone, NOW + 53000)).toMatchObject({ available: true, stale: true, ageSec: 11 });
    expect(availability(drone, NOW + 103000)).toMatchObject({ available: false, ageSec: 61 });
    expect(availability(attachDroneRuntimeClock({ ...drone, presence: { heartbeat_age_sec: -1 } },
      { serverNowMs: NOW, receivedAtMs: NOW }))).toMatchObject({ available: false, ageSec: null });
  });

  test('packet timestamps alone cannot calibrate browser time or age-only presence', () => {
    const drone = attachDroneRuntimeClock({ timestamp: NOW, presence: { heartbeat_age_sec: 0 } }, { receivedAtMs: NOW });
    expect(availability(drone)).toMatchObject({ available: false, ageSec: null });
    const skewed = attachDroneRuntimeClock(heartbeat(0), { receivedAtMs: NOW + 3600000 });
    expect(availability(skewed, NOW + 3600000)).toMatchObject({ available: false, ageSec: 3600 });
  });

  test('uses supplied policy, falls back on malformed values and never mutates policy', () => {
    const policy = Object.freeze({ stale_sec: 5, available_sec: 30 });
    expect(availability(heartbeat(6), NOW, policy)).toMatchObject({ available: true, stale: true });
    expect(availability(heartbeat(31), NOW, policy)).toMatchObject({ available: false });
    expect(availability(heartbeat(11), NOW, { stale_sec: 'bad', available_sec: -1 }))
      .toMatchObject({ available: true, stale: true });
    expect(availability(heartbeat(61), NOW, null)).toMatchObject({ available: false });
    expect(DEFAULT_FLEET_AVAILABILITY_POLICY).toEqual({ stale_sec: 10, available_sec: 60 });
  });

  test.each([undefined, null, NaN, Infinity, '1780000000000'])('requires an explicit valid caller clock %p', (nowMs) => {
    expect(getAircraftAvailability(heartbeat(0), nowMs)).toMatchObject({ available: false, ageSec: null });
  });
});
