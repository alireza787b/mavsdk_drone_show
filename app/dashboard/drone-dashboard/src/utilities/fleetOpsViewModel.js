import { areGitRevisionsEquivalent } from './missionIdentityUtils';

const HEALTHY_VALUES = new Set(['healthy', 'active', 'running', 'synced', 'success', 'ok']);
const WARNING_VALUES = new Set(['warning', 'degraded', 'unknown', 'inactive']);
const ERROR_VALUES = new Set(['error', 'failed', 'unhealthy']);
const ACTIVE_BOOT_PHASES = new Set(['starting', 'locked', 'validation', 'network', 'git_url', 'stash', 'fetch', 'checkout', 'reset', 'validate', 'service_reconcile', 'runtime_reconcile', 'restart']);
const TERMINAL_BOOT_PHASES = new Set(['success', 'ready']);

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

export function buildGitHubDocsUrl(remoteUrl, branch, docPath) {
  const normalized = String(remoteUrl || '').trim().replace(/\.git$/, '');
  const safeBranch = String(branch || 'main').trim() || 'main';
  const safeDocPath = String(docPath || '').replace(/^\/+/, '');
  if (!safeDocPath) {
    return null;
  }

  let match = normalized.match(/^https:\/\/github\.com\/([^/]+)\/(.+)$/i);
  if (!match) {
    match = normalized.match(/^git@github\.com:([^/]+)\/(.+)$/i);
  }
  if (!match) {
    match = normalized.match(/^ssh:\/\/git@github\.com\/([^/]+)\/(.+)$/i);
  }
  if (!match) {
    return null;
  }

  const owner = match[1];
  const repo = match[2].replace(/\.git$/, '');
  return `https://github.com/${owner}/${repo}/blob/${safeBranch}/${safeDocPath}`;
}

function formatHashMatch(runtime) {
  if (!runtime || runtime.config_hash_match === null || runtime.config_hash_match === undefined) {
    return 'hash unknown';
  }
  return runtime.config_hash_match
    ? `hash ${compactHash(runtime.applied_config_hash || runtime.desired_config_hash)}`
    : `hash drift ${compactHash(runtime.applied_config_hash)} -> ${compactHash(runtime.desired_config_hash)}`;
}

function formatConnectivityProfile(runtime) {
  if (runtime?.profile_present === false) {
    return 'fleet profile source missing';
  }
  const profileHash = compactHash(runtime?.profile_hash);
  return profileHash === 'unknown' ? 'profile hash unknown' : `profile ${profileHash}`;
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
  if (['not_required', 'unchanged', 'skipped', 'disabled', 'none', 'no_restart_required', 'present', 'provisioned'].includes(normalized)) {
    return 'good';
  }
  return classifyTone(value);
}

function normalizeBootPhaseLabel(value) {
  return String(value || 'unknown')
    .replaceAll('_', ' ')
    .replace(/^./, (letter) => letter.toUpperCase());
}

