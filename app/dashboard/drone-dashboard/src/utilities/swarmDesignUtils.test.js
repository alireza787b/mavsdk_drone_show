import {
  buildClusterScopeOptions,
  buildSwarmViewModel,
  buildWorkingSwarmAssignments,
  calculateClusterPlotData,
  getDirtyAssignmentIds,
} from './swarmDesignUtils';

describe('swarmDesignUtils', () => {
  test('buildWorkingSwarmAssignments merges config order, adds defaults, and prunes removed assignments', () => {
    const config = [
      { hw_id: 1, pos_id: 1, ip: '10.0.0.1' },
      { hw_id: 2, pos_id: 4, ip: '10.0.0.2' },
      { hw_id: 3, pos_id: 3, ip: '10.0.0.3' },
    ];
    const swarm = [
      { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 3, follow: 1, offset_x: 2, offset_y: 1, offset_z: 0, frame: 'body' },
      { hw_id: 9, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
    ];

    const result = buildWorkingSwarmAssignments(config, swarm);

    expect(result.assignments.map((assignment) => assignment.hw_id)).toEqual(['1', '2', '3']);
    expect(result.assignments[1]).toMatchObject({
      hw_id: '2',
      follow: '0',
      offset_x: 0,
      offset_y: 0,
      offset_z: 0,
      frame: 'ned',
    });
    expect(result.syncChanges).toEqual({
      addedIds: ['2'],
      removedIds: ['9'],
    });
  });

  test('buildSwarmViewModel exposes roles, role swaps, and blocking warnings', () => {
    const config = [
      { hw_id: 1, pos_id: 1 },
      { hw_id: 2, pos_id: 9, callsign: 'VIPER-2' },
      { hw_id: 3, pos_id: 3 },
      { hw_id: 4, pos_id: 4 },
      { hw_id: 5, pos_id: 5 },
      { hw_id: 6, pos_id: 6 },
    ];
    const assignments = [
      { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 2, follow: 1, offset_x: 1, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 3, follow: 2, offset_x: 0, offset_y: 1, offset_z: 0, frame: 'body' },
      { hw_id: 4, follow: 99, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 5, follow: 5, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 6, follow: 0, offset_x: 2, offset_y: 0, offset_z: 0, frame: 'ned' },
    ];

    const viewModel = buildSwarmViewModel(assignments, config);

    expect(viewModel.dronesById['1'].role).toBe('topLeader');
    expect(viewModel.dronesById['2'].role).toBe('relayLeader');
    expect(viewModel.dronesById['3'].role).toBe('follower');
    expect(viewModel.dronesById['2'].isRoleSwap).toBe(true);
    expect(viewModel.dronesById['2'].title).toBe('Drone 2');
    expect(viewModel.dronesById['2'].subtitle).toBe('Show Slot 9');
    expect(viewModel.dronesById['2'].alias).toBe('VIPER-2');
    expect(viewModel.followOptions[0].label).toContain('P1|H1');
    expect(viewModel.dronesById['4'].warnings.map((warning) => warning.code)).toContain('missing-leader');
    expect(viewModel.dronesById['4'].warnings[0].message).toContain('Drone 99');
    expect(viewModel.dronesById['5'].warnings.map((warning) => warning.code)).toEqual(
      expect.arrayContaining(['self-follow', 'cycle'])
    );
    expect(viewModel.dronesById['6'].warnings.map((warning) => warning.code)).toContain('leader-offset-ignored');
    expect(viewModel.summary.clusterCount).toBe(2);
    expect(viewModel.summary.blockingIssueCount).toBe(2);
  });

  test('calculateClusterPlotData returns only the selected cluster with cumulative offsets', () => {
    const config = [
      { hw_id: 1, pos_id: 1 },
      { hw_id: 2, pos_id: 2 },
      { hw_id: 3, pos_id: 3 },
      { hw_id: 9, pos_id: 9 },
    ];
    const assignments = [
      { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 2, follow: 1, offset_x: 5, offset_y: 2, offset_z: 1, frame: 'ned' },
      { hw_id: 3, follow: 2, offset_x: 1, offset_y: 0, offset_z: 2, frame: 'body' },
      { hw_id: 9, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
    ];

    const result = calculateClusterPlotData(assignments, config, '1');

    expect(result.clusterId).toBe('1');
    expect(result.data.map((point) => point.hw_id)).toEqual(['1', '2', '3']);
    expect(result.data.find((point) => point.hw_id === '2')).toMatchObject({
      x: 2,
      y: 5,
      z: 1,
    });
    expect(result.data.find((point) => point.hw_id === '3')).toMatchObject({
      x: 2,
      y: 6,
      z: 3,
    });
  });

  test('calculateClusterPlotData supports all executable clusters overlay', () => {
    const config = [
      { hw_id: 1, pos_id: 1 },
      { hw_id: 2, pos_id: 2 },
      { hw_id: 4, pos_id: 4 },
      { hw_id: 5, pos_id: 5 },
    ];
    const assignments = [
      { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 2, follow: 1, offset_x: 3, offset_y: 1, offset_z: 0, frame: 'ned' },
      { hw_id: 4, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 5, follow: 4, offset_x: -2, offset_y: 4, offset_z: 1, frame: 'body' },
    ];

    const result = calculateClusterPlotData(assignments, config, 'all');

    expect(result.clusterId).toBe('all');
    expect(result.data).toHaveLength(4);
    expect(result.description).toContain('2 clusters');
    expect(result.data.find((point) => point.hw_id === '2')).toMatchObject({
      clusterId: '1',
      x: 1,
      y: 3,
      z: 0,
    });
    expect(result.data.find((point) => point.hw_id === '5')).toMatchObject({
      clusterId: '4',
      x: 4,
      y: -2,
      z: 1,
    });
  });

  test('buildClusterScopeOptions uses compact leader identities for cluster scopes', () => {
    const viewModel = buildSwarmViewModel([
      { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 2, follow: 1, offset_x: 3, offset_y: 1, offset_z: 0, frame: 'ned' },
      { hw_id: 4, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
    ], [
      { hw_id: 1, pos_id: 1 },
      { hw_id: 2, pos_id: 2 },
      { hw_id: 4, pos_id: 9 },
    ]);

    expect(buildClusterScopeOptions(viewModel.clusters, viewModel.summary.totalDrones)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: '1', label: 'P1|H1 cluster', count: 2 }),
        expect.objectContaining({ id: '4', label: 'P9|H4 cluster', count: 1 }),
      ])
    );
  });

  test('getDirtyAssignmentIds compares normalized swarm assignments', () => {
    const baseline = [
      { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
      { hw_id: 2, follow: 1, offset_x: 1, offset_y: 0, offset_z: 0, frame: 'ned' },
    ];
    const current = [
      { hw_id: '1', follow: '0', offset_x: '0', offset_y: '0', offset_z: '0', frame: 'ned' },
      { hw_id: '2', follow: '1', offset_x: '2.5', offset_y: '0', offset_z: '0', frame: 'ned' },
    ];

    expect(getDirtyAssignmentIds(current, baseline)).toEqual(['2']);
  });
});
