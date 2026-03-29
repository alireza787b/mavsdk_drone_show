import {
  buildSwarmTrajectoryStages,
  buildSwarmTrajectoryWorkspaceStatus,
} from './swarmTrajectoryWorkspaceModel';

const buildViewModel = (overrides = {}) => ({
  uploadedLeaderIds: [],
  expectedLeaderIds: [1, 5],
  missingLeaderIds: [1, 5],
  orphanUploadedLeaderIds: [],
  processedDroneCount: 0,
  currentOutcome: null,
  issueCount: 0,
  advisoryCount: 0,
  clusterSummary: {
    cluster_count: 2,
    ready_cluster_count: 0,
    needs_processing_cluster_count: 0,
    partial_output_cluster_count: 0,
    all_clusters_ready: false,
  },
  session: {
    exists: false,
    session_id: null,
    total_drones: 0,
  },
  ...overrides,
});

describe('swarmTrajectoryWorkspaceModel', () => {
  test('buildSwarmTrajectoryWorkspaceStatus reports missing leader uploads as blocked or attention', () => {
    expect(
      buildSwarmTrajectoryWorkspaceStatus({
        viewModel: buildViewModel(),
        recommendation: null,
        hasProcessedOutputs: false,
      }),
    ).toMatchObject({
      tone: 'blocked',
      title: 'Leader uploads are still incomplete',
    });

    expect(
      buildSwarmTrajectoryWorkspaceStatus({
        viewModel: buildViewModel({
          uploadedLeaderIds: [1],
          missingLeaderIds: [5],
        }),
        recommendation: null,
        hasProcessedOutputs: false,
      }),
    ).toMatchObject({
      tone: 'attention',
      title: 'Leader uploads are still incomplete',
    });
  });

  test('buildSwarmTrajectoryWorkspaceStatus reports ready mission packages', () => {
    const status = buildSwarmTrajectoryWorkspaceStatus({
      viewModel: buildViewModel({
        uploadedLeaderIds: [1, 5],
        expectedLeaderIds: [1, 5],
        missingLeaderIds: [],
        processedDroneCount: 5,
        clusterSummary: {
          cluster_count: 2,
          ready_cluster_count: 2,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 0,
          all_clusters_ready: true,
        },
        session: {
          exists: true,
          session_id: 'session-42',
          total_drones: 5,
        },
      }),
      recommendation: null,
      hasProcessedOutputs: true,
    });

    expect(status).toMatchObject({
      tone: 'ready',
      title: 'Mission package is ready for launch preflight',
    });
    expect(status.details).toContain('Processing session: session-42');
    expect(status.details).toContain('Next step: review plots, optionally commit the package for traceability, then launch Mission Type 4 from Dashboard → Command Control → Mission Trigger.');
  });

  test('buildSwarmTrajectoryStages derives blocked, action-needed, and ready stages', () => {
    const stages = buildSwarmTrajectoryStages({
      viewModel: buildViewModel({
        uploadedLeaderIds: [1, 5],
        expectedLeaderIds: [1, 5],
        missingLeaderIds: [],
        processedDroneCount: 5,
        clusterSummary: {
          cluster_count: 2,
          ready_cluster_count: 2,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 0,
          all_clusters_ready: true,
        },
        session: {
          exists: true,
          session_id: 'session-42',
          total_drones: 5,
        },
      }),
      recommendation: { action: 'safe_incremental', message: 'Safe incremental update.' },
      hasProcessedOutputs: true,
    });

    expect(stages[0]).toMatchObject({
      id: 'upload',
      tone: 'ready',
      label: 'Ready',
    });
    expect(stages[1]).toMatchObject({
      id: 'processing',
      tone: 'ready',
      label: 'Ready',
    });
    expect(stages[2]).toMatchObject({
      id: 'review',
      tone: 'ready',
      label: 'Ready',
      actionLabel: 'Open Mission Trigger',
    });
  });

  test('buildSwarmTrajectoryStages flags partial outputs for review', () => {
    const stages = buildSwarmTrajectoryStages({
      viewModel: buildViewModel({
        uploadedLeaderIds: [1, 5],
        expectedLeaderIds: [1, 5],
        missingLeaderIds: [],
        processedDroneCount: 4,
        currentOutcome: 'partial',
        issueCount: 1,
        advisoryCount: 1,
        clusterSummary: {
          cluster_count: 2,
          ready_cluster_count: 1,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 1,
          all_clusters_ready: false,
        },
      }),
      recommendation: { action: 'recommended_full_reprocess', message: 'A clean processing pass is recommended.' },
      hasProcessedOutputs: true,
    });

    expect(stages[1]).toMatchObject({
      id: 'processing',
      tone: 'attention',
      label: 'Action Needed',
    });
    expect(stages[2]).toMatchObject({
      id: 'review',
      tone: 'attention',
      label: 'Review',
    });
  });
});
