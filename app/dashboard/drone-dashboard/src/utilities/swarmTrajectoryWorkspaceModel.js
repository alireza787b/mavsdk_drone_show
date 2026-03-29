const buildListLabel = (values = []) => (values.length > 0 ? values.join(', ') : 'None');

const buildClusterLabel = (count = 0) => `${count} cluster${count === 1 ? '' : 's'}`;
const buildDroneLabel = (count = 0) => `${count} drone output${count === 1 ? '' : 's'}`;

export function buildSwarmTrajectoryWorkspaceStatus({ viewModel, recommendation, hasProcessedOutputs }) {
  const clusterCount = viewModel.clusterSummary.cluster_count || 0;
  const readyClusterCount = viewModel.clusterSummary.ready_cluster_count || 0;
  const needsProcessingCount = viewModel.clusterSummary.needs_processing_cluster_count || 0;
  const partialOutputCount = viewModel.clusterSummary.partial_output_cluster_count || 0;

  if (clusterCount === 0) {
    return {
      tone: 'blocked',
      title: 'No swarm clusters are configured yet',
      message: 'Define top leaders in Swarm Design before authoring or processing trajectory missions.',
      details: ['This workspace only accepts top-leader CSVs from the current swarm structure.'],
    };
  }

  if (viewModel.missingLeaderIds.length > 0) {
    return {
      tone: viewModel.uploadedLeaderIds.length > 0 ? 'attention' : 'blocked',
      title: 'Leader uploads are still incomplete',
      message: `${viewModel.uploadedLeaderIds.length}/${viewModel.expectedLeaderIds.length || clusterCount} leader CSVs are available for the active swarm structure.`,
      details: [
        `Missing leaders: ${buildListLabel(viewModel.missingLeaderIds)}`,
        viewModel.orphanUploadedLeaderIds.length > 0
          ? `Unexpected uploads: ${buildListLabel(viewModel.orphanUploadedLeaderIds)}`
          : null,
      ].filter(Boolean),
    };
  }

  if (partialOutputCount > 0 || (hasProcessedOutputs && viewModel.currentOutcome === 'partial')) {
    return {
      tone: 'attention',
      title: 'Processed outputs need another review pass',
      message: `${buildClusterLabel(partialOutputCount)} still have missing or stale follower outputs before launch.`,
      details: [
        `Ready clusters: ${readyClusterCount}/${clusterCount}`,
        `Attention items: ${viewModel.issueCount + viewModel.advisoryCount}`,
      ],
    };
  }

  if (needsProcessingCount > 0) {
    return {
      tone: 'processing',
      title: 'Leader uploads are ready for processing',
      message: recommendation?.message || 'Follower outputs and plots still need to be regenerated from the latest leader paths.',
      details: [
        `Clusters waiting for processing: ${needsProcessingCount}`,
        `Uploaded leaders: ${buildListLabel(viewModel.uploadedLeaderIds)}`,
      ],
    };
  }

  if (viewModel.clusterSummary.all_clusters_ready && viewModel.processedDroneCount > 0) {
    return {
      tone: 'ready',
      title: 'Mission package is ready for dashboard preflight',
      message: `${buildDroneLabel(viewModel.processedDroneCount)} are available across ${buildClusterLabel(readyClusterCount)}.`,
      details: [
        `Processing session: ${viewModel.session.session_id || 'Unavailable'}`,
        'Next step: review plots, commit the package, then launch Mission Type 4 from Dashboard → Command Control → Mission Trigger.',
      ],
    };
  }

  return {
    tone: 'neutral',
    title: 'Workspace is ready for the next action',
    message: 'Confirm the current swarm structure, upload leader paths, and process the mission package when ready.',
    details: [
      `Expected leaders: ${buildListLabel(viewModel.expectedLeaderIds)}`,
    ],
  };
}

