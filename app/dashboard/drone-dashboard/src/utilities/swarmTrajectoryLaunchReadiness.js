import {
  buildLeaderChainSelectionIssues,
  buildNormalizedIdSet,
  getClusterMemberIds,
} from './swarmScopeUtils';
import { normalizeClusterState } from './swarmTrajectoryViewModel';

const countLabel = (count = 0, singular, plural = `${singular}s`) => `${count} ${count === 1 ? singular : plural}`;
const toFiniteNumber = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

const countClusterIssues = (clusters = []) => clusters.reduce((total, cluster) => total + (cluster.issues?.length || 0), 0);
const countClusterAdvisories = (clusters = []) => clusters.reduce((total, cluster) => total + (cluster.advisories?.length || 0), 0);

const formatDroneList = (droneIds = []) => droneIds.join(', ');

function buildSelectionScope(clusterStatus = {}, selectedDroneIds = []) {
  const selectedSet = buildNormalizedIdSet(selectedDroneIds);
  const clusters = clusterStatus?.clusters || [];
  const targetedClusters = clusters.filter((cluster) => {
    const memberIds = getClusterMemberIds(cluster);
    return memberIds.some((droneId) => selectedSet.has(droneId));
  });
  const untargetedClusters = clusters.filter((cluster) => !targetedClusters.includes(cluster));
  const processedSet = buildNormalizedIdSet(clusterStatus?.processed_drones || []);

  const selectedMissingOutputs = Array.from(selectedSet)
    .filter((droneId) => !processedSet.has(droneId))
    .sort((left, right) => left - right);
  const scopeReadyClusterCount = targetedClusters.filter((cluster) => {
    const selectedClusterMembers = getClusterMemberIds(cluster).filter((droneId) => selectedSet.has(droneId));
    return selectedClusterMembers.length > 0 && selectedClusterMembers.every((droneId) => processedSet.has(droneId));
  }).length;

  const selectionIssues = buildLeaderChainSelectionIssues({
    followMap: clusterStatus?.follow_map || {},
    activeIds: Array.from(selectedSet),
  });

  return {
    selectedSet,
    targetedClusters,
    untargetedClusters,
    processedSet,
    selectedMissingOutputs,
    scopeReadyClusterCount,
    selectionIssues,
  };
}

function formatSelectionIssues(selectionIssues = []) {
  const missingAssignments = selectionIssues
    .filter((issue) => issue.issue === 'missing_swarm_assignment')
    .map((issue) => issue.droneId)
    .sort((left, right) => left - right);
  const missingLeaders = selectionIssues
    .filter((issue) => issue.issue === 'leader_not_in_active_mission_set')
    .map((issue) => `Drone ${issue.droneId} requires leader ${issue.leaderId}`)
    .filter((value, index, items) => items.indexOf(value) === index);
  const circularChains = selectionIssues
    .filter((issue) => issue.issue === 'circular_leader_chain')
    .map((issue) => issue.droneId)
    .sort((left, right) => left - right);

  const blockers = [];

  if (missingAssignments.length > 0) {
    blockers.push(`Selected drones ${formatDroneList(missingAssignments)} are not present in the current swarm configuration.`);
  }

  if (missingLeaders.length > 0) {
    blockers.push(`${countLabel(missingLeaders.length, 'leader chain')} ${missingLeaders.length === 1 ? 'is' : 'are'} incomplete: ${missingLeaders.join('; ')}.`);
  }

  if (circularChains.length > 0) {
    blockers.push(`Selected drones ${formatDroneList(circularChains)} have circular leader chains in Swarm Design.`);
  }

  return blockers;
}

