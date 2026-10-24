import { buildSmartSwarmLaunchReadiness } from './smartSwarmLaunchReadiness';

const now = Date.now();
const aircraft = (hw_id, state = {}) => ({
  hw_id, update_time: now, heartbeat_last_seen: now, is_armed: true,
  landed_state: 2, ...state,
});
const readiness = (drones, scope = {}) => buildSmartSwarmLaunchReadiness({
  drones, referenceNowMs: now, ...scope,
});

test('native airborne evidence does not require a home-relative height floor', () => {
  const result = readiness([aircraft('1', { altitude_report: {
    source: 'relative_home', relative_home_m: -20, stale: false,
  } }), aircraft('2')]);
  expect(result.airborneCount).toBe(2);
  expect(result.groundedIds).toEqual([]);
});

test('native landed and disarmed states are not admitted as airborne', () => {
  const result = readiness([aircraft('1', { is_armed: false, landed_state: 1 }),
    aircraft('2', { landed_state: 1 }), aircraft('3')]);
  expect(result.airborneCount).toBe(1);
  expect(result.groundedIds).toEqual(['1', '2']);
});

test.each([undefined, 0, 3, 4])('missing or transitioning landed state %s is not guessed from height', (landed_state) => {
  const result = readiness([aircraft('1', { landed_state, position_alt: 1278,
    altitude_report: { source: 'relative_home', relative_home_m: 10, stale: false } })]);
  expect(result.airborneCount).toBe(0);
  expect(result.groundedIds).toEqual([]);
  expect(result.unavailableIds).toEqual(['1']);
});

test('offline and missing targets remain unavailable, separate from grounded', () => {
  const result = readiness([aircraft('1', { update_time: now - 60000, heartbeat_last_seen: now - 60000 }),
    aircraft('2', { is_armed: false })], { targetMode: 'selected', selectedDrones: ['1', '2', '3'] });
  expect(result.targetCount).toBe(3);
  expect(result.groundedIds).toEqual(['2']);
  expect(result.unavailableIds).toEqual(['3', '1']);
});