export function buildSwarmTrajectoryStages({ viewModel, recommendation, hasProcessedOutputs }) {
  const clusterCount = viewModel.clusterSummary.cluster_count || 0;
  const expectedLeaderCount = viewModel.expectedLeaderIds.length || clusterCount;
  const uploadedLeaderCount = viewModel.uploadedLeaderIds.length;
  const readyClusterCount = viewModel.clusterSummary.ready_cluster_count || 0;
  const needsProcessingCount = viewModel.clusterSummary.needs_processing_cluster_count || 0;
  const partialOutputCount = viewModel.clusterSummary.partial_output_cluster_count || 0;
  const attentionItemCount = viewModel.issueCount + viewModel.advisoryCount;

  const uploadStage = {
    id: 'upload',
    step: 1,
    title: 'Load Leader Paths',
    actionLabel: 'Open Trajectory Planning',
    actionHref: '/trajectory-planning',
  };

  if (clusterCount === 0) {
    uploadStage.actionLabel = 'Open Swarm Design';
    uploadStage.actionHref = '/swarm-design';
    uploadStage.tone = 'blocked';
    uploadStage.label = 'Blocked';
    uploadStage.summary = 'No clusters are available yet.';
    uploadStage.details = ['Go to Swarm Design and define top leaders before uploading CSVs.'];
  } else if (viewModel.missingLeaderIds.length === 0 && uploadedLeaderCount > 0) {
    uploadStage.tone = 'ready';
    uploadStage.label = 'Ready';
    uploadStage.summary = `All ${expectedLeaderCount} expected leader CSVs are loaded.`;
    uploadStage.details = [
      `Uploaded leaders: ${buildListLabel(viewModel.uploadedLeaderIds)}`,
      'Only top-leader paths belong in this workspace. Followers are generated later.',
    ];
  } else if (uploadedLeaderCount > 0) {
    uploadStage.tone = 'attention';
    uploadStage.label = 'Action Needed';
    uploadStage.summary = `${uploadedLeaderCount}/${expectedLeaderCount} leader CSVs are loaded for the current swarm structure.`;
    uploadStage.details = [
      `Missing leaders: ${buildListLabel(viewModel.missingLeaderIds)}`,
      viewModel.orphanUploadedLeaderIds.length > 0
        ? `Unexpected uploads: ${buildListLabel(viewModel.orphanUploadedLeaderIds)}`
        : 'Replace only the leader paths that changed before processing again.',
    ];
  } else {
    uploadStage.tone = 'blocked';
    uploadStage.label = 'Waiting';
    uploadStage.summary = 'Upload the current top-leader CSVs before processing can begin.';
    uploadStage.details = [
      `Expected leaders: ${buildListLabel(viewModel.expectedLeaderIds)}`,
      'Use the planner export to keep the authored path and upload in sync.',
    ];
  }

  const processingStage = {
    id: 'processing',
    step: 2,
    title: 'Generate Cluster Outputs',
  };

  if (clusterCount === 0) {
    processingStage.tone = 'blocked';
    processingStage.label = 'Blocked';
    processingStage.summary = 'Processing is unavailable until the swarm structure exists.';
    processingStage.details = ['Create top-leader clusters first, then upload at least one leader CSV.'];
  } else if (uploadedLeaderCount === 0) {
    processingStage.tone = 'blocked';
    processingStage.label = 'Waiting';
    processingStage.summary = 'No leader CSVs have been uploaded yet.';
    processingStage.details = ['Upload at least one leader path before generating follower outputs.'];
  } else if (viewModel.clusterSummary.all_clusters_ready && viewModel.processedDroneCount > 0) {
    processingStage.tone = 'ready';
    processingStage.label = 'Ready';
    processingStage.summary = `Processed outputs are current for ${buildClusterLabel(readyClusterCount)}.`;
    processingStage.details = [
      `Processed drones: ${viewModel.processedDroneCount}`,
      'Re-run processing only after changing leader paths or swarm assignments.',
    ];
  } else if (partialOutputCount > 0) {
    processingStage.tone = 'attention';
    processingStage.label = 'Action Needed';
    processingStage.summary = `${buildClusterLabel(partialOutputCount)} still have missing follower outputs.`;
    processingStage.details = [
      `Ready clusters: ${readyClusterCount}/${clusterCount}`,
      'Run a fresh processing pass after clearing or replacing invalid cluster outputs.',
    ];
  } else {
    processingStage.tone = 'processing';
    processingStage.label = 'Next';
    processingStage.summary = recommendation?.message || 'Leader uploads are ready to be expanded into follower outputs and plots.';
    processingStage.details = [
      `Clusters waiting for processing: ${needsProcessingCount || uploadedLeaderCount}`,
      'Process once after all changed leader paths are uploaded.',
    ];
  }

  const reviewStage = {
    id: 'review',
    step: 3,
    title: 'Review, Commit, and Launch',
  };

  if (!hasProcessedOutputs || viewModel.processedDroneCount === 0) {
    reviewStage.tone = 'blocked';
    reviewStage.label = 'Blocked';
    reviewStage.summary = 'Review and commit stay locked until processed outputs exist.';
    reviewStage.details = ['Generate the mission package first, then inspect plots and downloads here.'];
  } else if (viewModel.currentOutcome === 'partial' || attentionItemCount > 0 || !viewModel.clusterSummary.all_clusters_ready) {
    reviewStage.tone = 'attention';
    reviewStage.label = 'Review';
    reviewStage.summary = `${buildDroneLabel(viewModel.processedDroneCount)} exist, but attention items still need operator review.`;
    reviewStage.details = [
      `Ready clusters: ${readyClusterCount}/${clusterCount}`,
      `Attention items: ${attentionItemCount}`,
    ];
    reviewStage.actionLabel = 'Open Dashboard';
    reviewStage.actionHref = '/';
  } else {
    reviewStage.tone = 'ready';
    reviewStage.label = 'Ready';
    reviewStage.summary = 'Plots, outputs, and cluster readiness are clear for commit and dashboard dispatch.';
    reviewStage.details = [
      `Session: ${viewModel.session.session_id || 'Unavailable'}`,
      'Commit the package, then launch Mission Type 4 from Dashboard → Command Control → Mission Trigger.',
    ];
    reviewStage.actionLabel = 'Open Dashboard';
    reviewStage.actionHref = '/';
  }

  return [uploadStage, processingStage, reviewStage];
}
