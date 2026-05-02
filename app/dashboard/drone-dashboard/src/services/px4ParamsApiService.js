import {
  buildGcsUrl,
  fetchGcsResource,
  GCS_ROUTE_KEYS,
  GCS_ROUTES,
  postGcsResource,
} from './gcsApiService';

export function buildPx4ParamsUrl(suffix = '') {
  return buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.px4ParamsBase]}${suffix}`);
}

export async function getPx4ParamPolicy() {
  return fetchGcsResource(GCS_ROUTE_KEYS.px4ParamsPolicy);
}

export async function listPx4ParamProfiles() {
  return fetchGcsResource(GCS_ROUTE_KEYS.px4ParamsProfiles);
}

export async function getPx4ParamProfile(profileId) {
  return fetchGcsResource(buildPx4ParamsUrl(`/profiles/${encodeURIComponent(profileId)}`));
}

export async function refreshPx4ParamSnapshots({ hwIds, componentId = 1 }) {
  return postGcsResource(GCS_ROUTE_KEYS.px4ParamsSnapshots, {
    hw_ids: hwIds,
    component_id: componentId,
  });
}

export async function getPx4ParamSnapshot(snapshotId) {
  return fetchGcsResource(buildPx4ParamsUrl(`/snapshots/${encodeURIComponent(snapshotId)}`));
}

export async function getPx4ParamSnapshotRows(snapshotId) {
  return fetchGcsResource(buildPx4ParamsUrl(`/snapshots/${encodeURIComponent(snapshotId)}/rows`));
}

export async function createPx4ParamPatchJob({
  hwIds,
  entries,
  source = 'manual',
  verifyReadback = true,
}) {
  return postGcsResource(GCS_ROUTE_KEYS.px4ParamsPatchJobs, {
    hw_ids: hwIds,
    source,
    verify_readback: verifyReadback,
    entries,
  });
}

export async function getPx4ParamPatchJob(jobId) {
  return fetchGcsResource(buildPx4ParamsUrl(`/patch-jobs/${encodeURIComponent(jobId)}`));
}

export async function importQgcParameterFile(content) {
  return postGcsResource(buildPx4ParamsUrl('/imports/qgc'), { content });
}

export async function importMdsPatch(content) {
  return postGcsResource(buildPx4ParamsUrl('/imports/mds'), { content });
}

export async function diffPx4ParamSnapshot({
  snapshotId,
  desiredEntries,
  includeUnchanged = false,
}) {
  return postGcsResource(buildPx4ParamsUrl('/diff'), {
    snapshot_id: snapshotId,
    desired_entries: desiredEntries,
    include_unchanged: includeUnchanged,
  });
}