export function classifyNodeBootStatus(bootStatus, payloadTimestamp) {
  if (!bootStatus) {
    return {
      state: 'unknown',
      label: 'Unknown',
      tone: 'muted',
      detail: 'No boot/init status has been reported.',
      active: false,
    };
  }

  const phase = String(bootStatus.phase || 'unknown').trim().toLowerCase() || 'unknown';
  const status = String(bootStatus.status || '').trim().toLowerCase();
  const nowMs = Number(payloadTimestamp || Date.now());
  const timestampMs = Number(bootStatus.timestamp || 0);
  const ageSec = timestampMs > 0 && Number.isFinite(nowMs)
    ? Math.max(0, Math.round((nowMs - timestampMs) / 1000))
    : null;
  const stale = ageSec !== null && ageSec > 900;
  const message = bootStatus.message || normalizeBootPhaseLabel(phase);

  if (status === 'error' || phase === 'error') {
    return {
      state: 'error',
      label: 'Boot error',
      tone: 'danger',
      detail: message,
      ageSec,
      active: false,
    };
  }

  if (status === 'warning' || phase === 'fetch_failed_cached') {
    return {
      state: 'warning',
      label: 'Boot warning',
      tone: 'warning',
      detail: message,
      ageSec,
      active: false,
    };
  }

  if (TERMINAL_BOOT_PHASES.has(phase) || status === 'success') {
    return {
      state: stale ? 'stale_success' : 'success',
      label: stale ? 'Boot stale' : 'Boot OK',
      tone: stale ? 'muted' : 'good',
      detail: message,
      ageSec,
      active: false,
    };
  }

  if (ACTIVE_BOOT_PHASES.has(phase) || status === 'running') {
    return {
      state: stale ? 'stale_running' : 'initializing',
      label: stale ? 'Boot stale' : 'Initializing',
      tone: stale ? 'warning' : 'warning',
      detail: message,
      ageSec,
      active: !stale,
    };
  }

  return {
    state: 'unknown',
    label: 'Boot unknown',
    tone: stale ? 'muted' : 'warning',
    detail: message,
    ageSec,
    active: false,
  };
}

export function classifyNodePresence(heartbeat, payloadTimestamp, bootStatus = null) {
  const boot = classifyNodeBootStatus(bootStatus, payloadTimestamp);
  if (!heartbeat) {
    if (boot.active) {
      return {
        state: 'initializing',
        label: 'Initializing',
        tone: 'warning',
        detail: `Node boot/init phase: ${boot.detail}`,
      };
    }
    return {
      state: 'never_seen',
      label: 'Never seen',
      tone: 'muted',
      detail: 'Configured node has not reported a heartbeat in this GCS session.',
    };
  }

  if (heartbeat.presence && typeof heartbeat.presence === 'object') {
    const state = String(heartbeat.presence.state || heartbeat.presence_state || 'unknown');
    const longOffline = Boolean(heartbeat.presence.long_offline);
    const labels = {
      live: 'Live',
      blocked: 'Live blocked',
      recently_lost: 'Recent loss',
      stale: 'Stale',
      offline: longOffline ? 'Long offline' : 'Offline',
      never_seen: 'Never seen',
    };
    const tones = {
      live: 'good',
      blocked: 'warning',
      recently_lost: 'warning',
      stale: 'warning',
      offline: 'danger',
      never_seen: 'muted',
    };
    return {
      state,
      label: labels[state] || state.replace(/^./, (value) => value.toUpperCase()),
      tone: tones[state] || 'warning',
      detail: heartbeat.presence.detail || heartbeat.presence.label || 'Presence evidence is incomplete.',
      ageSec: heartbeat.presence.age_sec ?? heartbeat.heartbeat_age_sec ?? null,
      source: heartbeat.presence.source || 'unknown',
      longOffline,
    };
  }

  const nowMs = Number(payloadTimestamp || Date.now());
  const lastHeartbeatMs = Number(heartbeat.last_heartbeat || heartbeat.timestamp || 0);
  const ageSec = lastHeartbeatMs > 0 && Number.isFinite(nowMs)
    ? Math.max(0, Math.round((nowMs - lastHeartbeatMs) / 1000))
    : null;
  const runtimeMode = normalizeRuntimeMode(heartbeat.runtime_mode);

  if (heartbeat.online) {
    return {
      state: 'live',
      label: 'Live',
      tone: 'good',
      detail: ageSec === null ? 'Heartbeat is active.' : `Heartbeat age ${ageSec}s.`,
    };
  }

  if (lastHeartbeatMs > 0 && ageSec !== null && ageSec <= 30) {
    return {
      state: 'recently_lost',
      label: 'Recent loss',
      tone: 'warning',
      detail: `Last heartbeat ${ageSec}s ago; monitor for recovery or flapping.`,
    };
  }

  if (lastHeartbeatMs > 0 && ageSec !== null && ageSec <= 60) {
    return {
      state: 'stale',
      label: 'Stale',
      tone: 'warning',
      detail: `Last heartbeat ${ageSec}s ago; link is stale.`,
    };
  }

  if (runtimeMode && runtimeMode !== 'unknown') {
    return {
      state: 'offline',
      label: 'Offline',
      tone: 'danger',
      detail: ageSec === null ? 'Node heartbeat is stale.' : `Last heartbeat ${ageSec}s ago.`,
    };
  }

  return {
    state: 'unknown',
    label: 'Unknown',
    tone: 'warning',
    detail: 'Heartbeat status is incomplete; verify node runtime and mode declaration.',
  };
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
  const mavsdkTone = classifyRuntimeStepTone(gitSyncRuntime.mavsdk_runtime_status);
  const hasDeferredManualAction = Array.isArray(gitSyncRuntime.deferred_unit_actions)
    && gitSyncRuntime.deferred_unit_actions.some((action) => String(action || '').includes('manual_unit_update_required'));
  const tone = worstTone(
    statusTone,
    serviceReloadTone,
    mavlinkTone,
    connectivityTone,
    mavsdkTone,
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
      label: 'Unmanaged',
      tone: 'muted',
      detail: 'MDS is not managing Wi-Fi on this node; network telemetry is still reported separately.',
    };
  }

  const serviceStatus = runtime.service_status || 'unknown';
  const hashDrift = runtime.config_hash_match === false;
  const profileMissing = runtime.profile_present === false;
  const healthy = serviceStatus === 'active' && !profileMissing && !hashDrift;

  if (profileMissing) {
    return {
      state: 'profile_missing',
      label: 'Profile missing',
      tone: 'warning',
      detail: `Smart Wi-Fi is ${serviceStatus}; mode ${runtime.mode || 'unknown'}; ${formatConnectivityProfile(runtime)}. Add an approved fleet baseline, then use Fleet Ops Wi-Fi preview/apply. ${formatHashMatch(runtime)}.`,
    };
  }

  return {
    state: healthy ? 'healthy' : hashDrift ? 'drifted' : serviceStatus,
    label: healthy ? 'Healthy' : hashDrift ? 'Drift' : serviceStatus.replace(/^./, (value) => value.toUpperCase()),
    tone: healthy ? 'good' : hashDrift ? 'warning' : classifyTone(serviceStatus),
    detail: `Smart Wi-Fi ${serviceStatus}; mode ${runtime.mode || 'unknown'}; ${formatConnectivityProfile(runtime)}; ${formatHashMatch(runtime)}.`,
  };
}

