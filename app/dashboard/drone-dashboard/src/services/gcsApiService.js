import axios from 'axios';
import { getBackendURL } from '../config/apiConfig';

const ABSOLUTE_URL_PATTERN = /^[a-z][a-z\d+\-.]*:\/\//i;

export const GCS_ROUTE_KEYS = Object.freeze({
  systemHealth: 'systemHealth',
  fleetTelemetry: 'fleetTelemetry',
  fleetHeartbeats: 'fleetHeartbeats',
  fleetNetworkStatus: 'fleetNetworkStatus',
  fleetConfig: 'fleetConfig',
  saveFleetConfig: 'saveFleetConfig',
  validateFleetConfig: 'validateFleetConfig',
  dronePositions: 'dronePositions',
  trajectoryFirstRow: 'trajectoryFirstRow',
  swarmConfig: 'swarmConfig',
  saveSwarmConfig: 'saveSwarmConfig',
  commandSubmit: 'commandSubmit',
  commandStatus: 'commandStatus',
  recentCommands: 'recentCommands',
  activeCommands: 'activeCommands',
  commandStatistics: 'commandStatistics',
  gitStatus: 'gitStatus',
  syncRepos: 'syncRepos',
  origin: 'origin',
  setOrigin: 'setOrigin',
  globalOrigin: 'globalOrigin',
  elevation: 'elevation',
  originForDrone: 'originForDrone',
  positionDeviations: 'positionDeviations',
  computeOrigin: 'computeOrigin',
  desiredLaunchPositions: 'desiredLaunchPositions',
  gcsConfig: 'gcsConfig',
  saveGcsConfig: 'saveGcsConfig',
  networkInfo: 'networkInfo',
  swarmLeaders: 'swarmLeaders',
  showInfo: 'showInfo',
  comprehensiveMetrics: 'comprehensiveMetrics',
  customShowInfo: 'customShowInfo',
  importShow: 'importShow',
  importCustomShow: 'importCustomShow',
  showPlots: 'showPlots',
  rawShowDownload: 'rawShowDownload',
  processedShowDownload: 'processedShowDownload',
  customShowImage: 'customShowImage',
  staticPlotsBase: 'staticPlotsBase',
  swarmTrajectoryBase: 'swarmTrajectoryBase',
  swarmTrajectoryStatus: 'swarmTrajectoryStatus',
  swarmTrajectoryPolicy: 'swarmTrajectoryPolicy',
  swarmTrajectoryProcess: 'swarmTrajectoryProcess',
  swarmTrajectoryClearProcessed: 'swarmTrajectoryClearProcessed',
  logsBase: 'logsBase',
  sarBase: 'sarBase',
});

