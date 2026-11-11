import { attachDroneRuntimeClock } from '../../constants/fieldMappings';
import { buildAircraftViewModel, buildFleetViewModel } from './fleetViewModel';
import { DRONE_MISSION_TYPES } from '../../constants/droneConstants';

const NOW = 1780000000000;
const live = (id = '1', extra = {}) => ({
  hw_id: id, update_time: NOW / 1000, telemetry_available: true,
  is_armed: false, landed_state: 1,
  position_lat: 35.7, position_long: 51.4, global_position_valid: true,
  position_alt: 1200, gps_fix_type: 3, satellites_visible: 12,
  hdop: 0.8, vdop: 1.1, battery_remaining_percent: 80, battery_voltage: 16.1,
  ...extra,
});
const build = (drone, nowMs = NOW) => buildAircraftViewModel(drone, nowMs);

describe('fleet presentation truth', () => {
  test.each([1, 3, 100])('keeps %s aircraft distinct and stable, without a 64-ID presentation limit', (count) => {
    const drones = Array.from({ length: count }, (_, i) => live(String(i + 1)));
    const first = buildFleetViewModel(drones, { nowMs: NOW });
    const next = buildFleetViewModel([...drones].reverse(), { nowMs: NOW, previousOrder: first.order });
    expect(next.order).toEqual(first.order);
    expect(next.aircraft).toHaveLength(count);
    expect(next.byId.size).toBe(count);
    expect(next.summary).toMatchObject({ total: count, current: count, unavailable: 0, grounded: count, airborne: 0 });
  });

  test('missing telemetry and active system status never manufacture GPS, battery, altitude or phase', () => {
    const aircraft = build({ hw_id: '1', system_status: 4 });
    expect(aircraft.gps).toMatchObject({ fixType: null, label: 'Unknown', satellites: null, hdop: null, vdop: null, current: false });
    expect(aircraft.battery).toMatchObject({ remaining: null, available: false, text: 'Unknown' });
    expect(aircraft.altitude.value).toBeNull();
    expect(aircraft.armed).toBeNull();
    expect(aircraft.flightState).toBe('Unknown');
    expect(aircraft.position.current).toBe(false);
    expect(aircraft.runtime.label).toBe('Never seen');
    expect(build({ hw_id: '1', flight_mode: 65536, mission: 0 })).toMatchObject({
      flightMode: { label: 'Unknown', known: false }, mission: { label: 'Unknown', known: false },
    });
  });

  test('fresh but incomplete telemetry is not filled with invented fixes or DOP', () => {
    const aircraft = build({ hw_id: '1', system_status: 4, update_time: NOW / 1000 });
    expect(aircraft.current).toBe(true);
    expect(aircraft.gps).toMatchObject({ fixType: null, satellites: null, hdop: null, vdop: null });
    expect(aircraft.altitude.value).toBeNull();
  });

  test('preserves observed zero, distinguishes null/empty, and requires valid map coordinates', () => {
    const aircraft = build(live('1', { gps_fix_type: 0, satellites_visible: 0, hdop: 0, vdop: 0, battery_remaining_percent: 0, position_alt: 0 }));
    expect(aircraft.gps).toMatchObject({ fixType: 0, satellites: 0, hdop: 0, vdop: 0 });
    expect(aircraft.battery.remaining).toBe(0);
    expect(aircraft.altitude.value).toBe(0);
    expect(build(live('1', { position_lat: null, position_long: '' })).position.current).toBe(false);
    expect(build(live('1', { position_lat: 91 })).position.current).toBe(false);
    expect(build(live('1', { global_position_valid: false })).position.current).toBe(false);
    expect(build(live('1', { position_lat: 0, position_long: 0, global_position_valid: true })).position.current).toBe(true);
    expect(build(live('1', { position_lat: 0, position_long: 0, global_position_valid: undefined })).position.current).toBe(false);
    expect(build(live('1', { position_alt: null, altitude_report: { display_m: null, source: 'absolute_msl' } })).altitude.value).toBeNull();
  });

  test('armed is not airborne; disarmed is not grounded; stale is neither', () => {
    expect(build(live('1', { is_armed: true, landed_state: undefined })).flightState).toBe('Unknown');
    expect(build(live('1', { is_armed: false, landed_state: undefined })).flightState).toBe('Unknown');
    expect(build(live('1', { is_armed: true })).flightState).toBe('Grounded');
    expect(build(live('1', { landed_state: 2 })).flightState).toBe('Airborne');
    const stale = build(live('1', { is_armed: true, landed_state: 2 }), NOW + 61000);
    expect(stale).toMatchObject({ current: false, armed: null, flightState: 'Unknown', lastKnown: true });
    expect(stale.battery).toMatchObject({ current: false, stale: true });
    expect(stale.altitude).toMatchObject({ current: false, stale: true, trustedForMap: false });
    expect(stale.gps).toMatchObject({ current: false, stale: true });
    expect(stale.position).toMatchObject({ current: false, stale: true });
  });

  test('heartbeat-only and unavailable envelopes cannot promote cached telemetry to current', () => {
    const delayed = build(live('1', { update_time: (NOW - 30000) / 1000, heartbeat_last_seen: NOW / 1000 }));
    expect(delayed).toMatchObject({ current: false, armed: null, flightState: 'Unknown' });
    expect(delayed.runtime.level).toBe('degraded');
    const unavailable = build(live('1', { telemetry_available: false }));
    expect(unavailable.current).toBe(false);
    expect(unavailable.issues[0].label).toBe('Telemetry unavailable');
  });

  test('source-specific stale samples are not made current by fresh vehicle telemetry', () => {
    const aircraft = build(live('1', { battery_age_ms: 11000, gps_raw_age_ms: 11000, global_position_age_ms: 11000 }));
    expect(aircraft.current).toBe(true);
    expect(aircraft.battery.current).toBe(false);
    expect(aircraft.gps.current).toBe(false);
    expect(aircraft.position.current).toBe(false);
    expect(aircraft.altitude.current).toBe(false);
  });

  test('sample ages and link status advance while polls are hung, respecting the calibrated clock', () => {
    const drone = attachDroneRuntimeClock(live('1', { battery_age_ms: 9000 }), { receivedAtMs: NOW + 100000, serverNowMs: NOW });
    expect(build(drone, NOW + 100000).current).toBe(true);
    expect(build(drone, NOW + 102000).battery.current).toBe(false);
    expect(build(drone, NOW + 112000).current).toBe(false);
  });

  test('uses hardware identity, distinguishes duplicate callsigns, and never substitutes a slot', () => {
    const fleet = buildFleetViewModel([live('2', { callsign: 'Scout' }), live('1', { callsign: 'Scout' }), { pos_id: '3' }], { nowMs: NOW });
    expect(fleet.order).toEqual(['1', '2']);
    expect(fleet.aircraft.map((item) => item.label)).toEqual(['Scout', 'Scout']);
    expect(fleet.aircraft.map((item) => item.identity.hwId)).toEqual(['1', '2']);
    expect(build({ pos_id: '1' })).toBeNull();
  });

  test('summary explicitly counts unknown arm state and retains unselected hazards independent of targeting', () => {
    const drones = [live('1', { is_armed: true, landed_state: 2 }), live('2', { battery_charge_state: 3 }), { hw_id: '3' }];
    const fleet = buildFleetViewModel(drones, { nowMs: NOW });
    expect(fleet.summary).toMatchObject({ total: 3, current: 2, unavailable: 1, attention: 1, armed: 1, disarmed: 1, armUnknown: 1 });
    expect(fleet.byId.get('2').issues[0]).toMatchObject({ key: 'battery', tone: 'danger' });
    expect(buildFleetViewModel([], { nowMs: NOW }).summary).toMatchObject({ total: 0, current: 0 });
  });

  test('prior ordering survives severity changes and new arrivals append deterministically', () => {
    const fleet = buildFleetViewModel([live('1'), live('10'), live('2'), live('3', { battery_charge_state: 3 })], { nowMs: NOW, previousOrder: ['3', '1'] });
    expect(fleet.order).toEqual(['3', '1', '2', '10']);
  });

  test('unused configured aircraft do not flood attention, but losing an observed aircraft does', () => {
    const configured = Array.from({ length: 100 }, (_, index) => ({ hw_id: String(index + 1) }));
    const unused = buildFleetViewModel(configured, { nowMs: NOW });
    expect(unused.summary.attention).toBe(0);
    expect(unused.summary.available).toBe(0);
    expect(build(live(), NOW + 65000).attention).toBe(true);
  });

  test('heartbeat availability stays independent of telemetry and uses the published display policy', () => {
    const drones = [live('1', { heartbeat_last_seen: (NOW - 15000) / 1000 }),
      live('2', { update_time: (NOW - 30000) / 1000, heartbeat_last_seen: NOW / 1000 }),
      live('3')];
    const fleet = buildFleetViewModel(drones, { nowMs: NOW, displayPolicy: { stale_sec: 12, available_sec: 14 } });
    expect(fleet.byId.get('1')).toMatchObject({ current: true, availability: { available: false, label: 'Offline' } });
    expect(fleet.byId.get('2')).toMatchObject({ current: false, flightState: 'Unknown', availability: { available: true, label: 'Fresh' } });
    expect(fleet.byId.get('3')).toMatchObject({ current: true, availability: { available: false, label: 'Unknown' } });
    expect(fleet.summary).toMatchObject({ current: 2, unavailable: 1, available: 1, stale: 0 });
    const stale = buildAircraftViewModel(drones[0], NOW, { stale_sec: 10, available_sec: 60 });
    expect(stale.availability).toMatchObject({ available: true, stale: true, ageSec: 15 });
  });

  test.each([[0, 'Initializing'], [65536, 'Manual'], [0x03040000, 'Hold'], [0x00060000, 'Offboard'],
    [null, 'Unknown'], ['', 'Unknown'], [0x2a040000, 'Unknown'], [0xff000000, 'Unknown']])('names flight mode %s without exposing a code', (code, label) => {
    expect(build(live('1', { flight_mode: code })).flightMode).toMatchObject({ label });
  });

  test('cached named modes and missions are explicitly last known, never implied current', () => {
    const aircraft = build(live('1', { flight_mode: 0x03040000, mission: DRONE_MISSION_TYPES.SMART_SWARM }), NOW + 20000);
    expect(aircraft.flightMode).toMatchObject({ label: 'Hold', current: false, stale: true });
    expect(aircraft.mission).toMatchObject({ label: 'Smart Swarm', current: false, stale: true });
    expect(build(live()).mission).toMatchObject({ label: 'Unknown', known: false });
    expect(build(live('1', { mission: 9999 })).mission).toMatchObject({ label: 'Unknown', known: false });
    expect(build(live('1', { mission: 0 })).mission).toMatchObject({ label: 'No Mission', known: true });
  });

  test('Wi-Fi percentage requires a measured value and a fresh heartbeat, not telemetry success', () => {
    const drone = live('1', { heartbeat_last_seen: NOW / 1000, heartbeat_network_info: { wifi: { signal_strength_percent: 0 } } });
    expect(build(drone).wifi).toEqual({ percent: 0, current: true });
    expect(build({ ...drone, telemetry_available: false }).wifi.current).toBe(true);
    expect(build(drone, NOW + 11000).wifi).toEqual({ percent: null, current: false });
    expect(build({ ...drone, heartbeat_last_seen: undefined }).wifi.current).toBe(false);
    [null, '', 'bad', -1, 101, Infinity].forEach((value) => {
      expect(build({ ...drone, heartbeat_network_info: { wifi: { signal_strength_percent: value } } }).wifi.current).toBe(false);
    });
  });

  test('readiness requires native evidence, never absence of issues, and ages independently of heartbeat', () => {
    expect(build(live()).readiness).toMatchObject({ status: 'unknown', label: 'Unknown' });
    expect(build(live('1', { readiness_status: 'ready' })).readiness.status).toBe('ready');
    expect(build(live('1', { readiness_status: 'warning' })).readiness.status).toBe('warning');
    expect(build(live('1', { readiness_status: 'ready', preflight_blockers: [{ message: 'Heading blocked' }] })).readiness.status).toBe('blocked');
    const stale = live('1', { readiness_status: 'ready', heartbeat_last_seen: NOW / 1000, update_time: (NOW - 20000) / 1000 });
    expect(build(stale).readiness).toMatchObject({ status: 'unknown', summary: '' });
  });
});
