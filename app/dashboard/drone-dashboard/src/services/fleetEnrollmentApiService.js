import axios from 'axios';
import { buildGcsUrl, GCS_ROUTE_KEYS, GCS_ROUTES } from './gcsApiService';

export function buildFleetCandidateUrl(candidateId = '', suffix = '') {
  const baseRoute = GCS_ROUTES[GCS_ROUTE_KEYS.fleetCandidates];
  if (!candidateId) {
    return buildGcsUrl(`${baseRoute}${suffix}`);
  }
  return buildGcsUrl(
    `${baseRoute}/${encodeURIComponent(candidateId)}${suffix}`
  );
}

export async function listFleetCandidates({ includeInactive = false } = {}) {
  return axios.get(buildGcsUrl(GCS_ROUTE_KEYS.fleetCandidates), {
    params: includeInactive ? { include_inactive: 'true' } : {},
  });
}

export async function getFleetCandidate(candidateId) {
  return axios.get(buildFleetCandidateUrl(candidateId));
}

export async function announceFleetCandidate(payload) {
  return axios.post(buildFleetCandidateUrl('', '/announce'), payload);
}

export async function acceptFleetCandidate(candidateId, payload, { commit = true } = {}) {
  return axios.post(buildFleetCandidateUrl(candidateId, '/accept'), payload, {
    params: { commit: commit ? 'true' : 'false' },
  });
}

export async function replaceFleetCandidate(candidateId, payload, { commit = true } = {}) {
  return axios.post(buildFleetCandidateUrl(candidateId, '/replace'), payload, {
    params: { commit: commit ? 'true' : 'false' },
  });
}

export async function recoverFleetCandidate(candidateId, payload, { commit = true } = {}) {
  return axios.post(buildFleetCandidateUrl(candidateId, '/recover'), payload, {
    params: { commit: commit ? 'true' : 'false' },
  });
}

export async function rejectFleetCandidate(candidateId, payload = {}) {
  return axios.post(buildFleetCandidateUrl(candidateId, '/reject'), payload);
}

export async function ignoreFleetCandidate(candidateId, payload = {}) {
  return axios.post(buildFleetCandidateUrl(candidateId, '/ignore'), payload);
}
