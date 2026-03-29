import { buildSwarmTrajectoryLaunchReadiness } from './swarmTrajectoryLaunchReadiness';

const baseClusterStatus = {
  clusters: [
    {
      leader_id: 1,
      follower_ids: [2, 3],
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
      follower_ids: [5],
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
  follow_map: {
    1: 0,
    2: 1,
    3: 1,
    4: 0,
    5: 4,
  },
  session: {
    exists: true,
    session_id: '20260329_081500',
    total_drones: 5,
  },
};

describe('buildSwarmTrajectoryLaunchReadiness', () => {
  test('blocks launch until every cluster is processed and ready in all-drone scope', () => {
    const readiness = buildSwarmTrajectoryLaunchReadiness({
      clusterStatus: baseClusterStatus,
    });

    expect(readiness.canLaunch).toBe(false);
    expect(readiness.blockers).toContain('1 cluster still has partial outputs.');
    expect(readiness.blockers).toContain('1 cluster issue still requires operator correction before launch.');
    expect(readiness.warnings).toContain('1 advisory item should be reviewed before launch.');
    expect(readiness.summary.readyClusterCount).toBe(1);
    expect(readiness.summary.processedDroneCount).toBe(4);
    expect(readiness.summary.scopeMode).toBe('all');
  });

  test('allows a selected ready subset even when another cluster is incomplete', () => {
    const readiness = buildSwarmTrajectoryLaunchReadiness({
      clusterStatus: baseClusterStatus,
      targetMode: 'selected',
      selectedDrones: ['1', '2', '3'],
    });

    expect(readiness.canLaunch).toBe(true);
    expect(readiness.blockers).toHaveLength(0);
    expect(readiness.warnings).toContain('1 out-of-scope cluster remains incomplete, but is outside the current launch scope.');
    expect(readiness.warnings).toContain('Subset launch targets 3 of 4 processed drones. Non-selected drones will remain idle.');
    expect(readiness.summary.scopeMode).toBe('selected');
    expect(readiness.summary.scopeClusterCount).toBe(1);
    expect(readiness.summary.scopeProcessedDroneCount).toBe(3);
  });

  test('blocks a selected follower when the required leader chain is incomplete', () => {
    const readiness = buildSwarmTrajectoryLaunchReadiness({
      clusterStatus: baseClusterStatus,
      targetMode: 'selected',
      selectedDrones: ['2', '3'],
    });

    expect(readiness.canLaunch).toBe(false);
    expect(readiness.blockers).toContain(
      '2 leader chains are incomplete: Drone 2 requires leader 1; Drone 3 requires leader 1.',
    );
    expect(readiness.summary.scopeSelectionIssueCount).toBe(2);
  });

  test('blocks selected drones without processed outputs in the active package', () => {
    const readiness = buildSwarmTrajectoryLaunchReadiness({
      clusterStatus: baseClusterStatus,
      targetMode: 'selected',
      selectedDrones: ['4', '5'],
    });

    expect(readiness.canLaunch).toBe(false);
    expect(readiness.blockers).toContain(
      'Selected drones 5 do not have processed trajectory outputs in the active package.',
    );
  });
});
