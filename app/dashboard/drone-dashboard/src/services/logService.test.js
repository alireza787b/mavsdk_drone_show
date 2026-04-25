// src/services/logService.test.js
import axios from 'axios';
import {
  buildDroneUlogDownloadURL,
  buildStreamURL,
  createDroneUlogDownloadJob,
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
  getFleetConfigResponse,
  getFleetHeartbeatsResponse,
} from './gcsApiService';

jest.mock('axios');
jest.mock('./gcsApiService', () => ({
  buildLogsUrl: jest.fn((suffix = '') => `http://gcs.test:5030/api/logs${suffix}`),
  getFleetConfigResponse: jest.fn(),
  getFleetHeartbeatsResponse: jest.fn(),
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
    axios.get.mockResolvedValue({ data: [] });

    await getDroneSessions('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/sessions');
    expect(axios.get).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/sessions');
  });

  test('builds onboard ULog browser download URL', () => {
    const url = buildDroneUlogDownloadURL('leader/1', 'job:7');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/downloads/job%3A7/content');
    expect(url).toBe('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/downloads/job%3A7/content');
  });

  test('requests drone onboard ULog policy through the GCS log proxy', async () => {
    axios.get.mockResolvedValue({ data: { policy: { supported: true } } });

    const result = await getDroneUlogPolicy('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/policy');
    expect(axios.get).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/policy');
    expect(result.policy.supported).toBe(true);
  });

  test('requests drone onboard ULog files through the GCS log proxy', async () => {
    axios.get.mockResolvedValue({ data: { files: [] } });

    const result = await getDroneUlogFiles('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/files');
    expect(axios.get).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/files');
    expect(result.files).toEqual([]);
  });

  test('creates and polls onboard ULog download jobs', async () => {
    axios.post.mockResolvedValue({ data: { job: { job_id: 'job-1' } } });
    axios.get.mockResolvedValue({ data: { job: { job_id: 'job-1', status: 'ready' } } });

    const created = await createDroneUlogDownloadJob('leader/1', 12);
    const status = await getDroneUlogDownloadJob('leader/1', 'job-1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/files/12/download');
    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/downloads/job-1');
    expect(created.job.job_id).toBe('job-1');
    expect(status.job.status).toBe('ready');
  });

  test('sends onboard ULog erase-all through the GCS log proxy', async () => {
    axios.post.mockResolvedValue({ data: { status: 'accepted' } });

    const result = await eraseAllDroneUlogs('leader/1');

    expect(buildLogsUrl).toHaveBeenCalledWith('/drone/leader%2F1/ulog/erase-all');
    expect(axios.post).toHaveBeenCalledWith('http://gcs.test:5030/api/logs/drone/leader%2F1/ulog/erase-all');
    expect(result.status).toBe('accepted');
  });
});
