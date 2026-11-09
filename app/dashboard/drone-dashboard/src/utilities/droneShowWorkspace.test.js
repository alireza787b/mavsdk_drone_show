import { buildShowCommand, formatShowOperationStart, formatShowStart, showReadiness } from './droneShowWorkspace';

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

test('explicit subsets preserve mapped slots and ignore unselected readiness', () => {
  const result = showReadiness({ workspace: base,
    operation: { fleet: [operation.fleet[0], { ...operation.fleet[1], telemetry_fresh: false }] },
    targetIds: ['10'], mode: 'local' });
  expect(result.ready).toBe(true);
  expect(showReadiness({ workspace: base, operation, targetIds: [], mode: 'local' }).ready).toBe(false);
  expect(showReadiness({ workspace: base, operation, targetIds: ['missing'], mode: 'local' }).ready).toBe(false);
});

test('selected show slots must be present and uniquely assigned across the configured fleet', () => {
  expect(showReadiness({ workspace: base, operation: { fleet: [operation.fleet[0], { ...operation.fleet[1], pos_id: '1' }] },
    targetIds: ['10'], mode: 'local' }).mappingReady).toBe(false);
  expect(showReadiness({ workspace: base, operation: { fleet: [{ ...operation.fleet[0], pos_id: '9' }] },
    targetIds: ['10'], mode: 'local' }).mappingReady).toBe(false);
});

test.each([false, true])('show scheduling uses existing Now, Delay and At-time contracts (custom=%s)', custom => {
  const options = { custom, referenceNowMs: 1700000000000 };
  expect(buildShowCommand('launch', ['10'], { ...options, scheduleMode: 'now' }).trigger_time).toBe(0);
  expect(buildShowCommand('launch', ['10'], { ...options, delay: 30 }).trigger_time).toBe(1700000030);
  expect(buildShowCommand('launch', ['10'], { ...options, scheduleMode: 'absolute', selectedDateTime: '2023-11-14T22:14:20Z' }).trigger_time).toBe(1700000060);
  expect(() => buildShowCommand('launch', ['10'], { ...options, delay: -1 })).toThrow();
  expect(() => buildShowCommand('launch', ['10'], { ...options, scheduleMode: 'absolute', selectedDateTime: '2020-01-01' })).toThrow();
});

test('Custom CSV is always type 3 LOCAL-only; empty scopes never become all', () => {
  expect(buildShowCommand('launch', ['10', '10'], { custom: true, mode: 'global-auto', scheduleMode: 'now' }))
    .toMatchObject({ mission_type: 3, target_drone_ids: ['10'], auto_global_origin: false, use_global_setpoints: false });
  expect(() => buildShowCommand('launch', [])).toThrow('No aircraft selected');
});

test('When ready labels zero honestly and countdown comes only from fresh tracked trigger evidence', () => {
  expect(formatShowStart(0)).toBe('Synchronized start after aircraft checks');
  const operation = { state: 'active', command: { mission_type: 3, params: { trigger_time: 0 } } };
  expect(formatShowOperationStart(operation, 1700000000000, true)).toBe('Preparing synchronized start');
  operation.command.params.trigger_time = 1700000030;
  expect(formatShowOperationStart(operation, 1700000010000, true)).toMatch(/^Start in 20 s/);
  expect(formatShowOperationStart(operation, 1700000010000, false)).toBe('Start timing unconfirmed');
  expect(formatShowOperationStart({ ...operation, state: 'completed' }, 1700000040000, true)).toBeNull();
});
