import { areGitRevisionsEquivalent } from './missionIdentityUtils';

const HEALTHY_VALUES = new Set(['healthy', 'active', 'running', 'synced', 'success', 'ok']);
const WARNING_VALUES = new Set(['warning', 'degraded', 'unknown', 'inactive']);
const ERROR_VALUES = new Set(['error', 'failed', 'unhealthy']);

export function normalizeRuntimeMode(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (['real', 'hardware', 'production'].includes(normalized)) {
    return 'real';
  }
  if (['sitl', 'sim', 'simulation'].includes(normalized)) {
    return 'sitl';
  }
  return normalized || 'unknown';
}

export function formatRuntimeMode(value) {
  const normalized = normalizeRuntimeMode(value);
  if (normalized === 'real') {
    return 'REAL';
  }
  if (normalized === 'sitl') {
    return 'SITL';
  }
  return 'UNKNOWN';
}

export function formatRepoAccessMode(value) {
  switch (value) {
    case 'ssh_key':
      return 'SSH key';
    case 'https_token_file':
      return 'HTTPS token';
    case 'https_public_or_read_only':
      return 'Public HTTPS';
    case 'custom_or_unknown':
      return 'Custom';
    default:
      return value || 'Unknown';
  }
}

function compactCommit(commit) {
  return commit ? String(commit).slice(0, 8) : 'unknown';
}

export function compactHash(hash) {
  const value = String(hash || '').trim();
  if (!value || value === 'unknown') {
    return 'unknown';
  }
  return value.slice(0, 12);
}

function formatHashMatch(runtime) {
  if (!runtime || runtime.config_hash_match === null || runtime.config_hash_match === undefined) {
    return 'hash unknown';
  }
  return runtime.config_hash_match
    ? `hash ${compactHash(runtime.applied_config_hash || runtime.desired_config_hash)}`
    : `hash drift ${compactHash(runtime.applied_config_hash)} -> ${compactHash(runtime.desired_config_hash)}`;
}

function classifyTone(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (HEALTHY_VALUES.has(normalized)) {
    return 'good';
  }
  if (ERROR_VALUES.has(normalized)) {
    return 'danger';
  }
  if (WARNING_VALUES.has(normalized)) {
    return 'warning';
  }
  return normalized ? 'warning' : 'muted';
}

function classifyRuntimeStepTone(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (!normalized || normalized === 'unknown') {
    return 'muted';
  }
  if (['not_required', 'unchanged', 'skipped', 'disabled', 'none', 'no_restart_required'].includes(normalized)) {
    return 'good';
  }
  return classifyTone(value);
}

function isAttentionTone(tone) {
  return tone === 'warning' || tone === 'danger';
}

function worstTone(...tones) {
  if (tones.includes('danger')) {
    return 'danger';
  }
  if (tones.includes('warning')) {
    return 'warning';
  }
  if (tones.includes('good')) {
    return 'good';
  }
  return 'muted';
}

export function classifyGitSync(gitStatus, gcsStatus) {
  if (!gitStatus) {
    return {
      state: 'unknown',
      label: 'Unknown',
      tone: 'muted',
      detail: 'No node git status has been reported.',
    };
  }

  const synced = typeof gitStatus.in_sync_with_gcs === 'boolean'
    ? gitStatus.in_sync_with_gcs
    : areGitRevisionsEquivalent(gitStatus.commit, gcsStatus?.commit);

  if (synced) {
    return {
      state: 'synced',
      label: 'Synced',
      tone: 'good',
      detail: `Node ${compactCommit(gitStatus.commit)} matches GCS.`,
    };
  }

  return {
    state: 'drifted',
    label: 'Drift',
    tone: 'warning',
    detail: `Node ${compactCommit(gitStatus.commit)} vs GCS ${compactCommit(gcsStatus?.commit)}.`,
  };
}

export function classifyGitAuth(gitStatus) {
  if (!gitStatus) {
    return {
      state: 'unknown',
      label: 'Unknown',
      tone: 'muted',
      detail: 'No node git auth report.',
    };
  }

  const rawStatus = gitStatus.git_auth_health_status || 'unknown';
  return {
    state: rawStatus,
    label: rawStatus === 'healthy' ? 'Healthy' : rawStatus.replace(/^./, (value) => value.toUpperCase()),
    tone: classifyTone(rawStatus),
    detail: gitStatus.git_auth_health_summary || 'No auth summary reported.',
  };
}

