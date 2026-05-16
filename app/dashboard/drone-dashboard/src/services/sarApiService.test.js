import {
  abortMission,
  batchElevation,
  cancelPlanningJob,
  computePlan,
  createPlanningJob,
  getFindings,
  getMissionHandoff,
  getPlanningJob,
  getMissionWorkspace,
  launchMission,
  listMissions,
  revalidateLaunch,
  updateFinding,
} from './sarApiService';
import {
  buildSarUrl,
  fetchGcsResource,
  patchGcsResource,
  postGcsResource,
} from './gcsApiService';

jest.mock('./gcsApiService', () => ({
  buildSarUrl: jest.fn((suffix = '') => `http://gcs.test:5030/api/sar${suffix}`),
  deleteGcsResource: jest.fn(),
  fetchGcsResource: jest.fn(),
  patchGcsResource: jest.fn(),
  postGcsResource: jest.fn(),
}));

describe('sarApiService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    buildSarUrl.mockImplementation((suffix = '') => `http://gcs.test:5030/api/sar${suffix}`);
  });

  it('uses the centralized SAR base route with planning timeout defaults', async () => {
    postGcsResource.mockResolvedValue({ data: { mission_id: 'sar-1' } });

    await computePlan({ search_area: { type: 'polygon', points: [] } });

    expect(buildSarUrl).toHaveBeenCalledWith('/mission/plan');
    expect(postGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/sar/mission/plan',
      { search_area: { type: 'polygon', points: [] } },
      { timeout: 30000 }
    );
  });

  it('lists persisted QuickScout missions through the shared SAR route builder', async () => {
    fetchGcsResource.mockResolvedValue({ data: { missions: [], count: 0 } });

    await listMissions({ limit: 5, state: 'ready' });

    expect(buildSarUrl).toHaveBeenCalledWith('/missions?limit=5&state=ready');
    expect(fetchGcsResource).toHaveBeenCalledWith('http://gcs.test:5030/api/sar/missions?limit=5&state=ready');
  });

  it('uses planning job endpoints for long-running QuickScout compute', async () => {
    postGcsResource.mockResolvedValueOnce({ data: { job_id: 'job-1', status: 'queued' } });
    fetchGcsResource.mockResolvedValueOnce({ data: { job_id: 'job-1', status: 'running' } });
    postGcsResource.mockResolvedValueOnce({ data: { job_id: 'job-1', status: 'canceled' } });

    await createPlanningJob({ search_area: { type: 'polygon', points: [] } });
    await getPlanningJob('job/1');
    await cancelPlanningJob('job/1');

    expect(buildSarUrl).toHaveBeenNthCalledWith(1, '/mission/plan/jobs');
    expect(postGcsResource).toHaveBeenNthCalledWith(
      1,
      'http://gcs.test:5030/api/sar/mission/plan/jobs',
      { search_area: { type: 'polygon', points: [] } }
    );
    expect(buildSarUrl).toHaveBeenNthCalledWith(2, '/mission/plan/jobs/job%2F1');
    expect(fetchGcsResource).toHaveBeenCalledWith('http://gcs.test:5030/api/sar/mission/plan/jobs/job%2F1');
    expect(buildSarUrl).toHaveBeenNthCalledWith(3, '/mission/plan/jobs/job%2F1/cancel');
    expect(postGcsResource).toHaveBeenNthCalledWith(
      2,
      'http://gcs.test:5030/api/sar/mission/plan/jobs/job%2F1/cancel'
    );
  });

  it('uses revalidation token payloads for staged QuickScout launches', async () => {
    postGcsResource.mockResolvedValue({ data: { launchable: true } });

    await revalidateLaunch('mission/alpha');
    await launchMission('mission/alpha', { revalidationToken: 'token-1' });

    expect(buildSarUrl).toHaveBeenNthCalledWith(1, '/mission/mission%2Falpha/revalidate-launch');
    expect(postGcsResource).toHaveBeenNthCalledWith(
      1,
      'http://gcs.test:5030/api/sar/mission/mission%2Falpha/revalidate-launch'
    );
    expect(buildSarUrl).toHaveBeenNthCalledWith(2, '/mission/launch?mission_id=mission%2Falpha');
    expect(postGcsResource).toHaveBeenNthCalledWith(
      2,
      'http://gcs.test:5030/api/sar/mission/launch?mission_id=mission%2Falpha',
      { revalidation_token: 'token-1' }
    );
  });

  it('encodes mission ids and repeated drone filters for abort requests', async () => {
    postGcsResource.mockResolvedValue({ data: { success: true } });

    await abortMission('mission/alpha', ['1', '2'], 'hold_position');

    expect(buildSarUrl).toHaveBeenCalledWith(
      '/mission/mission%2Falpha/abort?return_behavior=hold_position&pos_ids=1&pos_ids=2'
    );
    expect(postGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/sar/mission/mission%2Falpha/abort?return_behavior=hold_position&pos_ids=1&pos_ids=2'
    );
  });

  it('encodes mission ids for workspace recovery requests', async () => {
    fetchGcsResource.mockResolvedValue({ data: { operation: { mission_id: 'mission/alpha' } } });

    await getMissionWorkspace('mission/alpha');

    expect(buildSarUrl).toHaveBeenCalledWith('/mission/mission%2Falpha/workspace');
    expect(fetchGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/sar/mission/mission%2Falpha/workspace'
    );
  });

  it('encodes mission ids for canonical handoff requests', async () => {
    fetchGcsResource.mockResolvedValue({ data: { mission_id: 'mission/alpha' } });

    await getMissionHandoff('mission/alpha');

    expect(buildSarUrl).toHaveBeenCalledWith('/mission/mission%2Falpha/handoff');
    expect(fetchGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/sar/mission/mission%2Falpha/handoff'
    );
  });

  it('encodes finding ids and delegates payload updates through the shared SAR route builder', async () => {
    patchGcsResource.mockResolvedValue({ data: { id: 'finding/1', summary: 'updated' } });

    await updateFinding('finding/1', { summary: 'updated' });

    expect(buildSarUrl).toHaveBeenCalledWith('/findings/finding%2F1');
    expect(patchGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/sar/findings/finding%2F1',
      { summary: 'updated' }
    );
  });

  it('lists findings through the canonical SAR findings route', async () => {
    fetchGcsResource.mockResolvedValue({ data: [] });

    await getFindings('mission-1');

    expect(buildSarUrl).toHaveBeenCalledWith('/findings?mission_id=mission-1');
    expect(fetchGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/sar/findings?mission_id=mission-1'
    );
  });

  it('delegates batch elevation payloads through the shared SAR API surface', async () => {
    postGcsResource.mockResolvedValue({ data: [{ elevation: 12 }] });

    await batchElevation([{ lat: 1, lng: 2 }]);

    expect(buildSarUrl).toHaveBeenCalledWith('/elevation/batch');
    expect(postGcsResource).toHaveBeenCalledWith(
      'http://gcs.test:5030/api/sar/elevation/batch',
      [{ lat: 1, lng: 2 }]
    );
  });
});
