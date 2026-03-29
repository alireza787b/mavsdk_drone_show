const CLUSTER_STATE_META = {
  ready: {
    tone: 'ready',
    label: 'Ready',
    summary: 'Leader upload, follower outputs, and review plots are ready for mission preflight.',
  },
  partial_outputs: {
    tone: 'warning',
    label: 'Partial Outputs',
    summary: 'Some drones in this cluster still need regenerated outputs before launch.',
  },
  needs_processing: {
    tone: 'processing',
    label: 'Needs Processing',
    summary: 'A leader CSV exists, but follower outputs and plots still need a processing pass.',
  },
  missing_upload: {
    tone: 'missing',
    label: 'Missing Leader CSV',
    summary: 'Upload the leader CSV for this cluster before processing can continue.',
  },
  unknown: {
    tone: 'unknown',
    label: 'Unknown',
    summary: 'Cluster readiness could not be determined yet.',
  },
};

const toNumericId = (value) => Number(value);
const CLUSTER_STATE_ALIASES = {
  partial: 'partial_outputs',
};

export function normalizeClusterState(state) {
  return CLUSTER_STATE_ALIASES[state] || state;
}

export function getClusterStateMeta(cluster = {}) {
  const derivedState = normalizeClusterState(cluster.state)
    || (cluster.ready ? 'ready' : cluster.leader_uploaded ? 'needs_processing' : 'missing_upload');

  return CLUSTER_STATE_META[derivedState] || CLUSTER_STATE_META.unknown;
}

export function buildFallbackClusters({
  leaders = [],
  hierarchies = {},
  followerDetails = {},
  uploadedLeaderIds = [],
}) {
  const uploadedSet = new Set(uploadedLeaderIds.map(toNumericId));

  return leaders.map((leaderId) => {
    const numericLeaderId = toNumericId(leaderId);
    const followerIds = followerDetails[numericLeaderId] || followerDetails[leaderId] || [];
    const followerCount = hierarchies[numericLeaderId] ?? hierarchies[leaderId] ?? followerIds.length;
    const leaderUploaded = uploadedSet.has(numericLeaderId);

    return {
      leader_id: numericLeaderId,
      follower_ids: followerIds,
      follower_count: followerCount,
      expected_drone_count: 1 + followerCount,
      processed_drone_count: 0,
      ready: false,
      state: leaderUploaded ? 'needs_processing' : 'missing_upload',
      leader_uploaded: leaderUploaded,
      leader_processed: false,
      missing_follower_ids: followerIds,
      processed_follower_ids: [],
      leader_plot_available: false,
      cluster_plot_available: false,
      issues: [],
      advisories: [],
    };
  });
}

export function buildSwarmTrajectoryViewModel({
  leaders = [],
  hierarchies = {},
  followerDetails = {},
  uploadedLeaders = [],
  status = null,
  results = null,
}) {
  const uploadedLeaderIds = (status?.uploaded_leaders || uploadedLeaders || []).map(toNumericId);
  const clusters = status?.clusters?.length
    ? status.clusters
    : buildFallbackClusters({
        leaders,
        hierarchies,
        followerDetails,
        uploadedLeaderIds,
      });

  const clusterSummary = status?.cluster_summary || {};
  const totalClusters = clusterSummary.cluster_count ?? clusters.length;
  const readyClusterCount = clusterSummary.ready_cluster_count
    ?? clusters.filter((cluster) => cluster.ready).length;
  const needsProcessingCount = clusterSummary.needs_processing_cluster_count
    ?? clusters.filter((cluster) => getClusterStateMeta(cluster).tone === 'processing').length;
  const partialOutputCount = clusterSummary.partial_output_cluster_count
    ?? clusters.filter((cluster) => normalizeClusterState(cluster.state) === 'partial_outputs').length;
  const missingUploadCount = clusterSummary.missing_upload_cluster_count
    ?? clusters.filter((cluster) => getClusterStateMeta(cluster).tone === 'missing').length;
  const processedClusterCount = clusterSummary.processed_cluster_count
    ?? clusters.filter((cluster) => (cluster.processed_drone_count || 0) > 0).length;
  const processedDroneCount = status?.processed_trajectories ?? results?.processed_drones ?? 0;
  const processedDroneList = status?.processed_drones || results?.processed_drone_list || [];
  const expectedLeaderIds = (status?.expected_top_leaders || leaders || []).map(toNumericId);
  const missingLeaderIds = (status?.missing_uploaded_leaders
    || expectedLeaderIds.filter((leaderId) => !uploadedLeaderIds.includes(leaderId))).map(toNumericId);
  const orphanUploadedLeaderIds = (status?.orphan_uploaded_leaders
    || uploadedLeaderIds.filter((leaderId) => !expectedLeaderIds.includes(leaderId))).map(toNumericId);
  const currentOutcome = results?.outcome
    || (clusterSummary.overall_state === 'partial' ? 'partial' : processedDroneCount > 0 ? 'success' : null);
  const visibleClusterLeaders = clusters
    .filter(
      (cluster) => (cluster.processed_drone_count || 0) > 0
        || cluster.leader_processed
        || cluster.cluster_plot_available
        || cluster.leader_plot_available
    )
    .map((cluster) => toNumericId(cluster.leader_id));

  const issueCount = clusters.reduce((sum, cluster) => sum + (cluster.issues?.length || 0), 0);
  const advisoryCount = clusters.reduce((sum, cluster) => sum + (cluster.advisories?.length || 0), 0);

  return {
    clusters,
    clusterSummary: {
      cluster_count: totalClusters,
      ready_cluster_count: readyClusterCount,
      needs_processing_cluster_count: needsProcessingCount,
      partial_output_cluster_count: partialOutputCount,
      missing_upload_cluster_count: missingUploadCount,
      processed_cluster_count: processedClusterCount,
      all_clusters_ready: clusterSummary.all_clusters_ready ?? (totalClusters > 0 && readyClusterCount === totalClusters),
      overall_state: clusterSummary.overall_state || 'unknown',
    },
    uploadedLeaderIds,
    expectedLeaderIds,
    missingLeaderIds,
    orphanUploadedLeaderIds,
    processedDroneCount,
    processedDroneList,
    currentOutcome,
    visibleClusterLeaders,
    issueCount,
    advisoryCount,
    session: status?.session || {
      exists: false,
      session_id: null,
      timestamp: null,
      processed_leaders: [],
      total_drones: 0,
    },
  };
}
