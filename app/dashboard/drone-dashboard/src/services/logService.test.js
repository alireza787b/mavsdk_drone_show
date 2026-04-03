// src/services/logService.test.js
import axios from 'axios';
import {
  buildStreamURL,
  getConfiguredDrones,
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
  buildLogsUrl: jest.fn((suffix = '') => `http://gcs.test:5000/api/logs${suffix}`),
  getFleetConfigResponse: jest.fn(),
  getFleetHeartbeatsResponse: jest.fn(),
}));

describe('logService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    buildLogsUrl.mockImplementation((suffix = '') => `http://gcs.test:5000/api/logs${suffix}`);
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
    expect(axios.get).toHaveBeenCalledWith('http://gcs.test:5000/api/logs/drone/leader%2F1/sessions');
  });
});
