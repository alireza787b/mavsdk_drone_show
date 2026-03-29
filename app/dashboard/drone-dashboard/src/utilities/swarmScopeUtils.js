const normalizeDroneId = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

export function buildNormalizedIdSet(values = []) {
  return new Set(
    values
      .map((value) => normalizeDroneId(value))
      .filter((value) => value !== null),
  );
}

export function buildNormalizedFollowMap(followMap = {}) {
  const normalized = new Map();

  Object.entries(followMap).forEach(([droneId, leaderId]) => {
    const normalizedDroneId = normalizeDroneId(droneId);
    const normalizedLeaderId = normalizeDroneId(leaderId) ?? 0;
    if (normalizedDroneId === null) {
      return;
    }
    normalized.set(normalizedDroneId, normalizedLeaderId);
  });

  return normalized;
}

export function getClusterMemberIds(cluster = {}) {
  return [
    cluster.leader_id,
    ...(Array.isArray(cluster.follower_ids) ? cluster.follower_ids : []),
  ]
    .map((value) => normalizeDroneId(value))
    .filter((value) => value !== null);
}

export function buildLeaderChainSelectionIssues({ followMap = {}, activeIds = [] } = {}) {
  const normalizedFollowMap = followMap instanceof Map ? followMap : buildNormalizedFollowMap(followMap);
  const activeSet = buildNormalizedIdSet(activeIds);
  const issues = [];

  activeSet.forEach((droneId) => {
    if (!normalizedFollowMap.has(droneId)) {
      issues.push({
        droneId,
        issue: 'missing_swarm_assignment',
      });
      return;
    }

    let currentId = droneId;
    const visited = new Set([droneId]);

    while (true) {
      const leaderId = normalizedFollowMap.get(currentId);
      if (leaderId === undefined) {
        issues.push({
          droneId,
          currentId,
          issue: 'missing_swarm_assignment',
        });
        break;
      }

      if (leaderId === 0) {
        break;
      }

      if (visited.has(leaderId)) {
        issues.push({
          droneId,
          leaderId,
          issue: 'circular_leader_chain',
        });
        break;
      }

      if (!activeSet.has(leaderId)) {
        issues.push({
          droneId,
          leaderId,
          issue: 'leader_not_in_active_mission_set',
        });
        break;
      }

      visited.add(leaderId);
      currentId = leaderId;
    }
  });

  return issues;
}
