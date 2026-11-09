import { createFleetAlertsState, fleetAlertsReducer, FLEET_ALERT_LIMITS } from './FleetAlertsContext';

const NOW = 1780000000000;
const item = (id = '1', issues = [{ key: 'battery', tone: 'warning', label: 'Battery: Low' }], current = true) => ({ id, label: `Aircraft ${id}`, current, issues });
const publish = (state, aircraft, observedAtMs = NOW, sourceError = false) => fleetAlertsReducer(state, { type: 'snapshot', snapshot: { aircraft, observedAtMs, sourceError } });

test('repeated snapshots deduplicate by aircraft and condition, while recurrence starts a new episode', () => {
  const first = publish(createFleetAlertsState(), [item()]);
  const second = publish(first, [item(), item()], NOW + 1000);
  expect(second.active).toHaveLength(1);
  expect(second.active[0]).toMatchObject({ id: first.active[0].id, firstObservedAtMs: NOW, lastObservedAtMs: NOW + 1000 });
  const cleared = publish(second, [item('1', [])], NOW + 2000);
  expect(cleared.active).toHaveLength(0);
  expect(cleared.recent[0]).toMatchObject({ id: first.active[0].id, clearedAtMs: NOW + 2000 });
  const recurrence = publish(cleared, [item()], NOW + 3000);
  expect(recurrence.active[0].id).not.toBe(first.active[0].id);
  expect(recurrence.recent).toHaveLength(1);
});

test('Seen is local acknowledgement, never a clear; it persists within one episode only', () => {
  const first = publish(createFleetAlertsState(), [item()]);
  const seen = fleetAlertsReducer(first, { type: 'seen', id: first.active[0].id });
  expect(seen.active[0]).toMatchObject({ seen: true, clearedAtMs: null });
  expect(seen.recent).toHaveLength(0);
  const refreshed = publish(seen, [item()], NOW + 1000);
  expect(refreshed.active[0].seen).toBe(true);
  const recurrence = publish(publish(refreshed, [item('1', [])], NOW + 2000), [item()], NOW + 3000);
  expect(recurrence.active[0].seen).toBe(false);
});

test('source departure, missing aircraft and stale telemetry cannot resolve a previously observed condition', () => {
  const first = publish(createFleetAlertsState(), [item()]);
  const left = fleetAlertsReducer(first, { type: 'source-unavailable' });
  expect(left.monitoring).toBe(false);
  expect(left.active[0].lastObservedAtMs).toBe(NOW);
  const missing = publish(left, [], NOW + 1000);
  expect(missing.active[0]).toMatchObject({ observed: false, clearedAtMs: null, lastObservedAtMs: NOW });
  const stale = publish(missing, [item('1', [{ key: 'telemetry', label: 'Offline', tone: 'danger' }], false)], NOW + 2000);
  expect(stale.active).toHaveLength(2);
  expect(stale.active.find((episode) => episode.issueKey === 'battery').observed).toBe(false);
  expect(stale.recent).toHaveLength(0);
});

test('raw readiness is never consumed; non-link stale issues cannot become observed conditions', () => {
  const aircraft = { ...item('1', [{ key: 'preflight_blockers:cached', label: 'Cached failure' }], false),
    raw: { readiness_status: 'blocked', preflight_blockers: [{ message: 'Raw failure' }] } };
  expect(publish(createFleetAlertsState(), [aircraft]).active).toHaveLength(0);
});

test('one aggregate GCS outage replaces per-aircraft loss generation, without clearing previous evidence', () => {
  const fleet = Array.from({ length: 100 }, (_, index) => item(String(index + 1), [{ key: 'telemetry', label: 'Offline' }], false));
  const outage = publish(createFleetAlertsState(), fleet, NOW, new Error('network'));
  expect(outage.active).toHaveLength(1);
  expect(outage.active[0]).toMatchObject({ aircraftId: null, reason: 'Telemetry source unavailable' });
  expect(publish(outage, fleet, NOW + 1000, true).active[0].id).toBe(outage.active[0].id);
  const first = publish(createFleetAlertsState(), [item()]);
  const paused = publish(first, fleet, NOW + 1000, true);
  expect(paused.active).toHaveLength(2);
  expect(paused.active.find((episode) => episode.aircraftId === '1')).toMatchObject({ observed: false, lastObservedAtMs: NOW });
  const restored = publish(paused, [item()], NOW + 2000);
  expect(restored.active).toHaveLength(1);
  expect(restored.recent[0].aircraftId).toBeNull();
});

test('aircraft, per-aircraft conditions and recent cleared episodes are bounded with explicit omission counts', () => {
  const fleet = Array.from({ length: 101 }, (_, index) => item(String(index + 1), Array.from({ length: 6 }, (_, issue) => ({ key: `issue-${issue}`, label: `Issue ${issue}` }))));
  const state = publish(createFleetAlertsState(), fleet);
  expect(new Set(state.active.map((episode) => episode.aircraftId)).size).toBe(100);
  expect(state.active).toHaveLength(500);
  expect(state).toMatchObject({ omittedAircraft: 1, omittedConditions: 100 });
  expect(state.active[0]).not.toHaveProperty('raw');
  let history = createFleetAlertsState();
  for (let index = 0; index < 60; index += 1) {
    history = publish(history, [item()], NOW + index * 2000);
    history = publish(history, [item('1', [])], NOW + index * 2000 + 1000);
  }
  expect(history.recent).toHaveLength(FLEET_ALERT_LIMITS.recent);
  expect(history.active).toHaveLength(0);
  expect(history.recent[0].clearedAtMs).toBe(NOW + 119000);
});

test('a completely replaced roster does not grow retained identities beyond the bound', () => {
  const fleet = (offset) => Array.from({ length: 100 }, (_, index) => item(String(index + offset)));
  const state = publish(publish(createFleetAlertsState(), fleet(1)), fleet(101), NOW + 1000);
  expect(new Set(state.active.map((episode) => episode.aircraftId)).size).toBe(100);
  expect(state.omittedAircraft).toBe(100);
});

test('older or invalid source observations cannot overwrite newer evidence', () => {
  const state = publish(createFleetAlertsState(), [item()], NOW + 1000);
  expect(publish(state, [], NOW)).toBe(state);
  expect(publish(state, [], NaN)).toBe(state);
});
