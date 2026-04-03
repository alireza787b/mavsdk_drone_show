// src/services/logService.js
// API service for all /api/logs/* endpoints

import axios from 'axios';
import {
  buildLogsUrl,
  getFleetConfigResponse,
  getFleetHeartbeatsResponse,
} from './gcsApiService';

/** GET /api/logs/sources — registered components */
export const getSources = async () => {
  const resp = await axios.get(buildLogsUrl('/sources'));
  return resp.data;
};

/** GET /api/v1/config/fleet — configured drone inventory */
export const getConfiguredDrones = async () => {
  const resp = await getFleetConfigResponse();
  return resp.data;
};

/** GET /api/v1/fleet/heartbeats — online/offline drone status */
export const getHeartbeats = async () => {
  const resp = await getFleetHeartbeatsResponse();
  return resp.data;
};

/** GET /api/logs/sessions — list GCS sessions */
export const getSessions = async () => {
  const resp = await axios.get(buildLogsUrl('/sessions'));
  return resp.data;
};

/** GET /api/logs/sessions/:id — retrieve session content with filters */
export const getSessionContent = async (sessionId, { level, component, limit, offset, since } = {}) => {
  const params = {};
  if (level) params.level = level;
  if (component) params.component = component;
  if (limit) params.limit = limit;
  if (offset) params.offset = offset;
  if (since) params.since = since;
  const resp = await axios.get(buildLogsUrl(`/sessions/${encodeURIComponent(sessionId)}`), { params });
  return resp.data;
};

/** GET /api/logs/drone/:id/sessions — list sessions on a drone */
export const getDroneSessions = async (droneId) => {
  const resp = await axios.get(buildLogsUrl(`/drone/${encodeURIComponent(droneId)}/sessions`));
  return resp.data;
};

/** GET /api/logs/drone/:id/sessions/:sid — retrieve drone session content */
export const getDroneSessionContent = async (droneId, sessionId, { level, component, limit, offset, since } = {}) => {
  const params = {};
  if (level) params.level = level;
  if (component) params.component = component;
  if (limit) params.limit = limit;
  if (offset) params.offset = offset;
  if (since) params.since = since;
  const resp = await axios.get(
    buildLogsUrl(`/drone/${encodeURIComponent(droneId)}/sessions/${encodeURIComponent(sessionId)}`),
    { params },
  );
  return resp.data;
};

/** POST /api/logs/export — export sessions as JSONL or ZIP */
export const exportSessions = async (sessionIds, format = 'jsonl', droneId = null) => {
  const endpoint = droneId != null
    ? buildLogsUrl(`/drone/${encodeURIComponent(droneId)}/export`)
    : buildLogsUrl('/export');
  const resp = await axios.post(
    endpoint,
    { session_ids: sessionIds, format },
    { responseType: 'blob' },
  );
  return resp;
};

/** POST /api/logs/frontend — report frontend error */
export const reportFrontendError = async (level, msg, extra = null) => {
  const resp = await axios.post(buildLogsUrl('/frontend'), {
    level,
    component: 'frontend',
    msg,
    extra,
  });
  return resp.data;
};

/** POST /api/logs/config — toggle background pull */
export const updateLogConfig = async (config) => {
  const resp = await axios.post(buildLogsUrl('/config'), config);
  return resp.data;
};

/**
 * Build SSE URL for EventSource connection.
 * @param {object} filters - { level, component, source, drone_id }
 * @param {number|null} droneId - if set, connects to drone proxy stream
 * @returns {string} Full SSE URL
 */
export const buildStreamURL = (filters = {}, droneId = null) => {
  const base = droneId
    ? buildLogsUrl(`/drone/${encodeURIComponent(droneId)}/stream`)
    : buildLogsUrl('/stream');
  const params = new URLSearchParams();
  if (filters.level) params.set('level', filters.level);
  if (filters.component) params.set('component', filters.component);
  if (filters.source) params.set('source', filters.source);
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
};
