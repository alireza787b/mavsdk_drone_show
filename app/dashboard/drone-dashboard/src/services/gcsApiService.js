import axios from 'axios';
import { getBackendURL } from '../config/apiConfig';

const ABSOLUTE_URL_PATTERN = /^[a-z][a-z\d+\-.]*:\/\//i;
const ABSOLUTE_WS_URL_PATTERN = /^wss?:\/\//i;
export const COMMAND_SUBMIT_TIMEOUT_MS = 12000;

export const GCS_ROUTE_KEYS = Object.freeze({
  systemHealth: 'systemHealth',
  fleetTelemetry: 'fleetTelemetry',
  fleetHeartbeats: 'fleetHeartbeats',
  fleetCandidates: 'fleetCandidates',
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
  precisionMovePolicy: 'precisionMovePolicy',
  px4ParamsBase: 'px4ParamsBase',
  px4ParamsPolicy: 'px4ParamsPolicy',
  px4ParamsProfiles: 'px4ParamsProfiles',
  px4ParamsSnapshots: 'px4ParamsSnapshots',
  px4ParamsPatchJobs: 'px4ParamsPatchJobs',
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
  sitlControlPolicy: 'sitlControlPolicy',
  sitlControlHost: 'sitlControlHost',
  sitlControlImages: 'sitlControlImages',
  sitlControlImageRelease: 'sitlControlImageRelease',
  sitlControlInstances: 'sitlControlInstances',
  sitlControlInstanceActions: 'sitlControlInstanceActions',
  sitlControlReconcile: 'sitlControlReconcile',
  sitlControlOperations: 'sitlControlOperations',
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
  [GCS_ROUTE_KEYS.fleetCandidates]: '/api/v1/fleet/candidates',
  [GCS_ROUTE_KEYS.fleetNetworkStatus]: '/api/v1/fleet/network-status',
  [GCS_ROUTE_KEYS.fleetConfig]: '/api/v1/config/fleet',
  [GCS_ROUTE_KEYS.saveFleetConfig]: '/api/v1/config/fleet',
  [GCS_ROUTE_KEYS.validateFleetConfig]: '/api/v1/config/fleet/validation',
  [GCS_ROUTE_KEYS.dronePositions]: '/api/v1/config/fleet/trajectory-start-positions',
  [GCS_ROUTE_KEYS.trajectoryFirstRow]: '/api/v1/config/fleet/trajectory-start-positions',
  [GCS_ROUTE_KEYS.swarmConfig]: '/api/v1/config/swarm',
  [GCS_ROUTE_KEYS.saveSwarmConfig]: '/api/v1/config/swarm',
  [GCS_ROUTE_KEYS.commandSubmit]: '/api/v1/commands',
  [GCS_ROUTE_KEYS.commandStatus]: '/api/v1/commands',
  [GCS_ROUTE_KEYS.recentCommands]: '/api/v1/commands/recent',
  [GCS_ROUTE_KEYS.activeCommands]: '/api/v1/commands/active',
  [GCS_ROUTE_KEYS.commandStatistics]: '/api/v1/commands/statistics',
  [GCS_ROUTE_KEYS.precisionMovePolicy]: '/api/v1/commands/policy/precision-move',
  [GCS_ROUTE_KEYS.px4ParamsBase]: '/api/v1/px4-params',
  [GCS_ROUTE_KEYS.px4ParamsPolicy]: '/api/v1/px4-params/policy',
  [GCS_ROUTE_KEYS.px4ParamsProfiles]: '/api/v1/px4-params/profiles',
  [GCS_ROUTE_KEYS.px4ParamsSnapshots]: '/api/v1/px4-params/snapshots',
  [GCS_ROUTE_KEYS.px4ParamsPatchJobs]: '/api/v1/px4-params/patch-jobs',
  [GCS_ROUTE_KEYS.gitStatus]: '/api/v1/git/status',
  [GCS_ROUTE_KEYS.syncRepos]: '/api/v1/git/sync-operations',
  [GCS_ROUTE_KEYS.origin]: '/api/v1/origin',
  [GCS_ROUTE_KEYS.setOrigin]: '/api/v1/origin',
  [GCS_ROUTE_KEYS.globalOrigin]: '/api/v1/navigation/global-origin',
  [GCS_ROUTE_KEYS.elevation]: '/api/v1/origin/elevation',
  [GCS_ROUTE_KEYS.originForDrone]: '/api/v1/origin/bootstrap',
  [GCS_ROUTE_KEYS.positionDeviations]: '/api/v1/origin/deviations',
  [GCS_ROUTE_KEYS.computeOrigin]: '/api/v1/origin/compute',
  [GCS_ROUTE_KEYS.desiredLaunchPositions]: '/api/v1/origin/launch-positions',
  [GCS_ROUTE_KEYS.gcsConfig]: '/api/v1/system/gcs-config',
  [GCS_ROUTE_KEYS.saveGcsConfig]: '/api/v1/system/gcs-config',
  [GCS_ROUTE_KEYS.sitlControlPolicy]: '/api/v1/system/sitl/policy',
  [GCS_ROUTE_KEYS.sitlControlHost]: '/api/v1/system/sitl/host',
  [GCS_ROUTE_KEYS.sitlControlImages]: '/api/v1/system/sitl/images',
  [GCS_ROUTE_KEYS.sitlControlImageRelease]: '/api/v1/system/sitl/images/release',
  [GCS_ROUTE_KEYS.sitlControlInstances]: '/api/v1/system/sitl/instances',
  [GCS_ROUTE_KEYS.sitlControlInstanceActions]: '/api/v1/system/sitl/instances/actions',
  [GCS_ROUTE_KEYS.sitlControlReconcile]: '/api/v1/system/sitl/reconcile',
  [GCS_ROUTE_KEYS.sitlControlOperations]: '/api/v1/system/sitl/operations',
  [GCS_ROUTE_KEYS.networkInfo]: '/api/v1/fleet/network-details',
  [GCS_ROUTE_KEYS.swarmLeaders]: '/api/v1/swarm-trajectories/leaders',
  [GCS_ROUTE_KEYS.showInfo]: '/api/v1/shows/skybrush',
  [GCS_ROUTE_KEYS.comprehensiveMetrics]: '/api/v1/shows/skybrush/metrics',
  [GCS_ROUTE_KEYS.customShowInfo]: '/api/v1/shows/custom',
  [GCS_ROUTE_KEYS.importShow]: '/api/v1/shows/skybrush/import',
  [GCS_ROUTE_KEYS.importCustomShow]: '/api/v1/shows/custom/import',
  [GCS_ROUTE_KEYS.showPlots]: '/api/v1/shows/skybrush/plots',
  [GCS_ROUTE_KEYS.rawShowDownload]: '/api/v1/shows/skybrush/archives/raw',
  [GCS_ROUTE_KEYS.processedShowDownload]: '/api/v1/shows/skybrush/archives/processed',
  [GCS_ROUTE_KEYS.customShowImage]: '/api/v1/shows/custom/preview',
  [GCS_ROUTE_KEYS.staticPlotsBase]: '/api/v1/swarm-trajectories/plots',
  [GCS_ROUTE_KEYS.swarmTrajectoryBase]: '/api/v1/swarm-trajectories',
  [GCS_ROUTE_KEYS.swarmTrajectoryStatus]: '/api/v1/swarm-trajectories/status',
  [GCS_ROUTE_KEYS.swarmTrajectoryPolicy]: '/api/v1/swarm-trajectories/policy',
  [GCS_ROUTE_KEYS.swarmTrajectoryProcess]: '/api/v1/swarm-trajectories/process',
  [GCS_ROUTE_KEYS.swarmTrajectoryClearProcessed]: '/api/v1/swarm-trajectories/clear-processed',
  [GCS_ROUTE_KEYS.logsBase]: '/api/logs',
  [GCS_ROUTE_KEYS.sarBase]: '/api/sar',
});

