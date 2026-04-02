import { buildSwarmViewModel } from './swarmDesignUtils';
import {
  buildSwarmRuntimeCommand,
  getSwarmRuntimeStartBlockerReason,
  getSwarmRuntimeTelemetrySummary,
  resolveSwarmRuntimeTargets,
  SWARM_RUNTIME_ACTIONS,
  SWARM_RUNTIME_SCOPE,
} from './swarmRuntimeUtils';

describe('swarmRuntimeUtils', () => {
  const config = [
    { hw_id: 1, pos_id: 1 },
    { hw_id: 2, pos_id: 2 },
    { hw_id: 3, pos_id: 3 },
  ];
  const assignments = [
    { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
    { hw_id: 2, follow: 1, offset_x: 3, offset_y: 0, offset_z: 0, frame: 'ned' },
    { hw_id: 3, follow: 2, offset_x: 0, offset_y: 1, offset_z: 0, frame: 'body' },
  ];
  const nowMs = 1_774_290_000_000;

  test('resolveSwarmRuntimeTargets defaults to selected drone scope', () => {
    const viewModel = buildSwarmViewModel(assignments, config);

    expect(resolveSwarmRuntimeTargets(viewModel, SWARM_RUNTIME_SCOPE.DRONE, '3')).toMatchObject({
      targetIds: ['3'],
      scopeLabel: 'Drone 3 · 1 drone',
    });
  });

  test('resolveSwarmRuntimeTargets expands the selected executable cluster', () => {
    const viewModel = buildSwarmViewModel(assignments, config);

    expect(resolveSwarmRuntimeTargets(viewModel, SWARM_RUNTIME_SCOPE.CLUSTER, '3')).toMatchObject({
      targetIds: ['1', '2', '3'],
      scopeLabel: 'P1|H1 cluster · 3 drones',
    });
  });

  test('resolveSwarmRuntimeTargets prefers an explicitly selected cluster for cluster scope', () => {
    const multiClusterViewModel = buildSwarmViewModel(
      [
        { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
        { hw_id: 2, follow: 1, offset_x: 3, offset_y: 0, offset_z: 0, frame: 'ned' },
        { hw_id: 3, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
        { hw_id: 4, follow: 3, offset_x: -3, offset_y: 0, offset_z: 0, frame: 'ned' },
      ],
      [
        { hw_id: 1, pos_id: 1 },
        { hw_id: 2, pos_id: 2 },
        { hw_id: 3, pos_id: 3 },
        { hw_id: 4, pos_id: 4 },
      ]
    );

    expect(resolveSwarmRuntimeTargets(multiClusterViewModel, SWARM_RUNTIME_SCOPE.CLUSTER, '2', '3')).toMatchObject({
      targetIds: ['3', '4'],
      scopeLabel: 'P3|H3 cluster · 2 drones',
    });
  });

  test('resolveSwarmRuntimeTargets blocks invalid cluster scope', () => {
    const invalidViewModel = buildSwarmViewModel(
      [
        { hw_id: 1, follow: 2, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
        { hw_id: 2, follow: 1, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      ],
      [
        { hw_id: 1, pos_id: 1 },
        { hw_id: 2, pos_id: 2 },
      ]
    );

    expect(resolveSwarmRuntimeTargets(invalidViewModel, SWARM_RUNTIME_SCOPE.CLUSTER, '1')).toMatchObject({
      targetIds: [],
      targetSummary: 'Resolve follow-chain warnings before sending cluster-scoped Smart Swarm commands.',
    });
  });

  test('buildSwarmRuntimeCommand preserves action mission type and explicit scope metadata', () => {
    expect(buildSwarmRuntimeCommand(SWARM_RUNTIME_ACTIONS.STOP_HOLD.key, ['2', '3'])).toEqual({
      missionType: '102',
      triggerTime: '0',
      target_drones: ['2', '3'],
      operatorLabel: 'Stop Smart Swarm (Hold)',
      command_scope: 'smart_swarm_runtime',
    });
  });

  test('getSwarmRuntimeStartBlockerReason only blocks unsaved edits inside the target scope', () => {
    const viewModel = buildSwarmViewModel(assignments, config);
    const { selectedDrone, cluster, targetIds } = resolveSwarmRuntimeTargets(
      viewModel,
      SWARM_RUNTIME_SCOPE.CLUSTER,
      '3'
    );
    const targetDrones = targetIds.map((targetId) => viewModel.dronesById[targetId]);

    expect(getSwarmRuntimeStartBlockerReason({
      scope: SWARM_RUNTIME_SCOPE.CLUSTER,
      selectedDrone,
      selectedCluster: cluster,
      targetIds,
      targetDrones,
      dirtyIds: ['99'],
      pendingSyncIds: [],
    })).toBe('');

    expect(getSwarmRuntimeStartBlockerReason({
      scope: SWARM_RUNTIME_SCOPE.CLUSTER,
      selectedDrone,
      selectedCluster: cluster,
      targetIds,
      targetDrones,
      dirtyIds: ['2'],
      pendingSyncIds: [],
    })).toContain('Drone 2');
  });

  test('getSwarmRuntimeTelemetrySummary reports ready, review, and waiting counts', () => {
    const summary = getSwarmRuntimeTelemetrySummary(
      ['1', '2', '3'],
      {
        1: {
          timestamp: nowMs,
          heartbeat_last_seen: nowMs,
          is_ready_to_arm: true,
          readiness_status: 'ready',
          readiness_summary: 'Ready to fly',
          preflight_blockers: [],
          preflight_warnings: [],
          status_messages: [],
          readiness_checks: [],
        },
        2: {
          timestamp: nowMs - 12_000,
          heartbeat_last_seen: nowMs - 2_000,
          is_ready_to_arm: true,
          readiness_status: 'warning',
          readiness_summary: 'Telemetry delayed.',
          preflight_blockers: [],
          preflight_warnings: [
            {
              source: 'telemetry',
              severity: 'warning',
              message: 'Telemetry delayed.',
            },
          ],
          status_messages: [],
          readiness_checks: [],
        },
      },
      nowMs
    );

    expect(summary).toMatchObject({
      total: 3,
      telemetryCount: 2,
      readyCount: 1,
      reviewCount: 1,
      waitingCount: 1,
    });
  });
});
