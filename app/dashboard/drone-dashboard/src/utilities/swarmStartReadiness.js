// Aggregate node decisions only; aircraft admission rules live on the node.
export function swarmStartValidUntil(targets, decisions, requestedAt) {
  return requestedAt + Math.max(0, Math.min(...targets.map((id) => decisions?.[id]?.status === 'ready'
    ? Number(decisions[id].valid_for_ms || 0) : 1000)));
}

export function swarmStartReadiness(targets, decisions, validUntilMs, now = Date.now()) {
  const unknown = { ready: false, label: 'Checking aircraft' };
  if (!targets.length || !decisions || now >= validUntilMs) return unknown;
  for (const id of targets) {
    const decision = decisions[id];
    if (!decision || decision.hw_id !== id) return unknown;
    if (decision.status !== 'ready') return {
      ready: false, label: `${decision.message || 'Checking aircraft'} · Drone ${id}`,
    };
    if (!(decision.valid_for_ms > 0)) return unknown;
  }
  return { ready: true, label: 'Ready' };
}