function rowNeedsAttention(row) {
  return !row.online
    || isAttentionTone(row.presence.tone)
    || isAttentionTone(row.boot.tone)
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

function normalizeBootStatusMap(nodeBootPayload) {
  const nodes = nodeBootPayload?.nodes && typeof nodeBootPayload.nodes === 'object' ? nodeBootPayload.nodes : {};
  const byKey = new Map();
  Object.entries(nodes).forEach(([key, node]) => {
    if (!node || typeof node !== 'object') {
      return;
    }
    [node.hw_id, node.pos_id, key].filter((value) => value !== undefined && value !== null).forEach((value) => {
      byKey.set(String(value), node);
    });
  });
  return { nodes, byKey };
}

function makeRow(gitKey, gitStatus, heartbeat, bootStatus, gcsStatus, payloadTimestamp, bootPayloadTimestamp) {
  const posId = gitStatus?.pos_id ?? heartbeat?.pos_id ?? bootStatus?.pos_id ?? gitKey;
  const hwId = gitStatus?.hw_id ?? heartbeat?.hw_id ?? bootStatus?.hw_id ?? gitKey;
  const runtimeMode = normalizeRuntimeMode(heartbeat?.runtime_mode || bootStatus?.runtime_mode || gitStatus?.runtime_mode);
  const boot = classifyNodeBootStatus(bootStatus, bootPayloadTimestamp || payloadTimestamp);
  const presence = classifyNodePresence(heartbeat, payloadTimestamp, bootStatus);
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
    ip: heartbeat?.ip || bootStatus?.ip || gitStatus?.ip || 'unknown',
    online,
    runtimeMode,
    runtimeModeLabel: formatRuntimeMode(runtimeMode),
    presence,
    branch: gitStatus?.branch || 'unknown',
    commit: gitStatus?.commit || '',
    shortCommit: compactCommit(gitStatus?.commit),
    accessMode: gitStatus?.repo_access_mode || 'unknown',
    accessLabel: formatRepoAccessMode(gitStatus?.repo_access_mode),
    authSummary: gitStatus?.git_auth_health_summary || '',
    sync,
    auth,
    boot,
    nodeSyncRuntime,
    mavlink,
    connectivity,
    mavlinkRuntime: gitStatus?.mavlink_runtime || null,
    connectivityRuntime: gitStatus?.connectivity_runtime || null,
    gitSyncRuntime: gitStatus?.git_sync_runtime || null,
    bootStatus: bootStatus || null,
    gitStatus: gitStatus || null,
  };

  return {
    ...row,
    needsAttention: rowNeedsAttention(row),
    hasDrift: rowHasComplianceDrift(row),
  };
}

