// Aggregate node decisions only; aircraft admission rules live on the node.
export function swarmStartValidUntil(targets, decisions, requestedAt) {
  return requestedAt + Math.max(0, Math.min(...targets.map((id) => decisions?.[id]?.status === 'ready'
    ? Number(decisions[id].valid_for_ms || 0) : 1000)));
}

export function swarmStartReadiness(targets, decisions, validUntilMs, now = Date.now()) {
  const unknown = { ready: false, label: 'Checking aircraft' };
  if (!targets.length || !decisions) return unknown;
  // Keep a named unavailable/blocked report visible even when another ready
  // member's short execution lease expired. This can never enable a command.
  for (const id of targets) {
    const decision = decisions[id];
    if (decision?.hw_id === id && decision.status !== 'ready') return {
      ready: false, label: `${decision.message || 'Readiness unavailable'} · Drone ${id}`,
    };
  }
  if (now >= validUntilMs) return { ready: false, label: 'Refreshing readiness' };
  for (const id of targets) {
    const decision = decisions[id];
    if (!decision || decision.hw_id !== id) return unknown;
    if (!(decision.valid_for_ms > 0)) return unknown;
  }
  return { ready: true, label: 'Ready' };
}
