import useFetch from './useFetch';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import { useEffect, useState } from 'react';

const DEFAULT_POLL_INTERVAL_MS = 15000;
const RUNTIME_MODE_CACHE_KEY = 'mds:gcs-runtime-mode';

function normalizeModeLabel(mode) {
  const normalized = String(mode || '').trim().toLowerCase();
  if (normalized === 'real') {
    return 'REAL';
  }
  if (normalized === 'sitl') {
    return 'SITL';
  }
  return 'UNKNOWN';
}

export default function useGcsRuntimeStatus(pollIntervalMs = DEFAULT_POLL_INTERVAL_MS) {
  const { data, error, loading } = useFetch(GCS_ROUTE_KEYS.systemRuntimeStatus, pollIntervalMs);
  const [cachedMode, setCachedMode] = useState(() => {
    if (typeof window === 'undefined') {
      return '';
    }
    return window.localStorage?.getItem(RUNTIME_MODE_CACHE_KEY) || '';
  });
  const mode = String(data?.mode || cachedMode || '').trim().toLowerCase() || 'unknown';
  const configuredMode = String(data?.configured_mode || '').trim().toLowerCase() || mode;
  const modeLabel = normalizeModeLabel(mode);
  const configuredModeLabel = normalizeModeLabel(configuredMode);

  useEffect(() => {
    if (!['real', 'sitl'].includes(String(data?.mode || '').toLowerCase())) {
      return;
    }
    const nextMode = String(data.mode).toLowerCase();
    setCachedMode(nextMode);
    if (typeof window !== 'undefined') {
      window.localStorage?.setItem(RUNTIME_MODE_CACHE_KEY, nextMode);
    }
  }, [data?.mode]);

  return {
    raw: data || null,
    error,
    loading,
    mode,
    modeLabel,
    configuredMode,
    configuredModeLabel,
    modeSource: data?.mode_source || '',
    repoAccessMode: data?.repo_access_mode || 'unknown',
    repoUrl: data?.repo_url || '',
    repoBranch: data?.repo_branch || '',
    gitAutoPush: Boolean(data?.git_auto_push),
    configuredGitAutoPush: Boolean(
      Object.prototype.hasOwnProperty.call(data || {}, 'configured_git_auto_push')
        ? data?.configured_git_auto_push
        : data?.git_auto_push
    ),
    restartRequired: Boolean(data?.restart_required),
    sitlInstanceCount: Number.isInteger(data?.sitl_instance_count) ? data?.sitl_instance_count : null,
    installDir: data?.install_dir || '',
    gcsConfigPath: data?.gcs_config_path || '',
    gitAuthHealth: data?.git_auth_health || { status: 'unknown', summary: '', issues: [] },
    repoSyncStatus: data?.repo_sync_status || null,
    fleetDefaults: data?.fleet_defaults || null,
    mavlinkRuntime: data?.mavlink_runtime || null,
    connectivityRuntime: data?.connectivity_runtime || null,
    docs: data?.docs || {},
  };
}
