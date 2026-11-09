import React, { createContext, useCallback, useContext, useMemo, useReducer } from 'react';

export const FLEET_ALERT_LIMITS = Object.freeze({ aircraft: 100, perAircraft: 5, recent: 50 });
const MAX_ACTIVE = FLEET_ALERT_LIMITS.aircraft * FLEET_ALERT_LIMITS.perAircraft + 1;
const GCS_CONDITION = 'gcs:outage';
const LINK_CONDITIONS = new Set(['telemetry', 'boot']);
const FleetAlertsContext = createContext(null);

export function createFleetAlertsState() {
  return { active: [], recent: [], monitoring: false, sourceError: false,
    observedAtMs: null, nextEpisode: 1, omittedAircraft: 0, omittedConditions: 0 };
}

/** Local condition evidence only: not a server journal, readiness model or admission gate. */
export function fleetAlertsReducer(state, action) {
  if (action.type === 'source-unavailable') return { ...state, monitoring: false };
  if (action.type === 'seen') return { ...state, active: state.active.map((episode) => (
    episode.id === action.id ? { ...episode, seen: true } : episode
  )) };
  if (action.type !== 'snapshot' || !Number.isFinite(action.snapshot?.observedAtMs)) return state;
  const { aircraft = [], sourceError, observedAtMs } = action.snapshot;
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
  if (sourceError) {
    const outage = observe(GCS_CONDITION, { aircraftId: null, aircraftLabel: 'GCS',
      issueKey: 'outage', tone: 'danger', reason: 'Telemetry source unavailable' });
    return { ...state, monitoring: true, sourceError: true, observedAtMs, nextEpisode,
      active: [outage, ...state.active.filter((entry) => entry.condition !== GCS_CONDITION)
        .map((entry) => ({ ...entry, observed: false }))].slice(0, MAX_ACTIVE) };
  }

  const uniqueAircraft = new Map();
  (Array.isArray(aircraft) ? aircraft : []).forEach((item) => {
    if (typeof item?.id === 'string' && item.id && !uniqueAircraft.has(item.id)) uniqueAircraft.set(item.id, item);
  });
  const roster = new Map(Array.from(uniqueAircraft).slice(0, FLEET_ALERT_LIMITS.aircraft));
  const incoming = new Map();
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
  const activeIds = new Set(active.map((episode) => episode.aircraftId));
  const omittedIds = new Set();
  retained.forEach((episode) => {
    if ((!activeIds.has(episode.aircraftId) && activeIds.size >= FLEET_ALERT_LIMITS.aircraft)
      || active.filter((item) => item.aircraftId === episode.aircraftId).length >= FLEET_ALERT_LIMITS.perAircraft) {
      omittedConditions += 1;
      if (!activeIds.has(episode.aircraftId)) omittedIds.add(episode.aircraftId);
      return;
    }
    activeIds.add(episode.aircraftId);
    active.push(episode);
  });
  return { active: active.slice(0, MAX_ACTIVE),
    recent: [...cleared.reverse(), ...state.recent].slice(0, FLEET_ALERT_LIMITS.recent),
    monitoring: true, sourceError: false, observedAtMs, nextEpisode,
    omittedAircraft: Math.max(0, uniqueAircraft.size - FLEET_ALERT_LIMITS.aircraft) + omittedIds.size,
    omittedConditions: omittedConditions + Math.max(0, active.length - MAX_ACTIVE) };
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
