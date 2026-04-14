import { useEffect, useMemo, useState } from 'react';

import { getUnifiedGitStatusResponse } from '../services/gcsApiService';
import { GIT_BRANCH as STATIC_BRANCH, GIT_COMMIT as STATIC_COMMIT, GIT_REPO as STATIC_REPO } from '../version';

const DEFAULT_POLL_INTERVAL_MS = 15000;

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

export default function useGcsGitInfo(pollIntervalMs = DEFAULT_POLL_INTERVAL_MS) {
  const [gitInfo, setGitInfo] = useState(null);

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      try {
        const response = await getUnifiedGitStatusResponse();
        const data = response?.data?.gcs_status || response?.data || null;
        if (mounted && data) {
          setGitInfo(data);
        }
      } catch {
        if (mounted) {
          setGitInfo(null);
        }
      }
    };

    load();
    const timer = window.setInterval(load, pollIntervalMs);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [pollIntervalMs]);

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
