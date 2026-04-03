import axios from 'axios';
import {
  buildGcsUrl,
  buildLogsUrl,
  buildShowDownloadUrl,
  buildShowPlotUrl,
  buildStaticPlotUrl,
  buildSarUrl,
  GCS_ROUTE_KEYS,
  getGcsConfigResponse,
  getNetworkInfoResponse,
  getCommandStatusResponse,
  getTrajectoryFirstRowResponse,
  getFleetTelemetryResponse,
  getRecentCommandsResponse,
  importCustomShowResponse,
  importShowResponse,
  saveGcsConfigResponse,
  saveFleetConfigResponse,
  setOriginResponse,
  syncReposResponse,
  resolveGcsRoute,
  resolveGcsRouteKey,
  saveSwarmConfigResponse,
  unwrapFleetTelemetryPayload,
  unwrapSwarmConfigPayload,
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

  it('preserves absolute URLs instead of prefixing them twice', () => {
    expect(buildGcsUrl('https://example.test/api/v1/health')).toBe('https://example.test/api/v1/health');
  });

  it('maps legacy and canonical paths back to the same route key', () => {
    expect(resolveGcsRouteKey('/telemetry')).toBe(GCS_ROUTE_KEYS.fleetTelemetry);
    expect(resolveGcsRouteKey('/api/v1/fleet/telemetry')).toBe(GCS_ROUTE_KEYS.fleetTelemetry);
    expect(resolveGcsRouteKey('/get-heartbeats')).toBe(GCS_ROUTE_KEYS.fleetHeartbeats);
    expect(resolveGcsRouteKey('/api/v1/config/fleet')).toBe(GCS_ROUTE_KEYS.fleetConfig);
    expect(resolveGcsRouteKey('/api/v1/config/swarm')).toBe(GCS_ROUTE_KEYS.swarmConfig);
    expect(resolveGcsRouteKey('/api/v1/git/status')).toBe(GCS_ROUTE_KEYS.gitStatus);
    expect(resolveGcsRouteKey('/api/v1/origin')).toBe(GCS_ROUTE_KEYS.origin);
    expect(resolveGcsRouteKey('/api/v1/origin/bootstrap')).toBe(GCS_ROUTE_KEYS.originForDrone);
    expect(resolveGcsRouteKey('/api/v1/origin/deviations')).toBe(GCS_ROUTE_KEYS.positionDeviations);
    expect(resolveGcsRouteKey('/submit_command')).toBe(GCS_ROUTE_KEYS.commandSubmit);
    expect(resolveGcsRouteKey('/api/v1/commands/recent')).toBe(GCS_ROUTE_KEYS.recentCommands);
    expect(resolveGcsRouteKey(GCS_ROUTE_KEYS.gitStatus)).toBe(GCS_ROUTE_KEYS.gitStatus);
  });

  it('resolves keyed routes that include query strings', () => {
    expect(resolveGcsRoute(`${GCS_ROUTE_KEYS.customShowInfo}?refresh=7`)).toBe('/api/v1/shows/custom?refresh=7');
  });

  it('builds encoded plot and download URLs from shared route helpers', () => {
    expect(buildShowPlotUrl('Drone 1.jpg')).toBe('http://gcs.test:5000/api/v1/shows/skybrush/plots/Drone%201.jpg');
    expect(buildShowDownloadUrl('processed')).toBe('http://gcs.test:5000/api/v1/shows/skybrush/archives/processed');
    expect(buildStaticPlotUrl('cluster leader 1.jpg')).toBe('http://gcs.test:5000/api/v1/swarm-trajectories/plots/cluster%20leader%201.jpg');
  });

  it('unwraps typed telemetry envelopes without changing plain telemetry payloads', () => {
    const envelope = { telemetry: { 1: { position_lat: 1 } }, total_drones: 1 };
    expect(unwrapFleetTelemetryPayload(envelope)).toEqual({ 1: { position_lat: 1 } });
    expect(unwrapFleetTelemetryPayload({ 2: { position_lat: 2 } })).toEqual({ 2: { position_lat: 2 } });
  });

  it('unwraps swarm config envelopes while preserving legacy list payloads', () => {
    expect(unwrapSwarmConfigPayload({ version: 1, assignments: [{ hw_id: 1 }] })).toEqual([{ hw_id: 1 }]);
    expect(unwrapSwarmConfigPayload([{ hw_id: 2 }])).toEqual([{ hw_id: 2 }]);
    expect(unwrapSwarmConfigPayload({ invalid: true })).toEqual([]);
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
      'http://gcs.test:5000/api/v1/commands/cmd%2Fleader%201',
      {}
    );
  });

  it('dispatches git sync through the canonical git sync operation route', async () => {
    axios.post.mockResolvedValue({ data: { success: true } });

    await syncReposResponse({ pos_ids: [1, 2] }, { timeout: 3000 });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/git/sync-operations',
      { pos_ids: [1, 2] },
      { timeout: 3000 }
    );
  });

  it('uploads SkyBrush archives through the canonical show import route', async () => {
    const formData = { append: jest.fn() };
    axios.post.mockResolvedValue({ data: { success: true } });

    await importShowResponse(formData, { timeout: 4000 });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/shows/skybrush/import',
      formData,
      { timeout: 4000 }
    );
  });

  it('uploads custom show CSV files through the canonical custom-show import route', async () => {
    const formData = { append: jest.fn() };
    axios.post.mockResolvedValue({ data: { success: true } });

    await importCustomShowResponse(formData, { timeout: 4000 });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/shows/custom/import',
      formData,
      { timeout: 4000 }
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
      'http://gcs.test:5000/api/v1/commands/recent',
      {
        params: {
          limit: 12,
          status: 'running',
          mission_type: 4,
        },
      }
    );
  });

  it('saves fleet config through the canonical config resource with PUT', async () => {
    axios.put.mockResolvedValue({ data: { success: true } });

    await saveFleetConfigResponse([{ hw_id: '1' }], { timeout: 2500 });

    expect(axios.put).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/config/fleet',
      [{ hw_id: '1' }],
      { timeout: 2500 }
    );
  });

  it('builds per-position trajectory-start requests with the canonical path parameter form', async () => {
    axios.get.mockResolvedValue({ data: {} });

    await getTrajectoryFirstRowResponse('7');

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/config/fleet/trajectory-start-positions/7',
      {}
    );
  });

  it('saves origin through the canonical origin resource with PUT', async () => {
    axios.put.mockResolvedValue({ data: { success: true } });

    await setOriginResponse({ lat: 35, lon: -120, alt: 12, alt_source: 'manual' }, { timeout: 2500 });

    expect(axios.put).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/origin',
      { lat: 35, lon: -120, alt: 12, alt_source: 'manual' },
      { timeout: 2500 }
    );
  });

  it('fetches GCS config from the canonical system resource', async () => {
    axios.get.mockResolvedValue({ data: {} });

    await getGcsConfigResponse({ timeout: 1200 });

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/gcs-config',
      { timeout: 1200 }
    );
  });

  it('saves GCS config through the canonical system resource with PUT', async () => {
    axios.put.mockResolvedValue({ data: { success: true } });

    await saveGcsConfigResponse({ sim_mode: true }, { timeout: 2100 });

    expect(axios.put).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/gcs-config',
      { sim_mode: true },
      { timeout: 2100 }
    );
  });

  it('fetches detailed fleet network metadata from the canonical network-details route', async () => {
    axios.get.mockResolvedValue({ data: [] });

    await getNetworkInfoResponse({ timeout: 1800 });

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/fleet/network-details',
      { timeout: 1800 }
    );
  });

  it('preserves commit intent when saving swarm config', async () => {
    axios.put.mockResolvedValue({ data: { success: true } });

    await saveSwarmConfigResponse([{ hw_id: '1' }], { commit: true, timeout: 3000 });

    expect(axios.put).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/config/swarm',
      {
        version: 1,
        assignments: [{ hw_id: '1' }],
      },
      {
        timeout: 3000,
        params: {
          commit: 'true',
        },
      }
    );
  });
});