export const GCS_WS_ROUTES = Object.freeze({
  telemetry: '/ws/telemetry',
  heartbeats: '/ws/heartbeats',
  gitStatus: '/ws/git-status',
});

const ROUTE_KEY_BY_PATH = Object.freeze({
  '/ping': GCS_ROUTE_KEYS.systemHealth,
  '/health': GCS_ROUTE_KEYS.systemHealth,
  '/api/v1/system/health': GCS_ROUTE_KEYS.systemHealth,
  '/api/v1/fleet/telemetry': GCS_ROUTE_KEYS.fleetTelemetry,
  '/api/v1/fleet/heartbeats': GCS_ROUTE_KEYS.fleetHeartbeats,
  '/api/v1/fleet/candidates': GCS_ROUTE_KEYS.fleetCandidates,
  '/api/v1/fleet/network-status': GCS_ROUTE_KEYS.fleetNetworkStatus,
  '/api/v1/config/fleet': GCS_ROUTE_KEYS.fleetConfig,
  '/api/v1/config/fleet/validation': GCS_ROUTE_KEYS.validateFleetConfig,
  '/api/v1/config/fleet/trajectory-start-positions': GCS_ROUTE_KEYS.dronePositions,
  '/api/v1/config/swarm': GCS_ROUTE_KEYS.swarmConfig,
  '/api/v1/commands': GCS_ROUTE_KEYS.commandSubmit,
  '/api/v1/commands/policy/precision-move': GCS_ROUTE_KEYS.precisionMovePolicy,
  '/api/v1/px4-params': GCS_ROUTE_KEYS.px4ParamsBase,
  '/api/v1/px4-params/policy': GCS_ROUTE_KEYS.px4ParamsPolicy,
  '/api/v1/px4-params/profiles': GCS_ROUTE_KEYS.px4ParamsProfiles,
  '/api/v1/px4-params/snapshots': GCS_ROUTE_KEYS.px4ParamsSnapshots,
  '/api/v1/px4-params/patch-jobs': GCS_ROUTE_KEYS.px4ParamsPatchJobs,
  '/api/v1/commands/recent': GCS_ROUTE_KEYS.recentCommands,
  '/api/v1/commands/active': GCS_ROUTE_KEYS.activeCommands,
  '/api/v1/commands/statistics': GCS_ROUTE_KEYS.commandStatistics,
  '/api/v1/git/status': GCS_ROUTE_KEYS.gitStatus,
  '/api/v1/git/sync-operations': GCS_ROUTE_KEYS.syncRepos,
  '/api/v1/origin': GCS_ROUTE_KEYS.origin,
  '/api/v1/navigation/global-origin': GCS_ROUTE_KEYS.globalOrigin,
  '/api/v1/origin/elevation': GCS_ROUTE_KEYS.elevation,
  '/api/v1/origin/bootstrap': GCS_ROUTE_KEYS.originForDrone,
  '/api/v1/origin/deviations': GCS_ROUTE_KEYS.positionDeviations,
  '/api/v1/origin/compute': GCS_ROUTE_KEYS.computeOrigin,
  '/api/v1/origin/launch-positions': GCS_ROUTE_KEYS.desiredLaunchPositions,
  '/api/v1/system/gcs-config': GCS_ROUTE_KEYS.gcsConfig,
  '/api/v1/system/sitl/policy': GCS_ROUTE_KEYS.sitlControlPolicy,
  '/api/v1/system/sitl/host': GCS_ROUTE_KEYS.sitlControlHost,
  '/api/v1/system/sitl/images': GCS_ROUTE_KEYS.sitlControlImages,
  '/api/v1/system/sitl/images/release': GCS_ROUTE_KEYS.sitlControlImageRelease,
  '/api/v1/system/sitl/instances': GCS_ROUTE_KEYS.sitlControlInstances,
  '/api/v1/system/sitl/instances/actions': GCS_ROUTE_KEYS.sitlControlInstanceActions,
  '/api/v1/system/sitl/reconcile': GCS_ROUTE_KEYS.sitlControlReconcile,
  '/api/v1/system/sitl/operations': GCS_ROUTE_KEYS.sitlControlOperations,
  '/api/v1/fleet/network-details': GCS_ROUTE_KEYS.networkInfo,
  '/api/v1/swarm-trajectories/leaders': GCS_ROUTE_KEYS.swarmLeaders,
  '/api/v1/shows/skybrush': GCS_ROUTE_KEYS.showInfo,
  '/api/v1/shows/skybrush/metrics': GCS_ROUTE_KEYS.comprehensiveMetrics,
  '/api/v1/shows/custom': GCS_ROUTE_KEYS.customShowInfo,
  '/api/v1/shows/skybrush/import': GCS_ROUTE_KEYS.importShow,
  '/api/v1/shows/custom/import': GCS_ROUTE_KEYS.importCustomShow,
  '/api/v1/shows/skybrush/plots': GCS_ROUTE_KEYS.showPlots,
  '/api/v1/shows/skybrush/archives/raw': GCS_ROUTE_KEYS.rawShowDownload,
  '/api/v1/shows/skybrush/archives/processed': GCS_ROUTE_KEYS.processedShowDownload,
  '/api/v1/shows/custom/preview': GCS_ROUTE_KEYS.customShowImage,
  '/api/v1/swarm-trajectories/plots': GCS_ROUTE_KEYS.staticPlotsBase,
  '/api/v1/swarm-trajectories': GCS_ROUTE_KEYS.swarmTrajectoryBase,
  '/api/v1/swarm-trajectories/status': GCS_ROUTE_KEYS.swarmTrajectoryStatus,
  '/api/v1/swarm-trajectories/policy': GCS_ROUTE_KEYS.swarmTrajectoryPolicy,
  '/api/v1/swarm-trajectories/process': GCS_ROUTE_KEYS.swarmTrajectoryProcess,
  '/api/v1/swarm-trajectories/clear-processed': GCS_ROUTE_KEYS.swarmTrajectoryClearProcessed,
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

export function buildGcsWebSocketUrl(path) {
  if (typeof path === 'string' && ABSOLUTE_WS_URL_PATTERN.test(path)) {
    return path;
  }

  const base = new URL(getBackendURL());
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  base.pathname = path.startsWith('/') ? path : `/${path}`;
  base.search = '';
  base.hash = '';
  return base.toString();
}

export function buildTelemetryWebSocketUrl() {
  return buildGcsWebSocketUrl(GCS_WS_ROUTES.telemetry);
}

export function buildHeartbeatWebSocketUrl() {
  return buildGcsWebSocketUrl(GCS_WS_ROUTES.heartbeats);
}

export function buildGitStatusWebSocketUrl() {
  return buildGcsWebSocketUrl(GCS_WS_ROUTES.gitStatus);
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

export function unwrapSwarmConfigPayload(payload) {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (payload && typeof payload === 'object' && Array.isArray(payload.assignments)) {
    return payload.assignments;
  }
  return [];
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
  return putGcsResource(GCS_ROUTE_KEYS.saveFleetConfig, payload, config);
}

export async function validateFleetConfigResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.validateFleetConfig, payload, config);
}

export async function getSwarmConfigResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.swarmConfig, config);
}