export function buildFleetOpsViewModel(gitPayload, heartbeatPayload, nodeBootPayload = null) {
  const gitStatusByNode = gitPayload?.git_status && typeof gitPayload.git_status === 'object'
    ? gitPayload.git_status
    : {};
  const gcsStatus = gitPayload?.gcs_status || {};
  const docs = {
    fleetOps: buildGitHubDocsUrl(gcsStatus.remote_url, gcsStatus.branch, 'docs/guides/fleet-ops.md'),
  };
  const { heartbeats, byKey: heartbeatByKey } = normalizeHeartbeatMap(heartbeatPayload);
  const { nodes: bootNodes, byKey: bootByKey } = normalizeBootStatusMap(nodeBootPayload);
  const rows = [];
  const seen = new Set();

  Object.entries(gitStatusByNode).forEach(([key, gitStatus]) => {
    const heartbeat = heartbeatByKey.get(String(gitStatus?.hw_id || ''))
      || heartbeatByKey.get(String(gitStatus?.pos_id || ''))
      || heartbeatByKey.get(String(key));
    const bootStatus = bootByKey.get(String(gitStatus?.hw_id || ''))
      || bootByKey.get(String(gitStatus?.pos_id || ''))
      || bootByKey.get(String(key));
    const row = makeRow(key, gitStatus, heartbeat, bootStatus, gcsStatus, heartbeatPayload?.timestamp, nodeBootPayload?.timestamp);
    rows.push(row);
    seen.add(row.key);
  });

  heartbeats.forEach((heartbeat) => {
    const key = String(heartbeat.hw_id || heartbeat.pos_id || heartbeat.ip || '');
    if (key && !seen.has(key)) {
      const bootStatus = bootByKey.get(String(heartbeat.hw_id || ''))
        || bootByKey.get(String(heartbeat.pos_id || ''));
      rows.push(makeRow(key, null, heartbeat, bootStatus, gcsStatus, heartbeatPayload?.timestamp, nodeBootPayload?.timestamp));
      seen.add(key);
    }
  });

  Object.entries(bootNodes).forEach(([key, bootStatus]) => {
    const rowKey = String(bootStatus?.hw_id || bootStatus?.pos_id || key || '');
    if (rowKey && !seen.has(rowKey)) {
      rows.push(makeRow(rowKey, null, null, bootStatus, gcsStatus, heartbeatPayload?.timestamp, nodeBootPayload?.timestamp));
      seen.add(rowKey);
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
    recentLoss: countBy((row) => row.presence.state === 'recently_lost'),
    stale: countBy((row) => row.presence.state === 'stale'),
    offline: countBy((row) => row.presence.state === 'offline'),
    neverSeen: countBy((row) => row.presence.state === 'never_seen'),
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
    docs,
    gitPayload,
    heartbeatPayload,
  };
}
