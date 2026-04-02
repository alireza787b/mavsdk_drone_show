import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { getDroneReadinessModel } from './droneReadiness';
import { formatDroneLabel } from './missionIdentityUtils';
import { getDroneRuntimeStatus } from './droneRuntimeStatus';

export const SWARM_RUNTIME_SCOPE = {
  DRONE: 'drone',
  CLUSTER: 'cluster',
};

export const SWARM_RUNTIME_ACTIONS = {
  START: {
    key: 'START',
    missionType: DRONE_MISSION_TYPES.SMART_SWARM,
    label: 'Start Smart Swarm',
    operatorLabel: 'Start Smart Swarm',
    tone: 'primary',
    description: 'Start live Smart Swarm following for the current scope.',
  },
  STOP_HOLD: {
    key: 'STOP_HOLD',
    missionType: DRONE_ACTION_TYPES.HOLD,
    label: 'Stop Swarm (Hold)',
    operatorLabel: 'Stop Smart Swarm (Hold)',
    tone: 'secondary',
    description: 'Exit active following and command the selected drones to hold position.',
  },
  LAND: {
    key: 'LAND',
    missionType: DRONE_ACTION_TYPES.LAND,
    label: 'Land Swarm',
    operatorLabel: 'Land Swarm',
    tone: 'danger',
    description: 'Override the current swarm behavior and land the selected drones.',
  },
  RTL: {
    key: 'RTL',
    missionType: DRONE_ACTION_TYPES.RETURN_RTL,
    label: 'RTL Swarm',
    operatorLabel: 'RTL Swarm',
    tone: 'warning',
    description: 'Override the current swarm behavior and return the selected drones to launch.',
  },
};

function getTargetIdSet(targetIds = []) {
  return new Set((Array.isArray(targetIds) ? targetIds : []).map((value) => String(value)));
}

function formatRuntimeTargetList(targetIds = []) {
  const labels = targetIds.slice(0, 3).map((targetId) => formatDroneLabel(targetId));
  if (targetIds.length > 3) {
    return `${labels.join(', ')} +${targetIds.length - 3} more`;
  }
  return labels.join(', ');
}

function formatScopeCountLabel(label, count) {
  return `${label} · ${count} drone${count === 1 ? '' : 's'}`;
}

export function resolveSwarmRuntimeTargets(
  viewModel,
  scope = SWARM_RUNTIME_SCOPE.DRONE,
  selectedDroneId = null,
  selectedClusterId = null
) {
  const drones = Array.isArray(viewModel?.drones) ? viewModel.drones : [];
  const dronesById = viewModel?.dronesById || {};
  const clusters = Array.isArray(viewModel?.clusters) ? viewModel.clusters : [];

  if (drones.length === 0) {
    return {
      selectedDrone: null,
      cluster: null,
      targetIds: [],
      scopeLabel: 'No swarm drones available',
      targetSummary: 'Load or save a Smart Swarm assignment before issuing runtime commands.',
    };
  }

  const selectedDrone = (selectedDroneId && dronesById[selectedDroneId]) || drones[0];

  if (scope === SWARM_RUNTIME_SCOPE.DRONE) {
    return {
      selectedDrone,
      cluster: null,
      targetIds: [selectedDrone.hw_id],
      scopeLabel: formatScopeCountLabel(selectedDrone.title, 1),
      targetSummary: 'Targets only the selected drone. Other swarm drones continue until they receive their own command, failover event, or follow-chain update.',
    };
  }

  const selectedCluster = clusters.find(
    (candidate) => candidate.id === selectedClusterId && candidate.type === 'cluster'
  )
    || clusters.find((candidate) => candidate.id === selectedDrone?.clusterId && candidate.type === 'cluster')
    || clusters.find((candidate) => candidate.type === 'cluster')
    || null;

  const targetIds = selectedCluster?.drones?.map((drone) => drone.hw_id) || [];
  const count = targetIds.length;

  return {
    selectedDrone,
    cluster: selectedCluster,
    targetIds,
    scopeLabel: selectedCluster
      ? formatScopeCountLabel(selectedCluster.title, count)
      : `${selectedDrone?.title || 'Selected drone'} has no valid executable cluster`,
    targetSummary: selectedCluster
      ? `${selectedCluster.subtitle} · ${count} target drone${count === 1 ? '' : 's'}`
      : 'Resolve follow-chain warnings before sending cluster-scoped Smart Swarm commands.',
  };
}

