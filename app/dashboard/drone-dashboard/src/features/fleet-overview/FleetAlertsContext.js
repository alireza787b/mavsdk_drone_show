import React, { createContext, useCallback, useContext, useMemo, useReducer } from 'react';

export const FLEET_ALERT_LIMITS = Object.freeze({ aircraft: 100, perAircraft: 5, recent: 50 });
const MAX_ACTIVE = FLEET_ALERT_LIMITS.aircraft * FLEET_ALERT_LIMITS.perAircraft + 1;
const GCS_CONDITION = 'gcs:outage';
const LINK_CONDITIONS = new Set(['telemetry', 'boot']);
const FleetAlertsContext = createContext(null);

export function createFleetAlertsState() {
  return { active: [], heightReviews: [], recent: [], monitoring: false, sourceError: false, sourceRecovering: false,
    observedAtMs: null, nextEpisode: 1, omittedAircraft: 0, omittedConditions: 0 };
}

/** Local condition evidence only: not a server journal, readiness model or admission gate. */
export function fleetAlertsReducer(state, action) {
  if (action.type === 'source-unavailable') return { ...state, monitoring: false };
  if (action.type === 'seen') return { ...state, active: state.active.map((episode) => (
    episode.id === action.id ? { ...episode, seen: true } : episode
  )) };
  if (action.type !== 'snapshot' || !Number.isFinite(action.snapshot?.observedAtMs)) return state;
  const { aircraft = [], sourceError, sourceRecovering, observedAtMs } = action.snapshot;
  if (state.observedAtMs !== null && observedAtMs < state.observedAtMs) return state;
  let nextEpisode = state.nextEpisode;
  const previous = new Map(state.active.map((episode) => [episode.condition, episode]));
  const observe = (condition, fields) => {
    const existing = previous.get(condition);
    return { ...existing, ...fields, condition,
      id: existing?.id || `fleet-alert-${nextEpisode++}`,
      firstObservedAtMs: existing?.firstObservedAtMs ?? observedAtMs,
      lastObservedAtMs: observedAtMs, clearedAtMs: null,
      seen: existing?.seen || false, observed: true };
  };
  if (sourceError && !sourceRecovering) {
    const outage = observe(GCS_CONDITION, { aircraftId: null, aircraftLabel: 'GCS',
      issueKey: 'outage', tone: 'danger', reason: 'Telemetry source unavailable' });
    return { ...state, heightReviews: [], monitoring: true, sourceError: true, sourceRecovering: false, observedAtMs, nextEpisode,
      active: [outage, ...state.active.filter((entry) => entry.condition !== GCS_CONDITION)
        .map((entry) => ({ ...entry, observed: false }))].slice(0, MAX_ACTIVE) };
  }

  const uniqueAircraft = new Map();
  (Array.isArray(aircraft) ? aircraft : []).forEach((item) => {
    if (typeof item?.id === 'string' && item.id && !uniqueAircraft.has(item.id)) uniqueAircraft.set(item.id, item);
  });
  const roster = uniqueAircraft;
  const incoming = new Map();
  if (sourceError && sourceRecovering) incoming.set(GCS_CONDITION, observe(GCS_CONDITION, {
    aircraftId: null, aircraftLabel: 'GCS', issueKey: 'outage', tone: 'warning', reason: 'Telemetry source recovering',
  }));
  const truncated = new Set();
  let omittedConditions = 0;
  roster.forEach((item, id) => {
    const issues = new Map();
    (Array.isArray(item.issues) ? item.issues : []).forEach((issue) => {
      if (typeof issue?.key !== 'string' || !issue.key || typeof issue.label !== 'string' || !issue.label.trim()) return;
      if (!item.current && !LINK_CONDITIONS.has(issue.key)) return;
      if (!issues.has(issue.key)) issues.set(issue.key, issue);
    });
    if (issues.size > FLEET_ALERT_LIMITS.perAircraft) truncated.add(id);
    omittedConditions += Math.max(0, issues.size - FLEET_ALERT_LIMITS.perAircraft);
    Array.from(issues.values()).slice(0, FLEET_ALERT_LIMITS.perAircraft).forEach((issue) => {
      const condition = JSON.stringify([id, issue.key]);
      incoming.set(condition, observe(condition, { aircraftId: id,
        aircraftLabel: typeof item.label === 'string' ? item.label : `Aircraft ${id}`,
        issueKey: issue.key, reason: issue.label.slice(0, 400), tone: issue.tone === 'danger' ? 'danger' : 'warning' }));
    });
  });

  const cleared = [], retained = [];
  state.active.forEach((episode) => {
    if (incoming.has(episode.condition)) return;
    const item = roster.get(episode.aircraftId);
    const hasClearingEvidence = episode.condition === GCS_CONDITION
      || (item && !truncated.has(item.id) && (item.current || LINK_CONDITIONS.has(episode.issueKey)));
    if (hasClearingEvidence) cleared.push({ ...episode, observed: false, clearedAtMs: observedAtMs });
    else retained.push({ ...episode, observed: false });
  });
  const active = [...incoming.values()];
  // Count all live aircraft. Only the retained, unconfirmed history is capped.
  const byAircraft = new Map();
  for (const entry of active) byAircraft.set(entry.aircraftId, (byAircraft.get(entry.aircraftId) || 0) + 1);
  const omittedIds = new Set();
  for (const episode of retained) {
    const count = byAircraft.get(episode.aircraftId) || 0;
    if ((!count && byAircraft.size >= FLEET_ALERT_LIMITS.aircraft) || count >= FLEET_ALERT_LIMITS.perAircraft) {
      omittedConditions += 1;
      if (!count) omittedIds.add(episode.aircraftId);
      continue;
    }
    byAircraft.set(episode.aircraftId, count + 1);
    active.push(episode);
  }
  const previousHeights = new Set((state.heightReviews || []).map(review => review.id));
  const heightReviews = (action.snapshot.heightReviews || []).filter(review => review.active
    || (!review.complete && previousHeights.has(review.id)));
  return { active, heightReviews,
    recent: [...cleared.reverse(), ...state.recent].slice(0, FLEET_ALERT_LIMITS.recent),
    monitoring: true, sourceError: Boolean(sourceError), sourceRecovering: Boolean(sourceError && sourceRecovering), observedAtMs, nextEpisode,
    omittedAircraft: omittedIds.size,
    omittedConditions };
}

/** Remount with a runtime/operator key at the shell boundary to isolate sessions. */
export function FleetAlertsProvider({ children }) {
  const [state, dispatch] = useReducer(fleetAlertsReducer, undefined, createFleetAlertsState);
  const publishSnapshot = useCallback((snapshot) => dispatch({ type: 'snapshot', snapshot }), []);
  const sourceUnavailable = useCallback(() => dispatch({ type: 'source-unavailable' }), []);
  const markSeen = useCallback((id) => dispatch({ type: 'seen', id }), []);
  const value = useMemo(() => ({ state, publishSnapshot, sourceUnavailable, markSeen }), [state, publishSnapshot, sourceUnavailable, markSeen]);
  return <FleetAlertsContext.Provider value={value}>{children}</FleetAlertsContext.Provider>;
}

export function useFleetAlerts() {
  const context = useContext(FleetAlertsContext);
  if (!context) throw new Error('useFleetAlerts requires FleetAlertsProvider');
  return context;
}