export function classifyGitSyncRuntime(gitSyncRuntime) {
  if (!gitSyncRuntime) {
    return {
      state: 'unknown',
      label: 'Unknown',
      tone: 'muted',
      detail: 'No node-local git sync runtime state has been reported.',
    };
  }

  const statusTone = classifyRuntimeStepTone(gitSyncRuntime.status);
  const serviceReloadTone = classifyRuntimeStepTone(gitSyncRuntime.service_reload_status);
  const mavlinkTone = classifyRuntimeStepTone(gitSyncRuntime.mavlink_runtime_reconcile_status);
  const connectivityTone = classifyRuntimeStepTone(gitSyncRuntime.connectivity_reconcile_status);
  const hasDeferredManualAction = Array.isArray(gitSyncRuntime.deferred_unit_actions)
    && gitSyncRuntime.deferred_unit_actions.some((action) => String(action || '').includes('manual_unit_update_required'));
  const tone = worstTone(
    statusTone,
    serviceReloadTone,
    mavlinkTone,
    connectivityTone,
    hasDeferredManualAction ? 'warning' : 'muted',
  );
  const state = tone === 'good' ? 'healthy' : tone === 'muted' ? 'unknown' : 'attention';

  return {
    state,
    label: state === 'healthy' ? 'Healthy' : state === 'attention' ? 'Attention' : 'Unknown',
    tone,
    detail: gitSyncRuntime.summary || 'Node-local git sync runtime state is incomplete.',
  };
}

export function classifyMavlinkRuntime(runtime, runtimeMode = 'unknown') {
  const mode = normalizeRuntimeMode(runtimeMode);
  if (mode === 'sitl') {
    return {
      state: 'not_applicable',
      label: 'N/A',
      tone: 'muted',
      detail: 'SITL containers use embedded mavlink-routerd, not managed mavlink-anywhere.',
    };
  }

  if (!runtime) {
    return {
      state: 'unknown',
      label: 'Unknown',
      tone: 'muted',
      detail: 'No MAVLink sidecar report.',
    };
  }

  const managementMode = String(runtime.management_mode || '').toLowerCase();
  if (['disabled', 'manual', 'none'].includes(managementMode)) {
    return {
      state: 'disabled',
      label: 'Disabled',
      tone: 'muted',
      detail: `MAVLink management mode is ${runtime.management_mode || 'disabled'}.`,
    };
  }

  const routerStatus = runtime.router_service_status || 'unknown';
  const dashboardStatus = runtime.dashboard_service_status || 'unknown';
  const hashDrift = runtime.config_hash_match === false;
  const healthy = routerStatus === 'active' && (!runtime.dashboard_enabled || dashboardStatus === 'active') && !hashDrift;

  return {
    state: healthy ? 'healthy' : hashDrift ? 'drifted' : routerStatus,
    label: healthy ? 'Healthy' : hashDrift ? 'Drift' : routerStatus.replace(/^./, (value) => value.toUpperCase()),
    tone: healthy ? 'good' : hashDrift ? 'warning' : classifyTone(routerStatus),
    detail: `Ref ${runtime.ref || 'unknown'}; router ${routerStatus}; dashboard ${runtime.dashboard_access_mode || 'unknown'}; ${formatHashMatch(runtime)}.`,
  };
}

export function classifyConnectivityRuntime(runtime, runtimeMode = 'unknown') {
  const mode = normalizeRuntimeMode(runtimeMode);
  if (mode === 'sitl') {
    return {
      state: 'not_applicable',
      label: 'N/A',
      tone: 'muted',
      detail: 'SITL does not require Smart Wi-Fi Manager.',
    };
  }

  if (!runtime) {
    return {
      state: 'unknown',
      label: 'Unknown',
      tone: 'muted',
      detail: 'No connectivity sidecar report.',
    };
  }

  const backend = String(runtime.backend || 'none').toLowerCase();
  if (backend === 'none') {
    return {
      state: 'not_applicable',
      label: 'Not used',
      tone: 'muted',
      detail: 'Fleet policy does not require a connectivity sidecar on this node.',
    };
  }

  const serviceStatus = runtime.service_status || 'unknown';
  const hashDrift = runtime.config_hash_match === false;
  const healthy = serviceStatus === 'active' && runtime.profile_present !== false && !hashDrift;

  return {
    state: healthy ? 'healthy' : hashDrift ? 'drifted' : serviceStatus,
    label: healthy ? 'Healthy' : hashDrift ? 'Drift' : serviceStatus.replace(/^./, (value) => value.toUpperCase()),
    tone: healthy ? 'good' : hashDrift ? 'warning' : classifyTone(serviceStatus),
    detail: `Backend ${runtime.backend || 'unknown'}; mode ${runtime.mode || 'unknown'}; profile ${runtime.profile_present ? compactHash(runtime.profile_hash) : 'missing'}; ${formatHashMatch(runtime)}.`,
  };
}

function rowNeedsAttention(row) {
  return !row.online
    || isAttentionTone(row.sync.tone)
    || isAttentionTone(row.auth.tone)
    || isAttentionTone(row.nodeSyncRuntime.tone)
    || isAttentionTone(row.mavlink.tone)
    || isAttentionTone(row.connectivity.tone);
}

function rowHasComplianceDrift(row) {
  return row.sync.state !== 'synced'
    || row.nodeSyncRuntime.state === 'attention'
    || row.mavlink.state === 'drifted'
    || row.connectivity.state === 'drifted';
}

