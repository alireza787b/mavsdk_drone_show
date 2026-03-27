import {
  buildFallbackClusters,
  buildSwarmTrajectoryViewModel,
  getClusterStateMeta,
} from './swarmTrajectoryViewModel';

describe('swarmTrajectoryViewModel', () => {
  test('getClusterStateMeta maps known cluster states', () => {
    expect(getClusterStateMeta({ state: 'ready' })).toMatchObject({
      tone: 'ready',
      label: 'Ready',
    });

    expect(getClusterStateMeta({ state: 'partial_outputs' })).toMatchObject({
      tone: 'warning',
      label: 'Partial Outputs',
    });

    expect(getClusterStateMeta({ leader_uploaded: true })).toMatchObject({
      tone: 'processing',
      label: 'Needs Processing',
    });

    expect(getClusterStateMeta({})).toMatchObject({
      tone: 'missing',
      label: 'Missing Leader CSV',
    });
  });

  test('buildFallbackClusters derives leader upload and follower counts', () => {
    const clusters = buildFallbackClusters({
      leaders: [1, 5],
      hierarchies: { 1: 2, 5: 1 },
      followerDetails: { 1: [2, 3], 5: [6] },
      uploadedLeaderIds: [1],
    });

    expect(clusters).toEqual([
      expect.objectContaining({
        leader_id: 1,
        follower_ids: [2, 3],
        follower_count: 2,
        state: 'needs_processing',
      }),
      expect.objectContaining({
        leader_id: 5,
        follower_ids: [6],
        follower_count: 1,
        state: 'missing_upload',
      }),
    ]);
  });

  test('buildSwarmTrajectoryViewModel prefers backend truth and keeps partial output visibility', () => {
    const viewModel = buildSwarmTrajectoryViewModel({
      leaders: [1, 5],
      hierarchies: { 1: 2, 5: 1 },
      followerDetails: { 1: [2, 3], 5: [6] },
      uploadedLeaders: [1],
      status: {
        uploaded_leaders: [1],
        expected_top_leaders: [1, 5],
        missing_uploaded_leaders: [5],
        orphan_uploaded_leaders: [],
        processed_trajectories: 2,
        processed_drones: [1, 2],
        clusters: [
          {
            leader_id: 1,
            follower_ids: [2, 3],
            follower_count: 2,
            expected_drone_count: 3,
            processed_drone_count: 2,
            ready: false,
            state: 'partial_outputs',
            leader_uploaded: true,
            leader_processed: true,
            processed_follower_ids: [2],
            missing_follower_ids: [3],
            cluster_plot_available: true,
            leader_plot_available: true,
            issues: ['Missing follower output for drone 3'],
            advisories: [],
          },
          {
            leader_id: 5,
            follower_ids: [6],
            follower_count: 1,
            expected_drone_count: 2,
            processed_drone_count: 0,
            ready: false,
            state: 'missing_upload',
            leader_uploaded: false,
            leader_processed: false,
            processed_follower_ids: [],
            missing_follower_ids: [6],
            cluster_plot_available: false,
            leader_plot_available: false,
            issues: ['Upload leader CSV for cluster 5'],
            advisories: [],
          },
        ],
        cluster_summary: {
          cluster_count: 2,
          ready_cluster_count: 0,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 1,
          missing_upload_cluster_count: 1,
          processed_cluster_count: 1,
          all_clusters_ready: false,
          overall_state: 'partial',
        },
        session: {
          exists: true,
          session_id: 'session-123',
          timestamp: '2026-03-27T12:00:00Z',
          processed_leaders: [1],
          total_drones: 2,
        },
      },
    });

    expect(viewModel.clusterSummary).toMatchObject({
      cluster_count: 2,
      partial_output_cluster_count: 1,
      missing_upload_cluster_count: 1,
      overall_state: 'partial',
    });
    expect(viewModel.currentOutcome).toBe('partial');
    expect(viewModel.processedDroneCount).toBe(2);
    expect(viewModel.visibleClusterLeaders).toEqual([1]);
    expect(viewModel.missingLeaderIds).toEqual([5]);
    expect(viewModel.issueCount).toBe(2);
    expect(viewModel.session).toMatchObject({
      exists: true,
      session_id: 'session-123',
    });
  });
});
