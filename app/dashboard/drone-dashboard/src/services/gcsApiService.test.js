import axios from 'axios';
import {
  buildGitStatusWebSocketUrl,
  buildGcsUrl,
  buildGcsWebSocketUrl,
  buildHeartbeatWebSocketUrl,
  buildLogsUrl,
  normalizeCommandSubmitPayload,
  buildShowDownloadUrl,
  buildShowPlotUrl,
  buildStaticPlotUrl,
  buildSarUrl,
  buildTelemetryWebSocketUrl,
  GCS_ROUTE_KEYS,
  GCS_WS_ROUTES,
  applyGcsConfigResponse,
  getGcsConfigResponse,
  getNetworkInfoResponse,
  getCommandStatusResponse,
  getPrecisionMovePolicyResponse,
  getTrajectoryFirstRowResponse,
  getFleetTelemetryResponse,
  getRecentCommandsResponse,
  getRuntimeStatusResponse,
  importCustomShowResponse,
  importShowResponse,
  saveGcsConfigResponse,
  saveFleetConfigResponse,
  submitCommandResponse,
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

  it('builds canonical websocket URLs from the backend base URL', () => {
    expect(buildGcsWebSocketUrl(GCS_WS_ROUTES.telemetry)).toBe('ws://gcs.test:5000/ws/telemetry');
    expect(buildTelemetryWebSocketUrl()).toBe('ws://gcs.test:5000/ws/telemetry');
    expect(buildHeartbeatWebSocketUrl()).toBe('ws://gcs.test:5000/ws/heartbeats');
    expect(buildGitStatusWebSocketUrl()).toBe('ws://gcs.test:5000/ws/git-status');
  });

  it('upgrades websocket URLs to wss when the backend base uses https', () => {
    mockGetBackendURL.mockReturnValue('https://gcs.example.test');

    expect(buildGcsWebSocketUrl(GCS_WS_ROUTES.gitStatus)).toBe('wss://gcs.example.test/ws/git-status');
  });

  it('preserves absolute websocket URLs instead of rebuilding them', () => {
    expect(buildGcsWebSocketUrl('wss://stream.example.test/ws/telemetry')).toBe('wss://stream.example.test/ws/telemetry');
  });

  it('maps active canonical and retained compatibility paths back to route keys', () => {
    expect(resolveGcsRouteKey('/api/v1/fleet/telemetry')).toBe(GCS_ROUTE_KEYS.fleetTelemetry);
    expect(resolveGcsRouteKey('/api/v1/fleet/heartbeats')).toBe(GCS_ROUTE_KEYS.fleetHeartbeats);
    expect(resolveGcsRouteKey('/api/v1/fleet/candidates')).toBe(GCS_ROUTE_KEYS.fleetCandidates);
    expect(resolveGcsRouteKey('/api/v1/config/fleet')).toBe(GCS_ROUTE_KEYS.fleetConfig);
    expect(resolveGcsRouteKey('/api/v1/config/swarm')).toBe(GCS_ROUTE_KEYS.swarmConfig);
    expect(resolveGcsRouteKey('/api/v1/git/status')).toBe(GCS_ROUTE_KEYS.gitStatus);
    expect(resolveGcsRouteKey('/api/v1/origin')).toBe(GCS_ROUTE_KEYS.origin);
    expect(resolveGcsRouteKey('/api/v1/navigation/global-origin')).toBe(GCS_ROUTE_KEYS.globalOrigin);
    expect(resolveGcsRouteKey('/api/v1/origin/bootstrap')).toBe(GCS_ROUTE_KEYS.originForDrone);
    expect(resolveGcsRouteKey('/api/v1/origin/deviations')).toBe(GCS_ROUTE_KEYS.positionDeviations);
    expect(resolveGcsRouteKey('/api/v1/origin/compute')).toBe(GCS_ROUTE_KEYS.computeOrigin);
    expect(resolveGcsRouteKey('/api/v1/origin/launch-positions')).toBe(GCS_ROUTE_KEYS.desiredLaunchPositions);
    expect(resolveGcsRouteKey('/api/v1/commands')).toBe(GCS_ROUTE_KEYS.commandSubmit);
    expect(resolveGcsRouteKey('/api/v1/commands/policy/precision-move')).toBe(GCS_ROUTE_KEYS.precisionMovePolicy);
    expect(resolveGcsRouteKey('/api/v1/commands/recent')).toBe(GCS_ROUTE_KEYS.recentCommands);
    expect(resolveGcsRouteKey('/api/v1/system/runtime-status')).toBe(GCS_ROUTE_KEYS.systemRuntimeStatus);
    expect(resolveGcsRouteKey('/api/v1/swarm-trajectories/leaders')).toBe(GCS_ROUTE_KEYS.swarmLeaders);
    expect(resolveGcsRouteKey('/api/v1/swarm-trajectories')).toBe(GCS_ROUTE_KEYS.swarmTrajectoryBase);
    expect(resolveGcsRouteKey('/api/v1/swarm-trajectories/status')).toBe(GCS_ROUTE_KEYS.swarmTrajectoryStatus);
    expect(resolveGcsRouteKey('/api/v1/swarm-trajectories/policy')).toBe(GCS_ROUTE_KEYS.swarmTrajectoryPolicy);
    expect(resolveGcsRouteKey('/api/v1/swarm-trajectories/process')).toBe(GCS_ROUTE_KEYS.swarmTrajectoryProcess);
    expect(resolveGcsRouteKey('/api/v1/swarm-trajectories/clear-processed')).toBe(GCS_ROUTE_KEYS.swarmTrajectoryClearProcessed);
    expect(resolveGcsRouteKey(GCS_ROUTE_KEYS.gitStatus)).toBe(GCS_ROUTE_KEYS.gitStatus);
  });

  it('does not keep retired management/static/config/swarm/show/command/origin legacy paths alive in the shared route resolver', () => {
    expect(resolveGcsRouteKey('/telemetry')).toBeNull();
    expect(resolveGcsRouteKey('/api/telemetry')).toBeNull();
    expect(resolveGcsRouteKey('/heartbeat')).toBeNull();
    expect(resolveGcsRouteKey('/drone-heartbeat')).toBeNull();
    expect(resolveGcsRouteKey('/get-heartbeats')).toBeNull();
    expect(resolveGcsRouteKey('/get-network-status')).toBeNull();
    expect(resolveGcsRouteKey('/git-status')).toBeNull();
    expect(resolveGcsRouteKey('/sync-repos')).toBeNull();
    expect(resolveGcsRouteKey('/get-gcs-config')).toBeNull();
    expect(resolveGcsRouteKey('/save-gcs-config')).toBeNull();
    expect(resolveGcsRouteKey('/get-network-info')).toBeNull();
    expect(resolveGcsRouteKey('/static/plots')).toBeNull();
    expect(resolveGcsRouteKey('/get-config-data')).toBeNull();
    expect(resolveGcsRouteKey('/save-config-data')).toBeNull();
    expect(resolveGcsRouteKey('/validate-config')).toBeNull();
    expect(resolveGcsRouteKey('/get-drone-positions')).toBeNull();
    expect(resolveGcsRouteKey('/get-trajectory-first-row')).toBeNull();
    expect(resolveGcsRouteKey('/get-swarm-data')).toBeNull();
    expect(resolveGcsRouteKey('/save-swarm-data')).toBeNull();
    expect(resolveGcsRouteKey('/request-new-leader')).toBeNull();
    expect(resolveGcsRouteKey('/import-show')).toBeNull();
    expect(resolveGcsRouteKey('/download-raw-show')).toBeNull();
    expect(resolveGcsRouteKey('/download-processed-show')).toBeNull();
    expect(resolveGcsRouteKey('/get-show-info')).toBeNull();
    expect(resolveGcsRouteKey('/get-custom-show-info')).toBeNull();
    expect(resolveGcsRouteKey('/import-custom-show')).toBeNull();
    expect(resolveGcsRouteKey('/get-comprehensive-metrics')).toBeNull();
    expect(resolveGcsRouteKey('/get-safety-report')).toBeNull();
    expect(resolveGcsRouteKey('/validate-trajectory')).toBeNull();
    expect(resolveGcsRouteKey('/deploy-show')).toBeNull();
    expect(resolveGcsRouteKey('/get-show-plots')).toBeNull();
    expect(resolveGcsRouteKey('/get-custom-show-image')).toBeNull();
    expect(resolveGcsRouteKey('/submit_command')).toBeNull();
    expect(resolveGcsRouteKey('/command')).toBeNull();
    expect(resolveGcsRouteKey('/commands/recent')).toBeNull();
    expect(resolveGcsRouteKey('/commands/active')).toBeNull();
    expect(resolveGcsRouteKey('/commands/statistics')).toBeNull();
    expect(resolveGcsRouteKey('/get-origin')).toBeNull();
    expect(resolveGcsRouteKey('/set-origin')).toBeNull();
    expect(resolveGcsRouteKey('/get-gps-global-origin')).toBeNull();
    expect(resolveGcsRouteKey('/elevation')).toBeNull();
    expect(resolveGcsRouteKey('/get-origin-for-drone')).toBeNull();
    expect(resolveGcsRouteKey('/get-position-deviations')).toBeNull();
    expect(resolveGcsRouteKey('/compute-origin')).toBeNull();
    expect(resolveGcsRouteKey('/get-desired-launch-positions')).toBeNull();
    expect(resolveGcsRouteKey('/api/swarm/leaders')).toBeNull();
    expect(resolveGcsRouteKey('/api/swarm/trajectory')).toBeNull();
    expect(resolveGcsRouteKey('/api/swarm/trajectory/status')).toBeNull();
    expect(resolveGcsRouteKey('/api/swarm/trajectory/policy')).toBeNull();
    expect(resolveGcsRouteKey('/api/swarm/trajectory/process')).toBeNull();
    expect(resolveGcsRouteKey('/api/swarm/trajectory/clear-processed')).toBeNull();
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

  it('fetches precision move policy from the canonical command policy route', async () => {
    axios.get.mockResolvedValue({ data: { action: 'precision_move' } });

    await getPrecisionMovePolicyResponse();

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/commands/policy/precision-move',
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

  it('normalizes command submit payloads onto the canonical snake_case request contract', async () => {
    axios.post.mockResolvedValue({ data: { success: true } });

    const payload = normalizeCommandSubmitPayload({
      missionType: '10',
      triggerTime: '0',
      target_drones: ['1', '2'],
      operatorLabel: 'launch-now',
      takeoff_altitude: 15,
    });

    expect(payload).toEqual({
      mission_type: '10',
      trigger_time: '0',
      target_drone_ids: ['1', '2'],
      operator_label: 'launch-now',
      takeoff_altitude: 15,
    });

    await submitCommandResponse({
      missionType: '10',
      triggerTime: '0',
      target_drones: ['1', '2'],
      operatorLabel: 'launch-now',
      takeoff_altitude: 15,
    });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/commands',
      {
        mission_type: '10',
        trigger_time: '0',
        target_drone_ids: ['1', '2'],
        operator_label: 'launch-now',
        takeoff_altitude: 15,
      },
      {}
    );
  });

  it('preserves nested precision_move payloads while normalizing the command envelope', async () => {
    axios.post.mockResolvedValue({ data: { success: true } });

    await submitCommandResponse({
      missionType: '112',
      triggerTime: '0',
      operatorLabel: 'Precision Move',
      target_drones: ['1'],
      precision_move: {
        frame: 'body',
        translation_m: {
          forward: 1,
          right: 0,
          up: 0.5,
        },
        yaw: {
          mode: 'hold_current',
        },
      },
    });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/commands',
      {
        mission_type: '112',
        trigger_time: '0',
        operator_label: 'Precision Move',
        target_drone_ids: ['1'],
        precision_move: {
          frame: 'body',
          translation_m: {
            forward: 1,
            right: 0,
            up: 0.5,
          },
          yaw: {
            mode: 'hold_current',
          },
        },
      },
      {}
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

  it('persists GCS config through the canonical system resource with PUT', async () => {
    axios.put.mockResolvedValue({ data: { success: true } });

    await saveGcsConfigResponse({ mode: 'real', git_auto_push: false }, { timeout: 1100 });

    expect(axios.put).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/gcs-config',
      { mode: 'real', git_auto_push: false },
      { timeout: 1100 }
    );
  });

  it('applies persisted GCS config through the canonical apply route', async () => {
    axios.post.mockResolvedValue({ data: { success: true } });

    await applyGcsConfigResponse({ timeout: 900 });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/gcs-config/apply',
      {},
      { timeout: 900 }
    );
  });

  it('fetches runtime admin status from the canonical system runtime resource', async () => {
    axios.get.mockResolvedValue({ data: {} });

    await getRuntimeStatusResponse({ timeout: 900 });

    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/runtime-status',
      { timeout: 900 }
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