export const GCS_ROUTES = Object.freeze({
  [GCS_ROUTE_KEYS.systemHealth]: '/api/v1/system/health',
  [GCS_ROUTE_KEYS.fleetTelemetry]: '/api/v1/fleet/telemetry',
  [GCS_ROUTE_KEYS.fleetHeartbeats]: '/api/v1/fleet/heartbeats',
  [GCS_ROUTE_KEYS.fleetNetworkStatus]: '/api/v1/fleet/network-status',
  [GCS_ROUTE_KEYS.fleetConfig]: '/get-config-data',
  [GCS_ROUTE_KEYS.saveFleetConfig]: '/save-config-data',
  [GCS_ROUTE_KEYS.validateFleetConfig]: '/validate-config',
  [GCS_ROUTE_KEYS.dronePositions]: '/get-drone-positions',
  [GCS_ROUTE_KEYS.trajectoryFirstRow]: '/get-trajectory-first-row',
  [GCS_ROUTE_KEYS.swarmConfig]: '/get-swarm-data',
  [GCS_ROUTE_KEYS.saveSwarmConfig]: '/save-swarm-data',
  [GCS_ROUTE_KEYS.commandSubmit]: '/api/v1/commands',
  [GCS_ROUTE_KEYS.commandStatus]: '/api/v1/commands',
  [GCS_ROUTE_KEYS.recentCommands]: '/api/v1/commands/recent',
  [GCS_ROUTE_KEYS.activeCommands]: '/api/v1/commands/active',
  [GCS_ROUTE_KEYS.commandStatistics]: '/api/v1/commands/statistics',
  [GCS_ROUTE_KEYS.gitStatus]: '/git-status',
  [GCS_ROUTE_KEYS.syncRepos]: '/sync-repos',
  [GCS_ROUTE_KEYS.origin]: '/get-origin',
  [GCS_ROUTE_KEYS.setOrigin]: '/set-origin',
  [GCS_ROUTE_KEYS.globalOrigin]: '/get-gps-global-origin',
  [GCS_ROUTE_KEYS.elevation]: '/elevation',
  [GCS_ROUTE_KEYS.originForDrone]: '/get-origin-for-drone',
  [GCS_ROUTE_KEYS.positionDeviations]: '/get-position-deviations',
  [GCS_ROUTE_KEYS.computeOrigin]: '/compute-origin',
  [GCS_ROUTE_KEYS.desiredLaunchPositions]: '/get-desired-launch-positions',
  [GCS_ROUTE_KEYS.gcsConfig]: '/get-gcs-config',
  [GCS_ROUTE_KEYS.saveGcsConfig]: '/save-gcs-config',
  [GCS_ROUTE_KEYS.networkInfo]: '/get-network-info',
  [GCS_ROUTE_KEYS.swarmLeaders]: '/api/swarm/leaders',
  [GCS_ROUTE_KEYS.showInfo]: '/get-show-info',
  [GCS_ROUTE_KEYS.comprehensiveMetrics]: '/get-comprehensive-metrics',
  [GCS_ROUTE_KEYS.customShowInfo]: '/get-custom-show-info',
  [GCS_ROUTE_KEYS.importShow]: '/import-show',
  [GCS_ROUTE_KEYS.importCustomShow]: '/import-custom-show',
  [GCS_ROUTE_KEYS.showPlots]: '/get-show-plots',
  [GCS_ROUTE_KEYS.rawShowDownload]: '/download-raw-show',
  [GCS_ROUTE_KEYS.processedShowDownload]: '/download-processed-show',
  [GCS_ROUTE_KEYS.customShowImage]: '/get-custom-show-image',
  [GCS_ROUTE_KEYS.staticPlotsBase]: '/static/plots',
  [GCS_ROUTE_KEYS.swarmTrajectoryBase]: '/api/swarm/trajectory',
  [GCS_ROUTE_KEYS.swarmTrajectoryStatus]: '/api/swarm/trajectory/status',
  [GCS_ROUTE_KEYS.swarmTrajectoryPolicy]: '/api/swarm/trajectory/policy',
  [GCS_ROUTE_KEYS.swarmTrajectoryProcess]: '/api/swarm/trajectory/process',
  [GCS_ROUTE_KEYS.swarmTrajectoryClearProcessed]: '/api/swarm/trajectory/clear-processed',
  [GCS_ROUTE_KEYS.logsBase]: '/api/logs',
  [GCS_ROUTE_KEYS.sarBase]: '/api/sar',
});

