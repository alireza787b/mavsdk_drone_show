import { useMemo } from 'react';
import { useObservationResource } from '../contexts/ObservationContext';
import { GIT_BRANCH as STATIC_BRANCH, GIT_COMMIT as STATIC_COMMIT, GIT_REPO as STATIC_REPO } from '../version';


function formatRepoLabel(remoteUrl, fallback = STATIC_REPO) {
  const normalized = String(remoteUrl || '').trim();
  if (!normalized) {
    return fallback;
  }

  return normalized
    .replace(/\.git$/, '')
    .replace(/^git@github\.com:/, '')
    .replace(/^https?:\/\/github\.com\//, '')
    .replace(/^github\.com\//, '')
    .trim() || fallback;
}

export default function useGcsGitInfo() {
  const resource = useObservationResource('git');
  const gitInfo = resource.response?.data?.gcs_status || resource.response?.data || null;

  return useMemo(() => {
    const branch = gitInfo?.branch || gitInfo?.current_branch || STATIC_BRANCH;
    const commit = String(gitInfo?.commit || STATIC_COMMIT || '').slice(0, 8);
    const repo = formatRepoLabel(gitInfo?.remote_url, STATIC_REPO);

    return {
      raw: gitInfo,
      branch,
      commit,
      repo,
      runtimeLabel: commit ? `${branch} • ${commit}` : branch,
    };
  }, [gitInfo]);
}
