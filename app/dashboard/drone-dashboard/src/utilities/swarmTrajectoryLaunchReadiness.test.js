import { buildSwarmTrajectoryLaunchReadiness } from './swarmTrajectoryLaunchReadiness';

describe('buildSwarmTrajectoryLaunchReadiness', () => {
  test('blocks launch until every cluster is processed and ready', () => {
    const readiness = buildSwarmTrajectoryLaunchReadiness({
      clusterStatus: {
        clusters: [
          {
            leader_id: 1,
            ready: true,
            leader_uploaded: true,
            state: 'ready',
            expected_drone_count: 3,
            processed_drone_count: 3,
            issues: [],
            advisories: [],
          },
          {
            leader_id: 4,
            ready: false,
            leader_uploaded: true,
            state: 'partial_outputs',
            expected_drone_count: 2,
            processed_drone_count: 1,
            issues: ['Follower 5 output missing'],
            advisories: ['Cluster plot needs review'],
          },
        ],
        cluster_summary: {
          cluster_count: 2,
          ready_cluster_count: 1,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 1,
          missing_upload_cluster_count: 0,
          overall_state: 'partial',
        },
        processed_drones: [1, 2, 3, 4],
        orphan_uploaded_leaders: [],
        session: {
          exists: true,
          session_id: '20260329_081500',
          total_drones: 5,
        },
      },
    });

    expect(readiness.canLaunch).toBe(false);
    expect(readiness.blockers).toContain('1 cluster still has partial outputs.');
    expect(readiness.blockers).toContain('1 cluster issue still requires operator correction before launch.');
    expect(readiness.warnings).toContain('1 advisory item should be reviewed before launch.');
    expect(readiness.summary.readyClusterCount).toBe(1);
    expect(readiness.summary.processedDroneCount).toBe(4);
  });

  test('allows launch once backend truth reports a ready package', () => {
    const readiness = buildSwarmTrajectoryLaunchReadiness({
      clusterStatus: {
        clusters: [
          {
            leader_id: 1,
            ready: true,
            leader_uploaded: true,
            state: 'ready',
            expected_drone_count: 3,
            processed_drone_count: 3,
            issues: [],
            advisories: [],
          },
          {
            leader_id: 4,
            ready: true,
            leader_uploaded: true,
            state: 'ready',
            expected_drone_count: 2,
            processed_drone_count: 2,
            issues: [],
            advisories: [],
          },
        ],
        cluster_summary: {
          cluster_count: 2,
          ready_cluster_count: 2,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 0,
          missing_upload_cluster_count: 0,
          overall_state: 'ready',
        },
        processed_drones: [1, 2, 3, 4, 5],
        orphan_uploaded_leaders: [],
        session: {
          exists: true,
          session_id: '20260329_081500',
          total_drones: 5,
        },
      },
    });

    expect(readiness.canLaunch).toBe(true);
    expect(readiness.blockers).toHaveLength(0);
    expect(readiness.warnings).toHaveLength(0);
    expect(readiness.summary.readyClusterCount).toBe(2);
    expect(readiness.summary.expectedDroneCount).toBe(5);
  });
});