export function getSwarmRuntimeStartBlockerReason({
  scope,
  selectedDrone,
  selectedCluster,
  targetIds = [],
  targetDrones = [],
  dirtyIds = [],
  pendingSyncIds = [],
}) {
  if (targetIds.length === 0) {
    return 'No valid swarm targets are available.';
  }

  if (scope === SWARM_RUNTIME_SCOPE.CLUSTER && !selectedCluster) {
    return 'Resolve the selected cluster issues before starting Smart Swarm.';
  }

  if (scope === SWARM_RUNTIME_SCOPE.DRONE && selectedDrone?.hasBlockingWarnings) {
    return 'Resolve the selected drone follow-chain issues before starting Smart Swarm.';
  }

  if (selectedCluster?.type === 'attention') {
    return 'Resolve the selected cluster issues before starting Smart Swarm.';
  }

  const blockingTargetIds = targetDrones
    .filter((drone) => drone?.hasBlockingWarnings)
    .map((drone) => String(drone.hw_id));
  if (blockingTargetIds.length > 0) {
    return `Resolve follow-chain issues on ${formatRuntimeTargetList(blockingTargetIds)} before starting Smart Swarm.`;
  }

  const targetIdSet = getTargetIdSet(targetIds);
  const dirtyTargetIds = (Array.isArray(dirtyIds) ? dirtyIds : [])
    .map((value) => String(value))
    .filter((value) => targetIdSet.has(value));
  const pendingTargetIds = (Array.isArray(pendingSyncIds) ? pendingSyncIds : [])
    .map((value) => String(value))
    .filter((value) => targetIdSet.has(value));
  const targetedUnsavedIds = [...new Set([...dirtyTargetIds, ...pendingTargetIds])];

  if (targetedUnsavedIds.length > 0) {
    return `Save or sync the targeted swarm assignments for ${formatRuntimeTargetList(targetedUnsavedIds)} before starting Smart Swarm.`;
  }

  return '';
}

export function getSwarmRuntimeTelemetrySummary(targetIds = [], telemetryById = {}, nowMs = Date.now()) {
  const summary = {
    total: targetIds.length,
    telemetryCount: 0,
    readyCount: 0,
    blockedCount: 0,
    reviewCount: 0,
    linkIssueCount: 0,
    waitingCount: 0,
  };

  targetIds.forEach((targetId) => {
    const telemetry = telemetryById?.[String(targetId)];
    if (!telemetry) {
      summary.waitingCount += 1;
      return;
    }

    summary.telemetryCount += 1;
    const runtimeStatus = getDroneRuntimeStatus(telemetry, nowMs);
    const readiness = getDroneReadinessModel(telemetry, runtimeStatus);
    const hasLinkIssue = runtimeStatus.level !== 'online';

    if (hasLinkIssue) {
      summary.linkIssueCount += 1;
    }

    if (readiness.status === 'blocked') {
      summary.blockedCount += 1;
      return;
    }

    if (readiness.status === 'ready' && !hasLinkIssue) {
      summary.readyCount += 1;
      return;
    }

    summary.reviewCount += 1;
  });

  return summary;
}

export function buildSwarmRuntimeCommand(actionKey, targetIds = []) {
  const action = SWARM_RUNTIME_ACTIONS[actionKey];
  if (!action) {
    throw new Error(`Unknown swarm runtime action: ${actionKey}`);
  }

  return {
    missionType: String(action.missionType),
    triggerTime: '0',
    target_drones: targetIds,
    operatorLabel: action.operatorLabel,
    command_scope: 'smart_swarm_runtime',
  };
}
