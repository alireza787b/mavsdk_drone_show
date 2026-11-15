import { useEffect, useMemo, useRef } from 'react';

// Attention presentation only. Never feed these settled values into admission,
// telemetry clocks, map trust, availability, recipients or flight controllers.
export const LINK_ATTENTION_TIMING = Object.freeze({ promoteMs: 3000, recoverMs: 2000 });

export function settleLinkCondition(previous, present, now, immediate = false, timing = LINK_ATTENTION_TIMING) {
  if (present) {
    const since = previous?.present ? previous.since : now;
    const active = Boolean(immediate || previous?.active || now - since >= timing.promoteMs);
    return { present: true, since, recoverySince: null, active, phase: active ? 'active' : 'pending' };
  }
  if (previous?.active) {
    const recoverySince = previous.recoverySince ?? now;
    if (now - recoverySince < timing.recoverMs) return { ...previous, present: false, recoverySince, phase: 'recovering' };
  }
  return { present: false, active: false, phase: 'clear' };
}

export function fleetAttentionSnapshot(previous, model, resources) {
  const now = resources.nowMs;
  const old = previous?.at <= now ? previous : null;
  const telemetry = settleLinkCondition(old?.telemetry, Boolean(resources.telemetry.error), now,
    !resources.telemetry.response);
  const config = settleLinkCondition(old?.config, Boolean(resources.config.error), now,
    !resources.config.response);
  // Configuration refresh is low-rate: one failed refresh with a retained
  // roster is not an outage lasting until its next scheduled attempt.
  if (resources.config.response && resources.config.error && resources.config.consecutiveFailures === 1) {
    config.active = false;
    config.phase = 'pending';
  }
  const links = new Map();
  const aircraft = model.aircraft.map(item => {
    const issue = item.issues.find(row => row.key === 'telemetry');
    const link = settleLinkCondition(old?.links.get(item.id), Boolean(issue), now, issue?.tone === 'danger');
    const heartbeat = settleLinkCondition(old?.links.get(item.id)?.heartbeat, Boolean(item.availability?.stale), now);
    links.set(item.id, { ...link, heartbeat });
    const issues = item.issues.filter(row => row.key !== 'telemetry' || link.active);
    if (link.phase === 'recovering') issues.push({ key: 'telemetry', tone: 'warning', label: 'Link recovering' });
    return { ...item, issues, rawIssues: item.issues,
      linkAttention: link.phase === 'clear' ? heartbeat.phase : link.phase, attention: issues.length > 0 };
  });
  return { state: { at: now, telemetry, config, links }, telemetry, config,
    model: { ...model, aircraft, byId: new Map(aircraft.map(item => [item.id, item])),
      summary: { ...model.summary, attention: aircraft.filter(item => item.attention).length } } };
}

export default function useFleetAttention(model, resources) {
  const previous = useRef(null);
  const { nowMs } = resources;
  const { error: telemetryError, response: telemetryResponse } = resources.telemetry;
  const { error: configError, response: configResponse, consecutiveFailures: configFailures } = resources.config;
  const result = useMemo(() => fleetAttentionSnapshot(previous.current, model, {
    nowMs, telemetry: { error: telemetryError, response: telemetryResponse }, config: { error: configError, response: configResponse, consecutiveFailures: configFailures },
  }), [model, nowMs, telemetryError, telemetryResponse, configError, configResponse, configFailures]);
  // Commit history only after a committed render; abandoned React renders must
  // not advance warning/recovery clocks. The existing fleet tick drives time.
  useEffect(() => { previous.current = result.state; }, [result]);
  return result;
}