function normalizeHeartbeatMap(heartbeatPayload) {
  const heartbeats = Array.isArray(heartbeatPayload?.heartbeats) ? heartbeatPayload.heartbeats : [];
  const byKey = new Map();
  heartbeats.forEach((heartbeat) => {
    [heartbeat.hw_id, heartbeat.pos_id].filter((value) => value !== undefined && value !== null).forEach((value) => {
      byKey.set(String(value), heartbeat);
    });
  });
  return { heartbeats, byKey };
}

function makeRow(gitKey, gitStatus, heartbeat, gcsStatus) {
  const posId = gitStatus?.pos_id ?? heartbeat?.pos_id ?? gitKey;
  const hwId = gitStatus?.hw_id ?? heartbeat?.hw_id ?? gitKey;
  const runtimeMode = normalizeRuntimeMode(heartbeat?.runtime_mode || gitStatus?.runtime_mode);
  const sync = classifyGitSync(gitStatus, gcsStatus);
  const auth = classifyGitAuth(gitStatus);
  const nodeSyncRuntime = classifyGitSyncRuntime(gitStatus?.git_sync_runtime);
  const mavlink = classifyMavlinkRuntime(gitStatus?.mavlink_runtime, runtimeMode);
  const connectivity = classifyConnectivityRuntime(gitStatus?.connectivity_runtime, runtimeMode);
  const online = Boolean(heartbeat?.online);

  const row = {
    key: String(hwId || posId || gitKey),
    posId: String(posId || 'unknown'),
    hwId: String(hwId || 'unknown'),
    ip: heartbeat?.ip || gitStatus?.ip || 'unknown',
    online,
    runtimeMode,
    runtimeModeLabel: formatRuntimeMode(runtimeMode),
    branch: gitStatus?.branch || 'unknown',
    commit: gitStatus?.commit || '',
    shortCommit: compactCommit(gitStatus?.commit),
    accessMode: gitStatus?.repo_access_mode || 'unknown',
    accessLabel: formatRepoAccessMode(gitStatus?.repo_access_mode),
    authSummary: gitStatus?.git_auth_health_summary || '',
    sync,
    auth,
    nodeSyncRuntime,
    mavlink,
    connectivity,
    mavlinkRuntime: gitStatus?.mavlink_runtime || null,
    connectivityRuntime: gitStatus?.connectivity_runtime || null,
    gitSyncRuntime: gitStatus?.git_sync_runtime || null,
    gitStatus: gitStatus || null,
  };

  return {
    ...row,
    needsAttention: rowNeedsAttention(row),
    hasDrift: rowHasComplianceDrift(row),
  };
}

export function buildFleetOpsViewModel(gitPayload, heartbeatPayload) {
  const gitStatusByNode = gitPayload?.git_status && typeof gitPayload.git_status === 'object'
    ? gitPayload.git_status
    : {};
  const gcsStatus = gitPayload?.gcs_status || {};
  const { heartbeats, byKey: heartbeatByKey } = normalizeHeartbeatMap(heartbeatPayload);
  const rows = [];
  const seen = new Set();

  Object.entries(gitStatusByNode).forEach(([key, gitStatus]) => {
    const heartbeat = heartbeatByKey.get(String(gitStatus?.hw_id || ''))
      || heartbeatByKey.get(String(gitStatus?.pos_id || ''))
      || heartbeatByKey.get(String(key));
    const row = makeRow(key, gitStatus, heartbeat, gcsStatus);
    rows.push(row);
    seen.add(row.key);
  });

  heartbeats.forEach((heartbeat) => {
    const key = String(heartbeat.hw_id || heartbeat.pos_id || heartbeat.ip || '');
    if (key && !seen.has(key)) {
      rows.push(makeRow(key, null, heartbeat, gcsStatus));
      seen.add(key);
    }
  });

  rows.sort((left, right) => {
    const leftNumber = Number(left.posId);
    const rightNumber = Number(right.posId);
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && leftNumber !== rightNumber) {
      return leftNumber - rightNumber;
    }
    return left.key.localeCompare(right.key);
  });

  const countBy = (predicate) => rows.filter(predicate).length;
  const summary = {
    total: rows.length,
    online: countBy((row) => row.online),
    synced: countBy((row) => row.sync.state === 'synced'),
    authHealthy: countBy((row) => row.auth.tone === 'good'),
    mavlinkHealthy: countBy((row) => row.mavlink.tone === 'good'),
    connectivityHealthy: countBy((row) => row.connectivity.tone === 'good'),
    connectivityNotApplicable: countBy((row) => row.connectivity.state === 'not_applicable'),
    sidecarAttention: countBy((row) => isAttentionTone(row.mavlink.tone) || isAttentionTone(row.connectivity.tone)),
    nodeSyncRuntimeAttention: countBy((row) => isAttentionTone(row.nodeSyncRuntime.tone)),
    needsAttention: countBy((row) => row.needsAttention),
  };

  return {
    rows,
    summary,
    gcsStatus,
    gitPayload,
    heartbeatPayload,
  };
}
