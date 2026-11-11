import { normalizeComparableId } from '../../utilities/missionIdentityUtils';

/** Hardware identities only; never substitute a position slot. Retains input order. */
export function uniqueTargetIds(values = []) {
  if (!Array.isArray(values)) return [];
  return Array.from(new Set(values
    .filter((value) => typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value)))
    .map((value) => normalizeComparableId(value))
    .filter(Boolean)));
}

export function createTargetSelectionState() {
  return { initialized: false, ids: [] };
}

/** No telemetry/filter/reconcile actions: only explicit operator actions change membership. */
export function targetSelectionReducer(state, action) {
  switch (action.type) {
    case 'initialize': {
      if (state.initialized || !Array.isArray(action.configuredIds)) return state;
      const configuredIds = uniqueTargetIds(action.configuredIds);
      const defaults = action.defaultIds === undefined ? configuredIds
        : uniqueTargetIds(action.defaultIds).filter((id) => configuredIds.includes(id));
      return {
        initialized: true,
        ids: uniqueTargetIds(action.savedIds === undefined ? defaults : action.savedIds),
      };
    }
    case 'all':
    case 'group':
      if (!state.initialized || !Array.isArray(action.ids)) return state;
      return { initialized: true, ids: uniqueTargetIds(action.ids) };
    case 'none':
      return state.initialized ? { initialized: true, ids: [] } : state;
    case 'toggle': {
      const [id] = uniqueTargetIds([action.id]);
      if (!state.initialized || !id) return state;
      return {
        initialized: true,
        ids: state.ids.includes(id) ? state.ids.filter((value) => value !== id) : [...state.ids, id],
      };
    }
    default:
      return state;
  }
}

export function getTargetSelectionReview(state, knownIds, visibleIds = knownIds) {
  const known = new Set(uniqueTargetIds(knownIds));
  const visible = new Set(uniqueTargetIds(visibleIds));
  return {
    count: state.ids.length,
    unresolvedIds: state.ids.filter((id) => !known.has(id)),
    hiddenIds: state.ids.filter((id) => known.has(id) && !visible.has(id)),
  };
}

/**
 * The caller owns storage access. A stable deployment/operator pair may use localStorage;
 * otherwise require a session discriminator and use sessionStorage. Unknown runtime
 * mode must not share selections with REAL/SITL. Return null until context is known.
 */
export function getTargetSelectionStorageScope({ deploymentId, runtimeMode, operatorId, sessionId } = {}) {
  if (!['real', 'sitl'].includes(runtimeMode)) return null;
  const deployment = String(deploymentId || '').trim();
  const operator = String(operatorId || '').trim();
  const session = String(sessionId || '').trim();
  const persistent = Boolean(deployment && operator);
  if (!persistent && !session) return null;
  const parts = persistent
    ? ['operator', deployment, runtimeMode, operator]
    : ['session', deployment, runtimeMode, operator, session];
  return {
    storage: persistent ? 'local' : 'session',
    key: `mds:fleet-targets:v1:${parts.map(encodeURIComponent).join(':')}`,
  };
}

export function serializeTargetSelection(state) {
  if (!state.initialized) return null;
  return JSON.stringify({ version: 1, ids: uniqueTargetIds(state.ids) });
}

/** Missing => null; malformed saved data => empty, invalid (never widen to All). */
export function parseTargetSelection(serialized) {
  if (serialized === null || serialized === undefined) return null;
  try {
    const payload = JSON.parse(serialized);
    if (payload?.version !== 1 || !Array.isArray(payload.ids)
      || payload.ids.some((id) => typeof id !== 'string' || !id.trim())) {
      return { ids: [], valid: false };
    }
    return { ids: uniqueTargetIds(payload.ids), valid: true };
  } catch {
    return { ids: [], valid: false };
  }
}
