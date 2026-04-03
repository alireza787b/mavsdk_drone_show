import axios from 'axios';
import {
  buildGcsUrl,
  buildLogsUrl,
  buildSarUrl,
  GCS_ROUTE_KEYS,
  getCommandStatusResponse,
  getFleetTelemetryResponse,
  getRecentCommandsResponse,
  resolveGcsRoute,
  resolveGcsRouteKey,
  saveSwarmConfigResponse,
  unwrapFleetTelemetryPayload,
} from './gcsApiService';

const mockGetBackendURL = jest.fn(() => 'http://gcs.test:5000');

jest.mock('axios');
jest.mock('../config/apiConfig', () => ({
  __esModule: true,
  getBackendURL: (...args) => mockGetBackendURL(...args),
  default: {
    getBackendURL: (...args) => mockGetBackendURL(...args),
  },
}));

describe('gcsApiService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetBackendURL.mockReturnValue('http://gcs.test:5000');
  });

  it('resolves semantic route keys to canonical URLs', () => {
    expect(resolveGcsRoute(GCS_ROUTE_KEYS.fleetTelemetry)).toBe('/api/v1/fleet/telemetry');
    expect(buildGcsUrl(GCS_ROUTE_KEYS.fleetTelemetry)).toBe('http://gcs.test:5000/api/v1/fleet/telemetry');
    expect(buildLogsUrl('/sources')).toBe('http://gcs.test:5000/api/logs/sources');
    expect(buildSarUrl('/mission/plan')).toBe('http://gcs.test:5000/api/sar/mission/plan');
  });

  it('maps legacy and canonical paths back to the same route key', () => {
    expect(resolveGcsRouteKey('/telemetry')).toBe(GCS_ROUTE_KEYS.fleetTelemetry);
    expect(resolveGcsRouteKey('/api/v1/fleet/telemetry')).toBe(GCS_ROUTE_KEYS.fleetTelemetry);
    expect(resolveGcsRouteKey('/get-heartbeats')).toBe(GCS_ROUTE_KEYS.fleetHeartbeats);
    expect(resolveGcsRouteKey(GCS_ROUTE_KEYS.gitStatus)).toBe(GCS_ROUTE_KEYS.gitStatus);
  });

  it('unwraps typed telemetry envelopes without changing plain telemetry payloads', () => {
    const envelope = { telemetry: { 1: { position_lat: 1 } }, total_drones: 1 };
    expect(unwrapFleetTelemetryPayload(envelope)).toEqual({ 1: { position_lat: 1 } });
    expect(unwrapFleetTelemetryPayload({ 2: { position_lat: 2 } })).toEqual({ 2: { position_lat: 2 } });
  });

  it('fetches fleet telemetry from the canonical v1 endpoint', async () => {
    axios.get.mockResolvedValue({ data: {} });

    await getFleetTelemetryResponse({ timeout: 2000 });

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/fleet/telemetry',
      { timeout: 2000 }
    );
  });

  it('builds dynamic command status requests with URL-safe command ids', async () => {
    axios.get.mockResolvedValue({ data: {} });

    await getCommandStatusResponse('cmd/leader 1');

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/command/cmd%2Fleader%201',
      {}
    );
  });

  it('preserves query params for recent command lookups', async () => {
    axios.get.mockResolvedValue({ data: {} });

    await getRecentCommandsResponse({
      limit: 12,
      status: 'running',
      missionType: 4,
    });

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/commands/recent',
      {
        params: {
          limit: 12,
          status: 'running',
          mission_type: 4,
        },
      }
    );
  });

  it('preserves commit intent when saving swarm config', async () => {
    axios.post.mockResolvedValue({ data: { success: true } });

    await saveSwarmConfigResponse([{ hw_id: '1' }], { commit: true, timeout: 3000 });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/save-swarm-data',
      [{ hw_id: '1' }],
      {
        timeout: 3000,
        params: {
          commit: 'true',
        },
      }
    );
  });
});
