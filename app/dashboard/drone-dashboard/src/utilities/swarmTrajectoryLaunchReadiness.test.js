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
  package_drone_stats: {
    1: {
      route_entry_time_s: 10,
      mission_clock_s: 72,
      route_motion_time_s: 62,
      max_altitude_msl_m: 1465,
      min_altitude_msl_m: 1450,
      altitude_window_m: 15,
    },
    2: {
      route_entry_time_s: 10,
      mission_clock_s: 72,
      route_motion_time_s: 62,
      max_altitude_msl_m: 1458,
      min_altitude_msl_m: 1451,
      altitude_window_m: 7,
    },
    3: {
      route_entry_time_s: 10,
      mission_clock_s: 72,
      route_motion_time_s: 62,
      max_altitude_msl_m: 1462,
      min_altitude_msl_m: 1452,
      altitude_window_m: 10,
    },
    4: {
      route_entry_time_s: 10,
      mission_clock_s: 65,
      route_motion_time_s: 55,
      max_altitude_msl_m: 1448,
      min_altitude_msl_m: 1445,
      altitude_window_m: 3,
    },
  },
  package_stats: {
    available: true,
    drone_count: 4,
    route_entry_time_s: 10,
    mission_clock_s: 72,
    route_motion_time_s: 62,
    max_altitude_msl_m: 1465,
    min_altitude_msl_m: 1445,
    altitude_window_m: 20,
  },
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
  session_changes: {
    has_previous_session: true,
    requires_full_reprocess: false,
  },
  processing_recommendation: {
    action: 'safe_incremental',
    message: 'Ready to process trajectories',
    details: [],
    changes: {
      has_previous_session: true,
      requires_full_reprocess: false,
    },
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
    expect(readiness.summary.packageStats).toEqual({
      available: true,
      droneCount: 4,
      routeEntryTimeS: 10,
      missionClockS: 72,
      routeMotionTimeS: 62,
      maxAltitudeMslM: 1465,
      minAltitudeMslM: 1445,
      altitudeWindowM: 20,
    });
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
    expect(readiness.summary.scopePackageStats).toEqual({
      available: true,
      droneCount: 3,
      routeEntryTimeS: 10,
      missionClockS: 72,
      routeMotionTimeS: 62,
      maxAltitudeMslM: 1465,
      minAltitudeMslM: 1450,
      altitudeWindowM: 15,
    });
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

  test('blocks launch when the active package is stale after a parameter change', () => {
    const readiness = buildSwarmTrajectoryLaunchReadiness({
      clusterStatus: {
        ...baseClusterStatus,
        clusters: baseClusterStatus.clusters.map((cluster) => ({
          ...cluster,
          ready: true,
          state: 'ready',
          issues: [],
          advisories: [],
          processed_drone_count: cluster.expected_drone_count,
        })),
        cluster_summary: {
          cluster_count: 2,
          ready_cluster_count: 2,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 0,
          missing_upload_cluster_count: 0,
          overall_state: 'ready',
        },
        processed_drones: [1, 2, 3, 4, 5],
        session_changes: {
          has_previous_session: true,
          parameters_changed: true,
          requires_full_reprocess: true,
        },
        processing_recommendation: {
          action: 'mandatory_full_reprocess',
          message: 'Parameters changed - full reprocess required',
          details: ['Processing parameters have been modified'],
          changes: {
            has_previous_session: true,
            parameters_changed: true,
            requires_full_reprocess: true,
          },
        },
      },
    });

    expect(readiness.canLaunch).toBe(false);
    expect(readiness.blockers).toContain(
      'Swarm trajectory processing parameters changed since the active package was generated. Reprocess before launch.',
    );
  });
});
