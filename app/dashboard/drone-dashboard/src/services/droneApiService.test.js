import {
  clearProcessedData,
  getRecentCommands,
  getSwarmClusterStatus,
  processTrajectories,
  sendDroneCommand,
  uploadSwarmTrajectory,
} from './droneApiService';
import {
  COMMAND_SUBMIT_TIMEOUT_MS,
  buildSwarmTrajectoryUrl,
  clearProcessedSwarmTrajectoriesResponse,
  getRecentCommandsResponse,
  getSwarmLeadersResponse,
  getSwarmTrajectoryStatusResponse,
  postGcsResource,
  processSwarmTrajectoriesResponse,
  submitCommandResponse,
} from './gcsApiService';

jest.mock('./gcsApiService', () => ({
  COMMAND_SUBMIT_TIMEOUT_MS: 12000,
  buildSwarmTrajectoryUrl: jest.fn(),
  clearProcessedSwarmTrajectoriesResponse: jest.fn(),
  getActiveCommandsResponse: jest.fn(),
  getCommandStatusResponse: jest.fn(),
  getRecentCommandsResponse: jest.fn(),
  getSwarmLeadersResponse: jest.fn(),
  getSwarmTrajectoryPolicyResponse: jest.fn(),
  getSwarmTrajectoryStatusResponse: jest.fn(),
  postGcsResource: jest.fn(),
  processSwarmTrajectoriesResponse: jest.fn(),
  submitCommandResponse: jest.fn(),
}));

describe('droneApiService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('delegates command submission to the centralized GCS service', async () => {
    submitCommandResponse.mockResolvedValue({ data: { success: true, command_id: 'cmd-1' } });

    const result = await sendDroneCommand({ missionType: '4', target_drones: ['1'] });

    expect(submitCommandResponse).toHaveBeenCalledWith(
      { missionType: '4', target_drones: ['1'] },
      { timeout: COMMAND_SUBMIT_TIMEOUT_MS },
    );
    expect(result).toEqual({ success: true, command_id: 'cmd-1' });
  });

  it('delegates recent command filtering to the centralized GCS service', async () => {
    getRecentCommandsResponse.mockResolvedValue({ data: { commands: [] } });

    await getRecentCommands({ limit: 5, status: 'running', missionType: 7 });

    expect(getRecentCommandsResponse).toHaveBeenCalledWith({
      limit: 5,
      status: 'running',
      missionType: 7,
    });
  });

  it('uses centralized route building for swarm trajectory uploads', async () => {
    buildSwarmTrajectoryUrl.mockReturnValue('http://gcs.test:5030/api/v1/swarm-trajectories/upload/1');
    postGcsResource.mockResolvedValue({ data: { success: true } });

    const file = new Blob(['hw_id,follow\n1,0\n'], { type: 'text/csv' });
    await uploadSwarmTrajectory('1', file, 'Drone 1.csv');

    expect(buildSwarmTrajectoryUrl).toHaveBeenCalledWith('/upload/1');
    expect(postGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/v1/swarm-trajectories/upload/1',
      expect.any(FormData)
    );
  });

  it('combines leader and status responses into normalized cluster state', async () => {
    getSwarmLeadersResponse.mockResolvedValue({
      data: {
        success: true,
        leaders: ['1'],
        follower_details: { 1: ['2', '3'] },
        hierarchies: { 1: 2 },
        uploaded_leaders: ['1'],
      },
    });
    getSwarmTrajectoryStatusResponse.mockResolvedValue({
      data: {
        success: true,
        status: {
          clusters: [
            {
              leader_id: '1',
              follower_ids: ['2', '3'],
              follower_count: 2,
              expected_drone_count: 3,
              processed_drone_count: 3,
              ready: true,
              state: 'ready',
              leader_uploaded: true,
              leader_processed: true,
            },
          ],
          processed_trajectories: 3,
          processed_drones: ['1', '2', '3'],
          processed_leaders: ['1'],
          cluster_summary: { overall_state: 'ready' },
        },
      },
    });

    const result = await getSwarmClusterStatus();

    expect(result.total_leaders).toBe(1);
    expect(result.total_followers).toBe(2);
    expect(result.overall_state).toBe('ready');
    expect(result.clusters[0]).toMatchObject({
      leader_id: '1',
      follower_ids: ['2', '3'],
      ready: true,
      state: 'ready',
      follower_count: 2,
    });
  });

  it('delegates trajectory process and clear actions to the centralized GCS service', async () => {
    processSwarmTrajectoriesResponse.mockResolvedValue({ data: { success: true } });
    clearProcessedSwarmTrajectoriesResponse.mockResolvedValue({ data: { success: true } });

    await processTrajectories({ force_clear: true, auto_reload: false });
    await clearProcessedData();

    expect(processSwarmTrajectoriesResponse).toHaveBeenCalledWith({
      force_clear: true,
      auto_reload: false,
    });
    expect(clearProcessedSwarmTrajectoriesResponse).toHaveBeenCalledWith();
  });
});
