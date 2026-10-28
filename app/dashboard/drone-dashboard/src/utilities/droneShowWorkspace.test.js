import { showReadiness } from './droneShowWorkspace';

const base = {
  package: { available: true, position_ids: ['1', '2'] },
  validation: { validation_status: 'PASS', issues: [] },
};

const operation = {
  fleet: [
    { hw_id: '10', pos_id: '1', telemetry_fresh: true, ready_to_arm: true, armed: false },
    { hw_id: '20', pos_id: '2', telemetry_fresh: true, ready_to_arm: true, armed: false },
  ],
};

const deviations = (statuses = ['ok', 'ok']) => ({
  summary: { worst_deviation: statuses.includes('warning') ? 4.2 : 0.4, warnings: statuses.filter((s) => s === 'warning').length },
  deviations: Object.fromEntries(statuses.map((status, index) => [index ? '20' : '10', { status }])),
});

test('blocks global auto correction when origin is missing', () => {
  const result = showReadiness({ workspace: base, operation, mode: 'global-auto', origin: {}, deviations: deviations() });
  expect(result.originReady).toBe(false);
  expect(result.readinessState).toBe('blocked');
});

test('allows a warning-level correction with explicit review state', () => {
  const result = showReadiness({ workspace: base, operation, mode: 'global-auto', origin: { lat: 1, lon: 2 }, deviations: deviations(['warning', 'ok']) });
  expect(result.geometryReady).toBe(true);
  expect(result.geometryState).toBe('review');
  expect(result.ready).toBe(true);
});

test('blocks missing telemetry and unavailable trajectory analysis', () => {
  const result = showReadiness({
    workspace: { ...base, validation: { validation_status: 'UNKNOWN' } },
    operation: { fleet: [{ ...operation.fleet[0], telemetry_fresh: false }] },
    mode: 'global-auto', origin: { lat: 1, lon: 2 },
    deviations: { summary: {}, deviations: { 10: { status: 'no_telemetry' } } },
  });
  expect(result.fleetReady).toBe(false);
  expect(result.analysisReady).toBe(false);
  expect(result.readinessState).toBe('blocked');
});