const ROUTE_KEY_BY_PATH = Object.freeze({
  '/ping': GCS_ROUTE_KEYS.systemHealth,
  '/health': GCS_ROUTE_KEYS.systemHealth,
  '/api/v1/system/health': GCS_ROUTE_KEYS.systemHealth,
  '/telemetry': GCS_ROUTE_KEYS.fleetTelemetry,
  '/api/telemetry': GCS_ROUTE_KEYS.fleetTelemetry,
  '/api/v1/fleet/telemetry': GCS_ROUTE_KEYS.fleetTelemetry,
  '/heartbeat': GCS_ROUTE_KEYS.fleetHeartbeats,
  '/drone-heartbeat': GCS_ROUTE_KEYS.fleetHeartbeats,
  '/get-heartbeats': GCS_ROUTE_KEYS.fleetHeartbeats,
  '/api/v1/fleet/heartbeats': GCS_ROUTE_KEYS.fleetHeartbeats,
  '/get-network-status': GCS_ROUTE_KEYS.fleetNetworkStatus,
  '/api/v1/fleet/network-status': GCS_ROUTE_KEYS.fleetNetworkStatus,
  '/get-config-data': GCS_ROUTE_KEYS.fleetConfig,
  '/save-config-data': GCS_ROUTE_KEYS.saveFleetConfig,
  '/validate-config': GCS_ROUTE_KEYS.validateFleetConfig,
  '/get-drone-positions': GCS_ROUTE_KEYS.dronePositions,
  '/get-trajectory-first-row': GCS_ROUTE_KEYS.trajectoryFirstRow,
  '/get-swarm-data': GCS_ROUTE_KEYS.swarmConfig,
  '/save-swarm-data': GCS_ROUTE_KEYS.saveSwarmConfig,
  '/submit_command': GCS_ROUTE_KEYS.commandSubmit,
  '/api/v1/commands': GCS_ROUTE_KEYS.commandSubmit,
  '/command': GCS_ROUTE_KEYS.commandStatus,
  '/commands/recent': GCS_ROUTE_KEYS.recentCommands,
  '/api/v1/commands/recent': GCS_ROUTE_KEYS.recentCommands,
  '/commands/active': GCS_ROUTE_KEYS.activeCommands,
  '/api/v1/commands/active': GCS_ROUTE_KEYS.activeCommands,
  '/commands/statistics': GCS_ROUTE_KEYS.commandStatistics,
  '/api/v1/commands/statistics': GCS_ROUTE_KEYS.commandStatistics,
  '/git-status': GCS_ROUTE_KEYS.gitStatus,
  '/sync-repos': GCS_ROUTE_KEYS.syncRepos,
  '/get-origin': GCS_ROUTE_KEYS.origin,
  '/set-origin': GCS_ROUTE_KEYS.setOrigin,
  '/get-gps-global-origin': GCS_ROUTE_KEYS.globalOrigin,
  '/elevation': GCS_ROUTE_KEYS.elevation,
  '/get-origin-for-drone': GCS_ROUTE_KEYS.originForDrone,
  '/get-position-deviations': GCS_ROUTE_KEYS.positionDeviations,
  '/compute-origin': GCS_ROUTE_KEYS.computeOrigin,
  '/get-desired-launch-positions': GCS_ROUTE_KEYS.desiredLaunchPositions,
  '/get-gcs-config': GCS_ROUTE_KEYS.gcsConfig,
  '/save-gcs-config': GCS_ROUTE_KEYS.saveGcsConfig,
  '/get-network-info': GCS_ROUTE_KEYS.networkInfo,
  '/api/swarm/leaders': GCS_ROUTE_KEYS.swarmLeaders,
  '/get-show-info': GCS_ROUTE_KEYS.showInfo,
  '/get-comprehensive-metrics': GCS_ROUTE_KEYS.comprehensiveMetrics,
  '/get-custom-show-info': GCS_ROUTE_KEYS.customShowInfo,
  '/import-show': GCS_ROUTE_KEYS.importShow,
  '/import-custom-show': GCS_ROUTE_KEYS.importCustomShow,
  '/get-show-plots': GCS_ROUTE_KEYS.showPlots,
  '/download-raw-show': GCS_ROUTE_KEYS.rawShowDownload,
  '/download-processed-show': GCS_ROUTE_KEYS.processedShowDownload,
  '/get-custom-show-image': GCS_ROUTE_KEYS.customShowImage,
  '/static/plots': GCS_ROUTE_KEYS.staticPlotsBase,
  '/api/swarm/trajectory': GCS_ROUTE_KEYS.swarmTrajectoryBase,
  '/api/swarm/trajectory/status': GCS_ROUTE_KEYS.swarmTrajectoryStatus,
  '/api/swarm/trajectory/policy': GCS_ROUTE_KEYS.swarmTrajectoryPolicy,
  '/api/swarm/trajectory/process': GCS_ROUTE_KEYS.swarmTrajectoryProcess,
  '/api/swarm/trajectory/clear-processed': GCS_ROUTE_KEYS.swarmTrajectoryClearProcessed,
});

export function resolveGcsRoute(routeOrPath) {
  if (!routeOrPath) {
    return routeOrPath;
  }

  if (typeof routeOrPath === 'string') {
    if (GCS_ROUTES[routeOrPath]) {
      return GCS_ROUTES[routeOrPath];
    }

    const [base, query = null] = routeOrPath.split('?');
    if (GCS_ROUTES[base]) {
      return query !== null ? `${GCS_ROUTES[base]}?${query}` : GCS_ROUTES[base];
    }
  }

  return routeOrPath;
}

export function resolveGcsRouteKey(routeOrPath) {
  if (!routeOrPath || typeof routeOrPath !== 'string') {
    return null;
  }

  if (GCS_ROUTES[routeOrPath]) {
    return routeOrPath;
  }

  const [path] = routeOrPath.split('?');
  if (GCS_ROUTES[path]) {
    return path;
  }
  return ROUTE_KEY_BY_PATH[path] || null;
}

export function buildGcsUrl(routeOrPath) {
  const path = resolveGcsRoute(routeOrPath);
  if (typeof path === 'string' && ABSOLUTE_URL_PATTERN.test(path)) {
    return path;
  }
  return `${getBackendURL()}${path}`;
}

export function buildLogsUrl(suffix = '') {
  return buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.logsBase]}${suffix}`);
}

export function buildSarUrl(suffix = '') {
  return buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sarBase]}${suffix}`);
}

export function buildShowPlotUrl(filename = '') {
  if (!filename) {
    return buildGcsUrl(GCS_ROUTE_KEYS.showPlots);
  }

  return buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.showPlots]}/${encodeURIComponent(filename)}`);
}

export function buildShowDownloadUrl(type = 'raw') {
  return buildGcsUrl(
    type === 'processed'
      ? GCS_ROUTE_KEYS.processedShowDownload
      : GCS_ROUTE_KEYS.rawShowDownload
  );
}

export function buildStaticPlotUrl(filename) {
  return buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.staticPlotsBase]}/${encodeURIComponent(filename)}`);
}

