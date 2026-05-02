import {
  buildGcsUrl,
  fetchGcsResource,
  GCS_ROUTE_KEYS,
  GCS_ROUTES,
  postGcsResource,
} from './gcsApiService';

export function buildFleetCandidateUrl(candidateId = '', suffix = '') {
  const baseRoute = GCS_ROUTES[GCS_ROUTE_KEYS.fleetCandidates];
  if (!candidateId) {
    return buildGcsUrl(`${baseRoute}${suffix}`);
  }
  return buildGcsUrl(
    `${baseRoute}/${encodeURIComponent(candidateId)}${suffix}`
  );
}

export async function listFleetCandidates({ includeInactive = false, runtimeMode = 'current' } = {}) {
  return fetchGcsResource(GCS_ROUTE_KEYS.fleetCandidates, {
    params: {
      ...(includeInactive ? { include_inactive: 'true' } : {}),
      runtime_mode: runtimeMode,
    },
  });
}

export async function getFleetCandidate(candidateId) {
  return fetchGcsResource(buildFleetCandidateUrl(candidateId));
}

export async function announceFleetCandidate(payload) {
  return postGcsResource(buildFleetCandidateUrl('', '/announce'), payload);
}

export async function acceptFleetCandidate(candidateId, payload, { commit = true } = {}) {
  return postGcsResource(buildFleetCandidateUrl(candidateId, '/accept'), payload, {
    params: { commit: commit ? 'true' : 'false' },
  });
}

export async function replaceFleetCandidate(candidateId, payload, { commit = true } = {}) {
  return postGcsResource(buildFleetCandidateUrl(candidateId, '/replace'), payload, {
    params: { commit: commit ? 'true' : 'false' },
  });
}

export async function recoverFleetCandidate(candidateId, payload, { commit = true } = {}) {
  return postGcsResource(buildFleetCandidateUrl(candidateId, '/recover'), payload, {
    params: { commit: commit ? 'true' : 'false' },
  });
}

export async function rejectFleetCandidate(candidateId, payload = {}) {
  return postGcsResource(buildFleetCandidateUrl(candidateId, '/reject'), payload);
}

export async function ignoreFleetCandidate(candidateId, payload = {}) {
  return postGcsResource(buildFleetCandidateUrl(candidateId, '/ignore'), payload);
}
