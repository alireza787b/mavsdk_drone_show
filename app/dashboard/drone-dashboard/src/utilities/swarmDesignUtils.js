import { getPromotedMissionConfigField } from './missionConfigFields';
import { formatCompactDroneIdentity, formatDroneLabel, formatShowSlotLabel } from './missionIdentityUtils';

export const TOP_LEADER_FOLLOW_VALUE = '0';

const VALID_FRAMES = new Set(['ned', 'body']);
const ROLE_ORDER = {
  topLeader: 0,
  relayLeader: 1,
  follower: 2,
};

const BLOCKING_WARNING_CODES = new Set([
  'self-follow',
  'missing-leader',
  'cycle',
]);

function normalizeNumericString(value, fallback = '') {
  if (value === undefined || value === null || value === '') {
    return fallback;
  }

  const parsed = Number.parseInt(String(value), 10);
  if (Number.isNaN(parsed)) {
    return fallback || String(value).trim();
  }

  return String(parsed);
}

function normalizeOffset(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function sortIds(leftId, rightId) {
  return Number(leftId) - Number(rightId);
}

function createDefaultAssignment(hwId) {
  return {
    hw_id: normalizeNumericString(hwId),
    follow: TOP_LEADER_FOLLOW_VALUE,
    offset_x: 0,
    offset_y: 0,
    offset_z: 0,
    frame: 'ned',
  };
}

export function normalizeConfigDrone(entry = {}) {
  const hwId = normalizeNumericString(entry.hw_id);
  if (!hwId) {
    return null;
  }

  const posId = normalizeNumericString(entry.pos_id, hwId);

  return {
    ...entry,
    hw_id: hwId,
    pos_id: posId,
    ip: entry.ip || '',
  };
}

export function normalizeSwarmAssignment(entry = {}, fallbackHwId = '') {
  const hwId = normalizeNumericString(entry.hw_id, normalizeNumericString(fallbackHwId));
  if (!hwId) {
    return null;
  }

  const follow = normalizeNumericString(entry.follow, TOP_LEADER_FOLLOW_VALUE) || TOP_LEADER_FOLLOW_VALUE;
  const frame = VALID_FRAMES.has(String(entry.frame).trim()) ? String(entry.frame).trim() : 'ned';

  return {
    hw_id: hwId,
    follow,
    offset_x: normalizeOffset(entry.offset_x),
    offset_y: normalizeOffset(entry.offset_y),
    offset_z: normalizeOffset(entry.offset_z),
    frame,
  };
}

function assignmentToComparableString(assignment) {
  const normalized = normalizeSwarmAssignment(assignment);
  if (!normalized) {
    return '';
  }

  return JSON.stringify(normalized);
}

function buildFollowerMap(assignments) {
  const followerMap = new Map();
  const assignmentMap = new Map(assignments.map((assignment) => [assignment.hw_id, assignment]));

  assignments.forEach((assignment) => {
    if (
      assignment.follow === TOP_LEADER_FOLLOW_VALUE ||
      assignment.follow === assignment.hw_id ||
      !assignmentMap.has(assignment.follow)
    ) {
      return;
    }

    const directFollowers = followerMap.get(assignment.follow) || [];
    directFollowers.push(assignment.hw_id);
    followerMap.set(assignment.follow, directFollowers);
  });

  followerMap.forEach((followers, leaderId) => {
    followerMap.set(leaderId, [...followers].sort(sortIds));
  });

  return followerMap;
}

function detectCycleIds(assignmentMap) {
  const states = new Map();
  const cycleIds = new Set();
  const stack = [];

  function visit(droneId) {
    const state = states.get(droneId);
    if (state === 'done') {
      return;
    }

    if (state === 'visiting') {
      const startIndex = stack.indexOf(droneId);
      stack.slice(startIndex).forEach((id) => cycleIds.add(id));
      return;
    }

    states.set(droneId, 'visiting');
    stack.push(droneId);

    const assignment = assignmentMap.get(droneId);
    if (assignment && assignment.follow !== TOP_LEADER_FOLLOW_VALUE && assignmentMap.has(assignment.follow)) {
      visit(assignment.follow);
    }

    stack.pop();
    states.set(droneId, 'done');
  }

  assignmentMap.forEach((_, droneId) => visit(droneId));

  return cycleIds;
}

function getClusterResolution(droneId, assignmentMap, cycleIds) {
  if (cycleIds.has(droneId)) {
    return {
      clusterId: 'attention',
      clusterRootId: null,
      clusterType: 'attention',
    };
  }

  let currentId = droneId;
  const visited = new Set();

  while (assignmentMap.has(currentId) && !visited.has(currentId)) {
    visited.add(currentId);
    const current = assignmentMap.get(currentId);

    if (current.follow === TOP_LEADER_FOLLOW_VALUE) {
      return {
        clusterId: current.hw_id,
        clusterRootId: current.hw_id,
        clusterType: 'cluster',
      };
    }

    if (!assignmentMap.has(current.follow) || cycleIds.has(current.follow)) {
      return {
        clusterId: 'attention',
        clusterRootId: null,
        clusterType: 'attention',
      };
    }

    currentId = current.follow;
  }

  return {
    clusterId: 'attention',
    clusterRootId: null,
    clusterType: 'attention',
  };
}

function getDepth(drone, assignmentMap, cycleIds, depthCache) {
  if (depthCache.has(drone.hw_id)) {
    return depthCache.get(drone.hw_id);
  }

  if (drone.follow === TOP_LEADER_FOLLOW_VALUE || cycleIds.has(drone.hw_id) || !assignmentMap.has(drone.follow)) {
    depthCache.set(drone.hw_id, 0);
    return 0;
  }

  const parentDepth = getDepth(assignmentMap.get(drone.follow), assignmentMap, cycleIds, depthCache);
  const depth = parentDepth + 1;
  depthCache.set(drone.hw_id, depth);
  return depth;
}

function getRoleKey(drone, followerMap) {
  if (drone.follow === TOP_LEADER_FOLLOW_VALUE) {
    return 'topLeader';
  }

  return followerMap.has(drone.hw_id) ? 'relayLeader' : 'follower';
}

function getRoleLabel(roleKey) {
  if (roleKey === 'topLeader') {
    return 'Top Leader';
  }

  if (roleKey === 'relayLeader') {
    return 'Relay Leader';
  }

  return 'Follower';
}

function getRoleSummary(roleKey, drone, directFollowers) {
  if (roleKey === 'topLeader') {
    if (directFollowers.length === 0) {
      return 'Independent leader';
    }

    return `Independent leader for ${directFollowers.length} drone${directFollowers.length === 1 ? '' : 's'}`;
  }

  if (roleKey === 'relayLeader') {
    return `Following ${formatDroneLabel(drone.follow)} and relaying to ${directFollowers.length} drone${directFollowers.length === 1 ? '' : 's'}`;
  }

  return `Maintaining formation from ${formatDroneLabel(drone.follow)}`;
}

function getOffsetAxisLabels(frame) {
  if (frame === 'body') {
    return {
      x: 'Forward',
      y: 'Right',
      z: 'Up',
      frameLabel: 'Leader body frame',
      frameDescription: 'Offsets move with the leader heading.',
    };
  }

  return {
    x: 'North',
    y: 'East',
    z: 'Up',
    frameLabel: 'Geographic frame',
    frameDescription: 'Offsets stay aligned to the North/East axes.',
  };
}

function formatSignedOffset(value) {
  const numeric = Number.isFinite(value) ? value : 0;
  const prefix = numeric > 0 ? '+' : '';
  return `${prefix}${numeric.toFixed(1)} m`;
}

export function formatOffsetSummary(drone) {
  const labels = getOffsetAxisLabels(drone.frame);
  if (drone.follow === TOP_LEADER_FOLLOW_VALUE) {
    return 'Leader anchor at cluster origin';
  }

  return `${labels.x} ${formatSignedOffset(drone.offset_x)} · ${labels.y} ${formatSignedOffset(drone.offset_y)} · ${labels.z} ${formatSignedOffset(drone.offset_z)}`;
}

function compareDrones(leftDrone, rightDrone) {
  const roleOrder = ROLE_ORDER[leftDrone.role] - ROLE_ORDER[rightDrone.role];
  if (roleOrder !== 0) {
    return roleOrder;
  }

  const depthOrder = leftDrone.depth - rightDrone.depth;
  if (depthOrder !== 0) {
    return depthOrder;
  }

  return sortIds(leftDrone.hw_id, rightDrone.hw_id);
}

function buildSummary(drones, clusters) {
  const summary = {
    totalDrones: drones.length,
    topLeaderCount: 0,
    relayLeaderCount: 0,
    followerCount: 0,
    roleSwapCount: 0,
    attentionCount: 0,
    blockingIssueCount: 0,
    clusterCount: clusters.filter((cluster) => cluster.type === 'cluster').length,
  };

  drones.forEach((drone) => {
    if (drone.role === 'topLeader') {
      summary.topLeaderCount += 1;
    } else if (drone.role === 'relayLeader') {
      summary.relayLeaderCount += 1;
    } else {
      summary.followerCount += 1;
    }

    if (drone.isRoleSwap) {
      summary.roleSwapCount += 1;
    }

    if (drone.warnings.length > 0) {
      summary.attentionCount += 1;
    }

    if (drone.hasBlockingWarnings) {
      summary.blockingIssueCount += 1;
    }
  });

  return summary;
}

function buildFollowOptions(drones) {
  return [...drones]
    .sort(compareDrones)
    .map((drone) => ({
      value: drone.hw_id,
      label: `${formatCompactDroneIdentity(drone.pos_id, drone.hw_id)} · ${drone.roleLabel}`,
    }));
}

export function buildWorkingSwarmAssignments(configData = [], swarmData = []) {
  const normalizedConfig = configData
    .map((entry) => normalizeConfigDrone(entry))
    .filter(Boolean);
  const normalizedSwarm = swarmData
    .map((entry) => normalizeSwarmAssignment(entry))
    .filter(Boolean);

  const configMap = new Map(normalizedConfig.map((entry) => [entry.hw_id, entry]));
  const swarmMap = new Map(normalizedSwarm.map((entry) => [entry.hw_id, entry]));

  if (normalizedConfig.length === 0) {
    return {
      assignments: normalizedSwarm,
      syncChanges: {
        addedIds: [],
        removedIds: [],
      },
    };
  }

  const assignments = normalizedConfig.map((configEntry) => swarmMap.get(configEntry.hw_id) || createDefaultAssignment(configEntry.hw_id));
  const addedIds = normalizedConfig
    .filter((configEntry) => !swarmMap.has(configEntry.hw_id))
    .map((configEntry) => configEntry.hw_id);
  const removedIds = normalizedSwarm
    .filter((assignment) => !configMap.has(assignment.hw_id))
    .map((assignment) => assignment.hw_id);

  return {
    assignments,
    syncChanges: {
      addedIds,
      removedIds,
    },
  };
}

export function getDirtyAssignmentIds(currentAssignments = [], baselineAssignments = []) {
  const baselineMap = new Map(
    baselineAssignments
      .map((assignment) => normalizeSwarmAssignment(assignment))
      .filter(Boolean)
      .map((assignment) => [assignment.hw_id, assignmentToComparableString(assignment)])
  );

  return currentAssignments
    .map((assignment) => normalizeSwarmAssignment(assignment))
    .filter(Boolean)
    .filter((assignment) => baselineMap.get(assignment.hw_id) !== assignmentToComparableString(assignment))
    .map((assignment) => assignment.hw_id);
}

export function buildSwarmViewModel(assignments = [], configData = []) {
  const normalizedAssignments = assignments
    .map((entry) => normalizeSwarmAssignment(entry))
    .filter(Boolean);
  const normalizedConfig = configData
    .map((entry) => normalizeConfigDrone(entry))
    .filter(Boolean);

  const configMap = new Map(normalizedConfig.map((entry) => [entry.hw_id, entry]));
  const assignmentMap = new Map(normalizedAssignments.map((entry) => [entry.hw_id, entry]));
  const followerMap = buildFollowerMap(normalizedAssignments);
  const cycleIds = detectCycleIds(assignmentMap);
  const depthCache = new Map();

  const drones = normalizedAssignments.map((drone) => {
    const configEntry = configMap.get(drone.hw_id) || {};
    const directFollowers = followerMap.get(drone.hw_id) || [];
    const role = getRoleKey(drone, followerMap);
    const clusterResolution = getClusterResolution(drone.hw_id, assignmentMap, cycleIds);
    const warnings = [];

    if (drone.follow === drone.hw_id) {
      warnings.push({
        code: 'self-follow',
        severity: 'error',
        message: `${formatDroneLabel(drone.hw_id)} is configured to follow itself.`,
      });
    }

    if (drone.follow !== TOP_LEADER_FOLLOW_VALUE && !assignmentMap.has(drone.follow)) {
      warnings.push({
        code: 'missing-leader',
        severity: 'error',
        message: `Assigned leader ${formatDroneLabel(drone.follow)} is not present in the active fleet configuration.`,
      });
    }

    if (cycleIds.has(drone.hw_id)) {
      warnings.push({
        code: 'cycle',
        severity: 'error',
        message: 'This follow chain contains a loop. Break the loop before saving.',
      });
    }

    if (
      drone.follow === TOP_LEADER_FOLLOW_VALUE &&
      (drone.offset_x !== 0 || drone.offset_y !== 0 || drone.offset_z !== 0)
    ) {
      warnings.push({
        code: 'leader-offset-ignored',
        severity: 'note',
        message: 'Leader offsets are ignored while the drone is acting as an independent leader.',
      });
    }

    const axisLabels = getOffsetAxisLabels(drone.frame);
    const posId = configEntry.pos_id || drone.hw_id;
    const isRoleSwap = posId !== drone.hw_id;
    const followTarget = assignmentMap.get(drone.follow);
    const depth = getDepth(drone, assignmentMap, cycleIds, depthCache);
    const promotedField = getPromotedMissionConfigField(configEntry);
    const alias = promotedField?.displayValue && promotedField.displayValue !== 'Not set'
      ? promotedField.displayValue
      : '';
    const hardwareLabel = formatDroneLabel(drone.hw_id);
    const slotLabel = formatShowSlotLabel(posId);

    return {
      ...drone,
      pos_id: posId,
      ip: configEntry.ip || '',
      mavlink_port: configEntry.mavlink_port || '',
      role,
      roleLabel: getRoleLabel(role),
      roleSummary: getRoleSummary(role, drone, directFollowers),
      directFollowers,
      directFollowerCount: directFollowers.length,
      followTargetExists: Boolean(followTarget),
      followTargetPosId: followTarget ? configMap.get(followTarget.hw_id)?.pos_id || followTarget.hw_id : null,
      isRoleSwap,
      warnings,
      hasWarnings: warnings.length > 0,
      hasBlockingWarnings: warnings.some((warning) => BLOCKING_WARNING_CODES.has(warning.code)),
      axisLabels,
      frameLabel: axisLabels.frameLabel,
      frameDescription: axisLabels.frameDescription,
      offsetSummary: formatOffsetSummary(drone),
      clusterId: clusterResolution.clusterId,
      clusterRootId: clusterResolution.clusterRootId,
      clusterType: clusterResolution.clusterType,
      depth,
      alias,
      aliasLabel: promotedField?.label || null,
      hardwareLabel,
      slotLabel,
      title: alias || hardwareLabel,
      subtitle: alias ? `${hardwareLabel} · ${slotLabel}` : slotLabel,
    };
  });

  const dronesById = Object.fromEntries(drones.map((drone) => [drone.hw_id, drone]));

  const clusterMap = new Map();
  drones.forEach((drone) => {
    const clusterId = drone.clusterId;
    const existingCluster = clusterMap.get(clusterId) || {
      id: clusterId,
      type: drone.clusterType,
      leaderId: drone.clusterRootId,
      drones: [],
      warningCount: 0,
    };

    existingCluster.drones.push(drone);
    if (drone.warnings.length > 0) {
      existingCluster.warningCount += 1;
    }

    clusterMap.set(clusterId, existingCluster);
  });

  const clusters = [...clusterMap.values()]
    .map((cluster) => {
      const sortedDrones = [...cluster.drones].sort(compareDrones);
      const leaderDrone = cluster.leaderId ? dronesById[cluster.leaderId] : null;
      const counts = {
        total: sortedDrones.length,
        relayLeaders: sortedDrones.filter((drone) => drone.role === 'relayLeader').length,
        followers: sortedDrones.filter((drone) => drone.role === 'follower').length,
      };
      const leaderIdentity = leaderDrone
        ? formatCompactDroneIdentity(
            leaderDrone.pos_id,
            leaderDrone.hw_id,
            formatDroneLabel(leaderDrone?.hw_id || cluster.leaderId, 'Leader')
          )
        : formatDroneLabel(cluster.leaderId, 'Leader');

      return {
        ...cluster,
        drones: sortedDrones,
        title: cluster.type === 'cluster'
          ? `${leaderIdentity} cluster`
          : 'Needs review',
        subtitle: cluster.type === 'cluster'
          ? `Top-leader cluster · ${counts.total} drone${counts.total === 1 ? '' : 's'}`
          : 'Assignments that cannot be executed safely until corrected',
        counts,
      };
    })
    .sort((leftCluster, rightCluster) => {
      if (leftCluster.type !== rightCluster.type) {
        return leftCluster.type === 'cluster' ? -1 : 1;
      }

      if (leftCluster.type === 'attention') {
        return 0;
      }

      return sortIds(leftCluster.leaderId, rightCluster.leaderId);
    });

  const summary = buildSummary(drones, clusters);
  const followOptions = buildFollowOptions(drones);
  const attentionItems = drones.flatMap((drone) =>
    drone.warnings.map((warning) => ({
      ...warning,
      droneId: drone.hw_id,
      droneTitle: drone.title,
    }))
  );

  return {
    drones,
    dronesById,
    clusters,
    summary,
    followOptions,
    attentionItems,
  };
}

function calculateClusterOffset(droneId, assignmentMap, visited = new Set()) {
  if (!assignmentMap.has(droneId) || visited.has(droneId)) {
    return {
      north: 0,
      east: 0,
      up: 0,
    };
  }

  const drone = assignmentMap.get(droneId);
  if (drone.follow === TOP_LEADER_FOLLOW_VALUE) {
    return {
      north: 0,
      east: 0,
      up: 0,
    };
  }

  visited.add(droneId);
  const leaderOffset = calculateClusterOffset(drone.follow, assignmentMap, visited);
  visited.delete(droneId);

  return {
    north: leaderOffset.north + drone.offset_x,
    east: leaderOffset.east + drone.offset_y,
    up: leaderOffset.up + drone.offset_z,
  };
}

export function calculateClusterPlotData(assignments = [], configData = [], clusterId = null) {
  const viewModel = buildSwarmViewModel(assignments, configData);
  const executableClusters = viewModel.clusters.filter((candidate) => candidate.type === 'cluster');
  const cluster = executableClusters.find((candidate) => candidate.id === clusterId)
    || executableClusters[0]
    || null;

  if (!cluster) {
    return {
      clusterId: null,
      data: [],
      clusters: executableClusters,
      title: '',
      description: '',
    };
  }

  if (clusterId === 'all') {
    const data = executableClusters.flatMap((currentCluster) => {
      const assignmentMap = new Map(
        currentCluster.drones
          .map((drone) => normalizeSwarmAssignment(drone))
          .filter(Boolean)
          .map((drone) => [drone.hw_id, drone])
      );

      return currentCluster.drones.map((drone) => {
        const offset = calculateClusterOffset(drone.hw_id, assignmentMap);
        return {
          hw_id: drone.hw_id,
          pos_id: drone.pos_id,
          follow: drone.follow,
          role: drone.role,
          title: drone.title,
          subtitle: drone.subtitle,
          clusterId: currentCluster.id,
          clusterTitle: currentCluster.title,
          x: offset.east,
          y: offset.north,
          z: offset.up,
        };
      });
    });

    const totalDrones = executableClusters.reduce((sum, currentCluster) => sum + currentCluster.counts.total, 0);

    return {
      clusterId: 'all',
      data,
      clusters: executableClusters,
      title: 'All executable clusters',
      description: `${executableClusters.length} clusters · ${totalDrones} drones · overlaid on shared leader origin`,
    };
  }

  const assignmentMap = new Map(
    cluster.drones
      .map((drone) => normalizeSwarmAssignment(drone))
      .filter(Boolean)
      .map((drone) => [drone.hw_id, drone])
  );

  const data = cluster.drones.map((drone) => {
    const offset = calculateClusterOffset(drone.hw_id, assignmentMap);
    return {
      hw_id: drone.hw_id,
      pos_id: drone.pos_id,
      follow: drone.follow,
      role: drone.role,
      title: drone.title,
      subtitle: drone.subtitle,
      x: offset.east,
      y: offset.north,
      z: offset.up,
    };
  });

  return {
    clusterId: cluster.id,
    data,
    clusters: executableClusters,
    title: cluster.title,
    description: cluster.subtitle,
  };
}

export function buildClusterScopeOptions(clusters = [], fallbackTotal = 0) {
  const executableClusters = clusters.filter((cluster) => cluster.type === 'cluster');
  const attentionCluster = clusters.find((cluster) => cluster.type === 'attention') || null;
  const totalDrones = fallbackTotal || clusters.reduce((sum, cluster) => sum + (cluster.counts?.total || cluster.drones?.length || 0), 0);

  const options = [
    {
      id: 'all',
      label: 'All drones',
      description: executableClusters.length > 0
        ? `${executableClusters.length} detected cluster${executableClusters.length === 1 ? '' : 's'}`
        : 'Entire fleet scope',
      count: totalDrones,
    },
  ];

  executableClusters.forEach((cluster) => {
    const leaderDrone = cluster.drones.find((drone) => drone.role === 'topLeader') || cluster.drones[0] || null;
    const leaderIdentity = leaderDrone
      ? formatCompactDroneIdentity(leaderDrone.pos_id, leaderDrone.hw_id, cluster.title)
      : cluster.title;
    options.push({
      id: String(cluster.id),
      label: leaderDrone ? `${leaderIdentity} cluster` : cluster.title,
      description: leaderDrone
        ? `Top-leader cluster rooted at ${leaderIdentity}. ${cluster.subtitle}`
        : cluster.subtitle,
      count: cluster.counts?.total || cluster.drones.length,
    });
  });

  if (attentionCluster) {
    options.push({
      id: 'attention',
      label: 'Needs review',
      description: attentionCluster.subtitle,
      count: attentionCluster.counts?.total || attentionCluster.drones.length,
    });
  }

  return options;
}

export function filterClustersByScope(clusters = [], scopeId = 'all') {
  if (!scopeId || scopeId === 'all') {
    return clusters;
  }

  if (scopeId === 'attention') {
    return clusters.filter((cluster) => cluster.type === 'attention');
  }

  return clusters.filter((cluster) => String(cluster.id) === String(scopeId));
}

export function toSwarmApiPayload(assignments = []) {
  return assignments
    .map((assignment) => normalizeSwarmAssignment(assignment))
    .filter(Boolean)
    .map((assignment) => ({
      hw_id: Number.parseInt(assignment.hw_id, 10),
      follow: Number.parseInt(assignment.follow, 10),
      offset_x: assignment.offset_x,
      offset_y: assignment.offset_y,
      offset_z: assignment.offset_z,
      frame: assignment.frame,
    }));
}