function aggregatePackageStats(statsList = []) {
  if (!statsList.length) {
    return {
      available: false,
      droneCount: 0,
      routeEntryTimeS: null,
      missionClockS: null,
      routeMotionTimeS: null,
      maxAltitudeMslM: null,
      minAltitudeMslM: null,
      altitudeWindowM: null,
    };
  }

  const missionClocks = statsList
    .map((stats) => toFiniteNumber(stats?.mission_clock_s ?? stats?.missionClockS))
    .filter((value) => value !== null);
  const routeEntries = statsList
    .map((stats) => toFiniteNumber(stats?.route_entry_time_s ?? stats?.routeEntryTimeS))
    .filter((value) => value !== null);
  const maxAltitudes = statsList
    .map((stats) => toFiniteNumber(stats?.max_altitude_msl_m ?? stats?.maxAltitudeMslM))
    .filter((value) => value !== null);
  const minAltitudes = statsList
    .map((stats) => toFiniteNumber(stats?.min_altitude_msl_m ?? stats?.minAltitudeMslM))
    .filter((value) => value !== null);

  const missionClockS = missionClocks.length ? Math.max(...missionClocks) : null;
  const routeEntryTimeS = routeEntries.length ? Math.min(...routeEntries) : null;
  const routeMotionTimeS = missionClockS !== null && routeEntryTimeS !== null
    ? Math.max(missionClockS - routeEntryTimeS, 0)
    : null;
  const maxAltitudeMslM = maxAltitudes.length ? Math.max(...maxAltitudes) : null;
  const minAltitudeMslM = minAltitudes.length ? Math.min(...minAltitudes) : null;

  return {
    available: true,
    droneCount: statsList.length,
    routeEntryTimeS,
    missionClockS,
    routeMotionTimeS,
    maxAltitudeMslM,
    minAltitudeMslM,
    altitudeWindowM: maxAltitudeMslM !== null && minAltitudeMslM !== null
      ? maxAltitudeMslM - minAltitudeMslM
      : null,
  };
}

function normalizePackageStats(stats = null) {
  if (!stats?.available) {
    return aggregatePackageStats([]);
  }

  return {
    available: true,
    droneCount: toFiniteNumber(stats?.drone_count ?? stats?.droneCount) ?? 0,
    routeEntryTimeS: toFiniteNumber(stats?.route_entry_time_s ?? stats?.routeEntryTimeS),
    missionClockS: toFiniteNumber(stats?.mission_clock_s ?? stats?.missionClockS),
    routeMotionTimeS: toFiniteNumber(stats?.route_motion_time_s ?? stats?.routeMotionTimeS),
    maxAltitudeMslM: toFiniteNumber(stats?.max_altitude_msl_m ?? stats?.maxAltitudeMslM),
    minAltitudeMslM: toFiniteNumber(stats?.min_altitude_msl_m ?? stats?.minAltitudeMslM),
    altitudeWindowM: toFiniteNumber(stats?.altitude_window_m ?? stats?.altitudeWindowM),
  };
}

function getPackageDroneStat(packageDroneStats = {}, droneId) {
  return packageDroneStats?.[droneId] || packageDroneStats?.[String(droneId)] || null;
}

