import { saveSwarmConfigResponse, publishSwarmConfigResponse } from '../services/gcsApiService';

/** Apply a captured draft, then publish only the revision actually acknowledged. */
export async function saveSwarmPlan({ assignments, revision, needsApply, publish,
  acknowledgedUnavailableIds = [], onApplied = () => {}, onPublishing = () => {} }) {
  let applied = false;
  let response;
  if (needsApply) {
    response = await saveSwarmConfigResponse(assignments, {
      commit: false, ...(revision ? { revision } : {}), acknowledgedUnavailableIds,
    });
    applied = true;
    revision = response?.data?.config?.revision;
    onApplied(response.data);
  }
  if (!publish) return response;
  try {
    if (!revision) throw new Error('Applied plan revision is unavailable. Reload before saving to the repository.');
    onPublishing();
    return await publishSwarmConfigResponse(revision);
  } catch (error) {
    throw Object.assign(error instanceof Error ? error : new Error(error?.message || 'Repository save failed'),
      error, { saveStage: 'publish', planApplied: applied, appliedRevision: revision });
  }
}
