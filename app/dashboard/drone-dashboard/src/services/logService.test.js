// src/services/logService.test.js
import {
  buildDroneUlogDownloadURL,
  buildStreamURL,
  createDroneUlogDownloadJob,
  deleteDroneUlogDownloadJob,
  eraseAllDroneUlogs,
  getConfiguredDrones,
  getDroneUlogFiles,
  getDroneUlogPolicy,
  getDroneUlogDownloadJob,
  getDroneSessions,
  getHeartbeats,
} from './logService';
import {
  buildLogsUrl,
  deleteGcsResource,
  fetchGcsResource,
  getFleetConfigResponse,
  getFleetHeartbeatsResponse,
  postGcsResource,
} from './gcsApiService';

jest.mock('./gcsApiService', () => ({
  buildLogsUrl: jest.fn((suffix = '') => `http://gcs.test:5030/api/logs${suffix}`),
  deleteGcsResource: jest.fn(),
  fetchGcsResource: jest.fn(),
  getFleetConfigResponse: jest.fn(),
  getFleetHeartbeatsResponse: jest.fn(),
  postGcsResource: jest.fn(),
}));

describe('logService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    buildLogsUrl.mockImplementation((suffix = '') => `http://gcs.test:5030/api/logs${suffix}`);
  });

  describe('buildStreamURL', () => {
    test('returns base URL with no filters', () => {
      const url = buildStreamURL();
      expect(url).toContain('/api/logs/stream');
      expect(url).not.toContain('?');
    });

    test('appends level filter', () => {
      const url = buildStreamURL({ level: 'WARNING' });
      expect(url).toContain('level=WARNING');
    });

    test('uses drone proxy URL when droneId provided', () => {
      const url = buildStreamURL({}, 5);
      expect(url).toContain('/api/logs/drone/5/stream');
    });

    test('combines filters', () => {
      const url = buildStreamURL({ level: 'ERROR', component: 'gcs' });
      expect(url).toContain('level=ERROR');
      expect(url).toContain('component=gcs');
    });
  });

  test('delegates configured drone inventory to the centralized fleet config response', async () => {
    getFleetConfigResponse.mockResolvedValue({ data: [{ hw_id: '1' }] });

    const result = await getConfiguredDrones();

    expect(getFleetConfigResponse).toHaveBeenCalledWith();
    expect(result).toEqual([{ hw_id: '1' }]);
  });

  test('delegates heartbeats to the centralized fleet heartbeat response', async () => {
    getFleetHeartbeatsResponse.mockResolvedValue({ data: { 1: { last_seen: 10 } } });

    const result = await getHeartbeats();

    expect(getFleetHeartbeatsResponse).toHaveBeenCalledWith();
    expect(result).toEqual({ 1: { last_seen: 10 } });
  });

  test('encodes drone ids in drone session routes', async () => {
    fetchGcsResource.mockResolvedValue({ data: [] });

    await getDroneSessions('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/sessions');
    expect(fetchGcsResource).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/sessions');
  });

  test('builds onboard ULog browser download URL', () => {
    const url = buildDroneUlogDownloadURL('leader/1', 'job:7');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/downloads/job%3A7/content');
    expect(url).toBe('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/downloads/job%3A7/content');
  });

  test('requests drone onboard ULog policy through the GCS log proxy', async () => {
    fetchGcsResource.mockResolvedValue({ data: { policy: { supported: true } } });

    const result = await getDroneUlogPolicy('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/policy');
    expect(fetchGcsResource).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/policy');
    expect(result.policy.supported).toBe(true);
  });

  test('requests drone onboard ULog files through the GCS log proxy', async () => {
    fetchGcsResource.mockResolvedValue({ data: { files: [] } });

    const result = await getDroneUlogFiles('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/files');
    expect(fetchGcsResource).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/files');
    expect(result.files).toEqual([]);
  });

  test('creates and polls onboard ULog download jobs', async () => {
    postGcsResource.mockResolvedValue({ data: { job: { job_id: 'job-1' } } });
    fetchGcsResource.mockResolvedValue({ data: { job: { job_id: 'job-1', status: 'ready' } } });

    const created = await createDroneUlogDownloadJob('leader/1', 12);
    const status = await getDroneUlogDownloadJob('leader/1', 'job-1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/files/12/download');
    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/downloads/job-1');
    expect(created.job.job_id).toBe('job-1');
    expect(status.job.status).toBe('ready');
  });

  test('deletes onboard ULog download jobs through the authenticated GCS helper', async () => {
    deleteGcsResource.mockResolvedValue({ data: { status: 'deleted' } });

    const result = await deleteDroneUlogDownloadJob('leader/1', 'job-1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/downloads/job-1');
    expect(deleteGcsResource).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/downloads/job-1');
    expect(result.status).toBe('deleted');
  });

  test('sends onboard ULog erase-all through the GCS log proxy', async () => {
    postGcsResource.mockResolvedValue({ data: { status: 'accepted' } });

    const result = await eraseAllDroneUlogs('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/erase-all');
    expect(postGcsResource).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/erase-all');
    expect(result.status).toBe('accepted');
  });
});