export async function saveSwarmConfigResponse(payload, { commit = false, ...config } = {}) {
  return putGcsResource(GCS_ROUTE_KEYS.saveSwarmConfig, {
    version: 1,
    assignments: payload,
  }, {
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

export function normalizeCommandSubmitPayload(payload = {}) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return payload;
  }

  const normalized = { ...payload };

  if (!Object.prototype.hasOwnProperty.call(normalized, 'mission_type') && Object.prototype.hasOwnProperty.call(normalized, 'missionType')) {
    normalized.mission_type = normalized.missionType;
  }
  if (!Object.prototype.hasOwnProperty.call(normalized, 'trigger_time') && Object.prototype.hasOwnProperty.call(normalized, 'triggerTime')) {
    normalized.trigger_time = normalized.triggerTime;
  }
  if (!Object.prototype.hasOwnProperty.call(normalized, 'target_drone_ids') && Object.prototype.hasOwnProperty.call(normalized, 'target_drones')) {
    normalized.target_drone_ids = normalized.target_drones;
  }
  if (!Object.prototype.hasOwnProperty.call(normalized, 'operator_label') && Object.prototype.hasOwnProperty.call(normalized, 'operatorLabel')) {
    normalized.operator_label = normalized.operatorLabel;
  }

  delete normalized.missionType;
  delete normalized.triggerTime;
  delete normalized.target_drones;
  delete normalized.operatorLabel;

  return normalized;
}

export async function submitCommandResponse(payload, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.commandSubmit, normalizeCommandSubmitPayload(payload), config);
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

export async function getPrecisionMovePolicyResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.precisionMovePolicy, config);
}

export async function syncReposResponse(payload = {}, config = {}) {
  return postGcsResource(GCS_ROUTE_KEYS.syncRepos, payload, config);
}

export async function getOriginResponse(config = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.origin, config);
}

export async function setOriginResponse(payload, config = {}) {
  return putGcsResource(GCS_ROUTE_KEYS.setOrigin, payload, config);
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
  return putGcsResource(GCS_ROUTE_KEYS.saveGcsConfig, payload, config);
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
  return fetchGcsResource(
    `${GCS_ROUTES[GCS_ROUTE_KEYS.trajectoryFirstRow]}/${encodeURIComponent(posId)}`,
    config,
  );
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
