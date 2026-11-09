import {
  createTargetSelectionState, targetSelectionReducer, uniqueTargetIds,
  getTargetSelectionReview, getTargetSelectionStorageScope,
  parseTargetSelection, serializeTargetSelection,
} from './targetSelection';

const initialize = (configuredIds, savedIds) => targetSelectionReducer(createTargetSelectionState(), {
  type: 'initialize', configuredIds, savedIds,
});

describe('explicit fleet targets', () => {
  test.each([1, 3, 100])('initializes all %s configured aircraft, independently of availability', (count) => {
    const ids = Array.from({ length: count }, (_, i) => String(i + 1));
    expect(initialize(ids)).toEqual({ initialized: true, ids });
  });

  test('waits for known configuration, including a legitimately empty roster', () => {
    const state = createTargetSelectionState();
    expect(targetSelectionReducer(state, { type: 'initialize' })).toBe(state);
    expect(initialize([])).toEqual({ initialized: true, ids: [] });
  });

  test.each([[[]], [['2']], [['2', 'removed']]])('restores exact saved IDs %j, including empty and unresolved', (savedIds) => {
    expect(initialize(['1', '2', '3'], savedIds).ids).toEqual(savedIds);
  });

  test('new arrivals, roster removals, reconnects and filters cannot retarget', () => {
    const state = initialize(['1', '2'], ['2', 'removed']);
    expect(targetSelectionReducer(state, { type: 'initialize', configuredIds: ['1', '3'] })).toBe(state);
    expect(targetSelectionReducer(state, { type: 'telemetry', ids: ['1', '3'] })).toBe(state);
    expect(targetSelectionReducer(state, { type: 'filter', ids: ['1'] })).toBe(state);
    expect(getTargetSelectionReview(state, ['1', '2'], ['1'])).toEqual({
      count: 2, hiddenIds: ['2'], unresolvedIds: ['removed'],
    });
    expect(state.ids).toEqual(['2', 'removed']);
  });

  test('all, none, group and toggle are explicit immutable snapshots', () => {
    const state = initialize(['1', '2', '3']);
    const group = ['2'];
    const selected = targetSelectionReducer(state, { type: 'group', ids: group });
    group.push('3');
    expect(selected.ids).toEqual(['2']);
    const toggled = targetSelectionReducer(selected, { type: 'toggle', id: '1' });
    expect(toggled.ids).toEqual(['2', '1']);
    expect(targetSelectionReducer(toggled, { type: 'toggle', id: '2' }).ids).toEqual(['1']);
    expect(targetSelectionReducer(toggled, { type: 'none' }).ids).toEqual([]);
    expect(targetSelectionReducer(toggled, { type: 'all', ids: ['1', '3'] }).ids).toEqual(['1', '3']);
    expect(targetSelectionReducer(toggled, { type: 'group' })).toBe(toggled);
    expect(targetSelectionReducer(toggled, { type: 'group', ids: [] }).ids).toEqual([]);
    expect(state.ids).toEqual(['1', '2', '3']);
  });

  test('canonicalizes duplicate hardware IDs and rejects non-identities', () => {
    expect(uniqueTargetIds(['01', 1, '2', '', null, undefined, false, {}, NaN])).toEqual(['1', '2']);
    expect(initialize(['1', '2'], { malformed: true }).ids).toEqual([]);
  });
});

describe('scoped target persistence', () => {
  test.each([[[]], [['2', 'removed']]])('round trips saved targets %j without reconciliation', (ids) => {
    const parsed = parseTargetSelection(serializeTargetSelection(initialize(['1'], ids)));
    expect(parsed).toEqual({ ids, valid: true });
    expect(initialize(['1', '3'], parsed.ids).ids).toEqual(ids);
  });

  test('missing and corrupt persistence are distinct; corrupt data fails to empty, not All', () => {
    expect(parseTargetSelection(null)).toBeNull();
    expect(serializeTargetSelection(createTargetSelectionState())).toBeNull();
    ['broken', '', '{}', '{"version":2,"ids":["1"]}', '{"version":1,"ids":[null]}'].forEach((value) => {
      const restored = parseTargetSelection(value);
      expect(restored).toEqual({ ids: [], valid: false });
      expect(initialize(['1', '2'], restored.ids).ids).toEqual([]);
    });
  });

  test('separates deployment, runtime and operator, escaping delimiter collisions', () => {
    const context = { deploymentId: 'site:a', runtimeMode: 'real', operatorId: 'b' };
    const scope = getTargetSelectionStorageScope(context);
    expect(scope.storage).toBe('local');
    expect(new Set([
      scope.key,
      getTargetSelectionStorageScope({ ...context, deploymentId: 'site' }).key,
      getTargetSelectionStorageScope({ ...context, runtimeMode: 'sitl' }).key,
      getTargetSelectionStorageScope({ ...context, operatorId: 'a:b' }).key,
    ]).size).toBe(4);
  });

  test('uses an explicit session discriminator without stable identities; waits for known mode', () => {
    expect(getTargetSelectionStorageScope({ runtimeMode: 'real' })).toBeNull();
    expect(getTargetSelectionStorageScope({ runtimeMode: 'unknown', sessionId: 'one' })).toBeNull();
    const one = getTargetSelectionStorageScope({ runtimeMode: 'real', sessionId: 'one' });
    const two = getTargetSelectionStorageScope({ runtimeMode: 'real', sessionId: 'two' });
    expect(one.storage).toBe('session');
    expect(one.key).not.toBe(two.key);
  });
});