export const buildSwarmTrajectoryLaunchReadiness = ({
  clusterStatus = null,
  loading = false,
  error = null,
  targetMode = 'all',
  selectedDrones = [],
  targetDroneIds = [],
} = {}) => {
  const blockers = [];
  const warnings = [];

  if (loading) {
    blockers.push('Verifying the processed Swarm Trajectory package...');
  }

  if (error) {
    blockers.push('Swarm Trajectory readiness could not be verified from the backend.');
  }

  const clusters = clusterStatus?.clusters || [];
  const summary = clusterStatus?.cluster_summary || {};
  const session = clusterStatus?.session || { exists: false };
  const sessionChanges = clusterStatus?.session_changes
    || clusterStatus?.processing_recommendation?.changes
    || {};
  const processingRecommendation = clusterStatus?.processing_recommendation || null;
  const clusterCount = summary.cluster_count ?? clusters.length;
  const readyClusterCount = summary.ready_cluster_count ?? clusters.filter((cluster) => cluster.ready).length;
  const needsProcessingCount = summary.needs_processing_cluster_count ?? clusters.filter((cluster) => cluster.state === 'needs_processing').length;
  const partialOutputCount = summary.partial_output_cluster_count
    ?? clusters.filter((cluster) => normalizeClusterState(cluster.state) === 'partial_outputs').length;
  const missingUploadCount = summary.missing_upload_cluster_count ?? clusters.filter((cluster) => !cluster.leader_uploaded).length;
  const processedDroneCount = clusterStatus?.processed_drones?.length ?? clusterStatus?.processed_trajectories ?? 0;
  const expectedDroneCount = session.total_drones
    || clusters.reduce(
      (count, cluster) => count + (cluster.expected_drone_count ?? ((cluster.follower_count || 0) + 1)),
      0,
    );
  const issueCount = countClusterIssues(clusters);
  const advisoryCount = countClusterAdvisories(clusters);
  const orphanLeaderCount = clusterStatus?.orphan_uploaded_leaders?.length || 0;
  const packageStats = clusterStatus?.package_stats?.available
    ? normalizePackageStats(clusterStatus.package_stats)
    : aggregatePackageStats(Object.values(clusterStatus?.package_drone_stats || {}));
  const scopedTargetIds = Array.isArray(targetDroneIds) && targetDroneIds.length > 0
    ? targetDroneIds
    : selectedDrones;
  const isScopedTarget = targetMode !== 'all' && scopedTargetIds.length > 0;
  const selectionScope = buildSelectionScope(clusterStatus, scopedTargetIds);
  const scopeClusterCount = isScopedTarget ? selectionScope.targetedClusters.length : clusterCount;
  const scopeReadyClusterCount = isScopedTarget
    ? selectionScope.scopeReadyClusterCount
    : readyClusterCount;
  const scopedProcessedDroneCount = isScopedTarget
    ? Array.from(selectionScope.selectedSet).filter((droneId) => selectionScope.processedSet.has(droneId)).length
    : processedDroneCount;
  const scopePackageStats = isScopedTarget
    ? aggregatePackageStats(
        Array.from(selectionScope.selectedSet)
          .map((droneId) => getPackageDroneStat(clusterStatus?.package_drone_stats, droneId))
          .filter(Boolean),
      )
    : packageStats;

  if (!loading && !error) {
    if (clusterCount === 0) {
      blockers.push('No swarm clusters are configured. Publish the hierarchy in Swarm Design first.');
    }

    if (!session.exists && processedDroneCount > 0) {
      blockers.push('Processed outputs exist, but no active processing session is recorded. Reprocess before launch.');
    } else if (!session.exists || processedDroneCount === 0) {
      blockers.push('No processed Swarm Trajectory package is active yet.');
    }

    if (sessionChanges.requires_full_reprocess && (session.exists || processedDroneCount > 0)) {
      let freshnessReasonAdded = false;
      if (sessionChanges.swarm_structure_changed) {
        blockers.push('Swarm structure changed since the active processed package was generated. Reprocess before launch.');
        freshnessReasonAdded = true;
      }
      if (sessionChanges.parameters_changed) {
        blockers.push('Swarm trajectory processing parameters changed since the active package was generated. Reprocess before launch.');
        freshnessReasonAdded = true;
      }
      if (sessionChanges.trajectory_files_changed) {
        blockers.push('One or more leader CSV uploads changed since the active package was generated. Reprocess before launch.');
        freshnessReasonAdded = true;
      }
      if (sessionChanges.leader_structure_changed) {
        blockers.push('Leader upload coverage no longer matches the current swarm structure. Reprocess before launch.');
        freshnessReasonAdded = true;
      }
      if (!freshnessReasonAdded) {
        blockers.push(processingRecommendation?.message || 'The active processed package is stale and must be regenerated before launch.');
      }
    }

    if (isScopedTarget) {
      const outOfScopeIncompleteClusters = selectionScope.untargetedClusters.filter(
        (cluster) => !cluster.ready || (cluster.issues?.length || 0) > 0,
      ).length;
      const targetedAdvisoryCount = countClusterAdvisories(selectionScope.targetedClusters);

      if (selectionScope.selectedSet.size === 0) {
        blockers.push('No drones are selected for this launch scope.');
      }

      if (selectionScope.targetedClusters.length === 0 && session.exists) {
        blockers.push('None of the selected drones belong to the active Swarm Trajectory package.');
      }

      if (selectionScope.selectedMissingOutputs.length > 0) {
        blockers.push(
          `Selected drones ${formatDroneList(selectionScope.selectedMissingOutputs)} do not have processed trajectory outputs in the active package.`,
        );
      }

      blockers.push(...formatSelectionIssues(selectionScope.selectionIssues));

      if (targetedAdvisoryCount > 0) {
        warnings.push(`${countLabel(targetedAdvisoryCount, 'scope advisory item')} should be reviewed before launch.`);
      }

      if (outOfScopeIncompleteClusters > 0) {
        warnings.push(`${countLabel(outOfScopeIncompleteClusters, 'out-of-scope cluster')} ${outOfScopeIncompleteClusters === 1 ? 'remains' : 'remain'} incomplete, but ${outOfScopeIncompleteClusters === 1 ? 'is' : 'are'} outside the current launch scope.`);
      }

      if (selectionScope.selectedSet.size < processedDroneCount) {
        warnings.push(`Subset launch targets ${selectionScope.selectedSet.size} of ${processedDroneCount} processed drones. Non-selected drones will remain idle.`);
      }
    } else {
      if (missingUploadCount > 0) {
        blockers.push(`${countLabel(missingUploadCount, 'leader upload')} still ${missingUploadCount === 1 ? 'is' : 'are'} missing.`);
      }

      if (needsProcessingCount > 0) {
        blockers.push(`${countLabel(needsProcessingCount, 'cluster')} still ${needsProcessingCount === 1 ? 'needs' : 'need'} a processing pass.`);
      }

      if (partialOutputCount > 0) {
        blockers.push(`${countLabel(partialOutputCount, 'cluster')} still ${partialOutputCount === 1 ? 'has' : 'have'} partial outputs.`);
      }

      if (clusterCount > 0 && readyClusterCount < clusterCount && missingUploadCount === 0 && needsProcessingCount === 0 && partialOutputCount === 0) {
        blockers.push('The processed package is incomplete and not all clusters are marked ready.');
      }

      if (issueCount > 0) {
        blockers.push(`${countLabel(issueCount, 'cluster issue')} still ${issueCount === 1 ? 'requires' : 'require'} operator correction before launch.`);
      }

      if (advisoryCount > 0) {
        warnings.push(`${countLabel(advisoryCount, 'advisory item')} should be reviewed before launch.`);
      }

      if (orphanLeaderCount > 0) {
        warnings.push(`${countLabel(orphanLeaderCount, 'uploaded leader path')} no longer ${orphanLeaderCount === 1 ? 'belongs' : 'belong'} to the current swarm structure.`);
      }
    }
  }

  return {
    blockers,
    warnings,
    canLaunch: blockers.length === 0,
    summary: {
      clusterCount,
      readyClusterCount,
      needsProcessingCount,
      partialOutputCount,
      missingUploadCount,
      processedDroneCount,
      expectedDroneCount,
      issueCount,
      advisoryCount,
      packageStats,
      scopePackageStats,
      session,
      overallState: summary.overall_state || 'unknown',
      scopeMode: isScopedTarget ? targetMode : 'all',
      scopeClusterCount,
      scopeReadyClusterCount,
      scopeTargetDroneCount: isScopedTarget ? selectionScope.selectedSet.size : expectedDroneCount,
      scopeProcessedDroneCount: scopedProcessedDroneCount,
      outOfScopeIncompleteClusterCount: isScopedTarget
        ? selectionScope.untargetedClusters.filter((cluster) => !cluster.ready || (cluster.issues?.length || 0) > 0).length
        : 0,
      scopeSelectionIssueCount: isScopedTarget ? selectionScope.selectionIssues.length : 0,
    },
  };
};
