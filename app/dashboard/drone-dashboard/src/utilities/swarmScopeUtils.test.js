import {
  buildLeaderChainSelectionIssues,
  buildNormalizedFollowMap,
  getClusterMemberIds,
} from './swarmScopeUtils';

describe('swarmScopeUtils', () => {
  test('buildNormalizedFollowMap normalizes string ids', () => {
    const followMap = buildNormalizedFollowMap({
      '1': '0',
      '2': '1',
      '3': 2,
    });

    expect(Array.from(followMap.entries())).toEqual([
      [1, 0],
      [2, 1],
      [3, 2],
    ]);
  });

  test('getClusterMemberIds returns leader plus followers', () => {
    expect(
      getClusterMemberIds({
        leader_id: '1',
        follower_ids: ['2', 3],
      }),
    ).toEqual([1, 2, 3]);
  });

  test('buildLeaderChainSelectionIssues flags missing leader chains recursively', () => {
    const issues = buildLeaderChainSelectionIssues({
      followMap: {
        '1': 0,
        '2': 1,
        '3': 2,
        '4': 0,
      },
      activeIds: [2, 3],
    });

    expect(issues).toContainEqual({
      droneId: 2,
      leaderId: 1,
      issue: 'leader_not_in_active_mission_set',
    });
    expect(issues).toContainEqual({
      droneId: 3,
      leaderId: 1,
      issue: 'leader_not_in_active_mission_set',
    });
  });

  test('buildLeaderChainSelectionIssues accepts complete selected chains', () => {
    const issues = buildLeaderChainSelectionIssues({
      followMap: {
        '1': 0,
        '2': 1,
        '3': 2,
      },
      activeIds: [1, 2, 3],
    });

    expect(issues).toEqual([]);
  });
});