export function buildSwarmTrajectoryUrl(suffix = '') {
  return buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.swarmTrajectoryBase]}${suffix}`);
}

export function unwrapFleetTelemetryPayload(payload) {
  if (payload && typeof payload === 'object' && payload.telemetry && typeof payload.telemetry === 'object') {
    return payload.telemetry;
  }
  return payload || {};
}

export async function fetchGcsResource(routeOrPath, config = {}) {
  return axios.get(buildGcsUrl(routeOrPath), config);
}

export async function fetchBlobGcsResource(routeOrPath, config = {}) {
  return axios.get(buildGcsUrl(routeOrPath), {
    ...config,
    responseType: config.responseType || 'blob',
  });
}

export async function postGcsResource(routeOrPath, payload = {}, config = {}) {
  return axios.post(buildGcsUrl(routeOrPath), payload, config);
}

export async function putGcsResource(routeOrPath, payload = {}, config = {}) {
  return axios.put(buildGcsUrl(routeOrPath), payload, config);
}

export async function patchGcsResource(routeOrPath, payload = {}, config = {}) {
  return axios.patch(buildGcsUrl(routeOrPath), payload, config);
}

export async function deleteGcsResource(routeOrPath, config = {}) {
  return axios.delete(buildGcsUrl(routeOrPath), config);
}

export async function getFleetTelemetryResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.fleetTelemetry, config);
}

export async function getFleetConfigResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.fleetConfig, config);
}

export async function getFleetHeartbeatsResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.fleetHeartbeats, config);
}

export async function saveFleetConfigResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.saveFleetConfig, payload, config);
}

export async function validateFleetConfigResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.validateFleetConfig, payload, config);
}

export async function getSwarmConfigResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.swarmConfig, config);
}

export async function saveSwarmConfigResponse(payload, { commit = false, ...config } = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.saveSwarmConfig, payload, {
    ...config,
    params: {
      ...(config.params || {}),
      commit: commit ? 'true' : 'false',
    },
  });
}

export async function getUnifiedGitStatusResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.gitStatus, config);
}

export async function submitCommandResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.commandSubmit, payload, config);
}

export async function getCommandStatusResponse(commandId, config = {}) {
  return fetchGcsResource(`${GCS_ROUTES[GCS_ROUTE_KEYS.commandStatus]}/${encodeURIComponent(commandId)}`, config);
}

export async function getRecentCommandsResponse(
  { limit = 8, status = null, missionType = null } = {},
  config = {}
) {
  return fetchGcsResource(GCS_ROUTE_KEYS.recentCommands, {
    ...config,
    params: {
      limit,
      ...(status ? { status } : {}),
      ...(missionType !== null && missionType !== undefined ? { mission_type: missionType } : {}),
      ...(config.params || {}),
    },
  });
}

export async function getActiveCommandsResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.activeCommands, config);
}

export async function syncReposResponse(payload = {}, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.syncRepos, payload, config);
}

export async function getOriginResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.origin, config);
}

export async function setOriginResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.setOrigin, payload, config);
}

export async function getPositionDeviationsResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.positionDeviations, config);
}

export async function getDronePositionsResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.dronePositions, config);
}

export async function getNetworkInfoResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.networkInfo, config);
}

export async function getGcsConfigResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.gcsConfig, config);
}

export async function saveGcsConfigResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.saveGcsConfig, payload, config);
}

export async function computeOriginResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.computeOrigin, payload, config);
}

export async function getSwarmLeadersResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.swarmLeaders, config);
}

export async function getShowInfoResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.showInfo, config);
}

export async function getShowPlotsResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.showPlots, config);
}

export async function getComprehensiveMetricsResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.comprehensiveMetrics, config);
}

export async function getCustomShowInfoResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.customShowInfo, config);
}

export async function importShowResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.importShow, payload, config);
}

export async function importCustomShowResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.importCustomShow, payload, config);
}

export async function getTrajectoryFirstRowResponse(posId, config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.trajectoryFirstRow, {
    ...config,
    params: {
      ...(config.params || {}),
      pos_id: posId,
    },
  });
}

export async function getSwarmTrajectoryStatusResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.swarmTrajectoryStatus, config);
}

export async function getSwarmTrajectoryPolicyResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.swarmTrajectoryPolicy, config);
}

export async function processSwarmTrajectoriesResponse(payload = {}, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.swarmTrajectoryProcess, payload, config);
}

export async function clearProcessedSwarmTrajectoriesResponse(config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.swarmTrajectoryClearProcessed, {}, config);
}
