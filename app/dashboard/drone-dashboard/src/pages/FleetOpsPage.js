import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  FaBroadcastTower,
  FaCheck,
  FaCodeBranch,
  FaExclamationTriangle,
  FaFilter,
  FaKey,
  FaLink,
  FaNetworkWired,
  FaPlus,
  FaSatelliteDish,
  FaSearch,
  FaServer,
  FaShieldAlt,
  FaSyncAlt,
  FaWifi,
} from 'react-icons/fa';
import {
  ActionIconButton,
  EmptyState,
  MetricStrip,
  OperatorCard,
  OperatorNotice,
  PageShell,
  StatusBadge,
} from '../components/ui';
import useFetch from '../hooks/useFetch';
import {
  GCS_ROUTE_KEYS,
  applyFleetGitSyncResponse,
  dryRunFleetGitSyncResponse,
} from '../services/gcsApiService';
import { buildFleetOpsViewModel, compactHash } from '../utilities/fleetOpsViewModel';
import '../styles/FleetOpsPage.css';

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'access', label: 'Access' },
  { key: 'sidecars', label: 'Sidecars' },
  { key: 'sync', label: 'Sync' },
];

const FILTERS = [
  { key: 'all', label: 'All nodes' },
  { key: 'attention', label: 'Attention' },
  { key: 'online', label: 'Online' },
  { key: 'offline', label: 'Offline' },
  { key: 'drift', label: 'Drift' },
];

const SYNC_STEPS = {
  preview: 'Preview',
  review: 'Review',
  apply: 'Apply',
  verify: 'Verify',
};

const syncSteps = (states = {}) => [
  { label: SYNC_STEPS.preview, state: states.preview || 'pending' },
  { label: SYNC_STEPS.review, state: states.review || 'pending' },
  { label: SYNC_STEPS.apply, state: states.apply || 'pending' },
  { label: SYNC_STEPS.verify, state: states.verify || 'pending' },
];

function toPrimitiveTone(tone) {
  if (tone === 'good') {
    return 'success';
  }
  return ['info', 'success', 'warning', 'danger', 'muted', 'neutral'].includes(tone) ? tone : 'neutral';
}

function StatusMetric({ icon: Icon, label, status, detail }) {
  return (
    <div className={`fleet-ops-metric fleet-ops-metric--${status.tone}`}>
      <Icon aria-hidden="true" />
      <div>
        <span>{label}</span>
        <strong>{status.label}</strong>
        <small aria-label={detail || status.detail}>{detail || status.detail}</small>
      </div>
    </div>
  );
}

function dashboardPortFromRuntime(runtime) {
  const listen = runtime?.dashboard_listen;
  if (typeof listen !== 'string' || !listen.trim()) {
    return null;
  }
  const match = listen.trim().match(/:(\d+)$/);
  if (!match) {
    return null;
  }
  return match[1];
}

function formatDashboardHost(ip) {
  const value = String(ip || '').trim();
  if (!value) {
    return '';
  }
  return value.includes(':') && !value.startsWith('[') ? `[${value}]` : value;
}

function resolveDashboardHref(runtime, nodeIp) {
  if (!runtime || runtime.dashboard_enabled === false || runtime.dashboard_access_mode === 'disabled') {
    return null;
  }
  if (runtime.dashboard_url) {
    return runtime.dashboard_url;
  }
  if (runtime.dashboard_access_mode === 'local_only') {
    return null;
  }
  const port = dashboardPortFromRuntime(runtime);
  const host = formatDashboardHost(nodeIp);
  if (!port || !host) {
    return null;
  }
  return `http://${host}:${port}`;
}

function DashboardQuickLinks({ row }) {
  const links = [
    {
      key: 'mavlink',
      label: 'Open MAVLink dashboard',
      icon: <FaSatelliteDish aria-hidden="true" />,
      href: resolveDashboardHref(row.mavlinkRuntime, row.ip),
      runtime: row.mavlinkRuntime,
    },
    {
      key: 'wifi',
      label: 'Open Smart Wi-Fi dashboard',
      icon: <FaWifi aria-hidden="true" />,
      href: resolveDashboardHref(row.connectivityRuntime, row.ip),
      runtime: row.connectivityRuntime,
    },
  ];

  if (!row.mavlinkRuntime && !row.connectivityRuntime) {
    return null;
  }

  return (
    <div className="fleet-ops-node-card__quick-links" aria-label={`Drone ${row.posId} sidecar dashboard links`}>
      {links.map((link) => {
        const reason = link.runtime?.dashboard_access_mode === 'local_only'
          ? `${link.label} is local-only; use SSH tunneling or enable direct dashboard listen on the node.`
          : `${link.label} unavailable; dashboard is disabled or not installed.`;
        return link.href ? (
          <a
            key={link.key}
            href={link.href}
            target="_blank"
            rel="noreferrer"
            aria-label={link.label}
            data-tooltip={link.label}
          >
            {link.icon}
          </a>
        ) : (
          <span
            key={link.key}
            className="is-disabled"
            aria-label={reason}
            data-tooltip={reason}
            tabIndex={0}
          >
            {link.icon}
          </span>
        );
      })}
    </div>
  );
}

function DashboardLinks({ runtime, nodeIp, label }) {
  if (!runtime) {
    return null;
  }

  const dashboardHref = resolveDashboardHref(runtime, nodeIp);
  const fallbackLabel = runtime.dashboard_access_mode === 'local_only'
    ? 'Local-only'
    : runtime.dashboard_enabled === false
      ? 'Dashboard off'
      : 'No dashboard URL';

  return (
    <div className="fleet-ops-node-card__links">
      {runtime.repo_web_url ? (
        <a href={runtime.repo_web_url} target="_blank" rel="noreferrer">
          <FaCodeBranch /> Repo
        </a>
      ) : null}
      {dashboardHref ? (
        <a href={dashboardHref} target="_blank" rel="noreferrer" aria-label={`Open ${label} dashboard`}>
          <FaLink /> Open UI
        </a>
      ) : (
        <span aria-label="Dashboard is disabled, local-only, or not reported. Use node SSH or a future GCS proxy for local-only dashboards.">
          <FaShieldAlt /> {fallbackLabel}
        </span>
      )}
    </div>
  );
}

function SidecarHashFacts({ runtime, profile = false }) {
  if (!runtime) {
    return null;
  }

  return (
    <dl className="fleet-ops-sidecar-facts">
      <div>
        <dt>Desired</dt>
        <dd>{compactHash(runtime.desired_config_hash)}</dd>
      </div>
      <div>
        <dt>Applied</dt>
        <dd>{compactHash(runtime.applied_config_hash)}</dd>
      </div>
      <div>
        <dt>Match</dt>
        <dd>{runtime.config_hash_match === true ? 'Yes' : runtime.config_hash_match === false ? 'No' : 'Unknown'}</dd>
      </div>
      {profile ? (
        <div>
          <dt>Profile</dt>
          <dd>{compactHash(runtime.profile_hash)}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function sidecarDriftState(runtime) {
  if (!runtime) {
    return 'unreachable';
  }
  if (runtime.drift_state) {
    return runtime.drift_state;
  }
  if (runtime.config_hash_match === true) {
    return 'in_sync';
  }
  if (runtime.config_hash_match === false) {
    return 'outdated';
  }
  return runtime.profile_present === false ? 'missing_fleet_baseline' : 'unmanaged';
}

function sidecarDriftTone(state) {
  if (state === 'in_sync') {
    return 'success';
  }
  if (state === 'unmanaged') {
    return 'muted';
  }
  if (state === 'unreachable') {
    return 'danger';
  }
  return 'warning';
}

function formatDriftState(state) {
  return String(state || 'unknown').replaceAll('_', ' ');
}

function SidecarDashboardLink({ runtime, row, label }) {
  const href = resolveDashboardHref(runtime, row.ip);
  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" aria-label={`Open ${label} dashboard for drone ${row.posId}`}>
        <FaLink aria-hidden="true" />
        Open
      </a>
    );
  }

  const access = runtime?.dashboard_access_mode || 'unavailable';
  return (
    <span className="fleet-ops-sidecar-table__muted" aria-label={`${label} dashboard ${access}`}>
      <FaShieldAlt aria-hidden="true" />
      {access === 'local_only' ? 'Local' : 'None'}
    </span>
  );
}

function SidecarTableCell({ runtime, row, label, icon }) {
  const drift = sidecarDriftState(runtime);
  const service = runtime?.service_state || runtime?.router_service_status || runtime?.service_status || 'unknown';
  const mode = runtime?.mode || runtime?.management_mode || runtime?.import_mode || 'unknown';
  const desiredHash = compactHash(runtime?.desired_hash || runtime?.desired_config_hash);
  const localHash = compactHash(runtime?.local_hash || runtime?.profile_hash || runtime?.applied_hash || runtime?.applied_config_hash);

  return (
    <div className="fleet-ops-sidecar-table__sidecar">
      <div className="fleet-ops-sidecar-table__sidecar-head">
        {icon}
        <span>{label}</span>
        <StatusBadge tone={sidecarDriftTone(drift)}>{formatDriftState(drift)}</StatusBadge>
      </div>
      <div className="fleet-ops-sidecar-table__facts" aria-label={`${label} profile facts for drone ${row.posId}`}>
        <span title={`Service: ${service}`}>Svc {service}</span>
        <span title={`Mode: ${mode}`}>Mode {mode}</span>
        <span title={`Desired hash: ${desiredHash}`}>Desired {desiredHash}</span>
        <span title={`Local/applied hash: ${localHash}`}>Local {localHash}</span>
      </div>
      <div className="fleet-ops-sidecar-table__links">
        <SidecarDashboardLink runtime={runtime} row={row} label={label} />
      </div>
    </div>
  );
}

function SidecarFleetTable({ rows }) {
  if (!rows.length) {
    return null;
  }

  return (
    <section className="fleet-ops-sidecar-table" aria-label="Sidecar fleet table">
      <header>
        <div>
          <span className="fleet-ops-sidecar-table__eyebrow">Fleet sidecars</span>
          <h2>Wi-Fi and MAVLink posture</h2>
        </div>
        <span className="fleet-ops-sidecar-table__hint">Read-only status. Mutating profile actions stay behind node sync/reconcile.</span>
      </header>
      <div className="fleet-ops-sidecar-table__rows">
        {rows.map((row) => (
          <article key={row.key} className="fleet-ops-sidecar-table__row">
            <div className="fleet-ops-sidecar-table__node">
              <strong>Drone {row.posId}</strong>
              <span>HW {row.hwId}</span>
              <small>{row.ip}</small>
            </div>
            <SidecarTableCell
              runtime={row.mavlinkRuntime}
              row={row}
              label="MAVLink"
              icon={<FaSatelliteDish aria-hidden="true" />}
            />
            <SidecarTableCell
              runtime={row.connectivityRuntime}
              row={row}
              label="Smart Wi-Fi"
              icon={<FaWifi aria-hidden="true" />}
            />
          </article>
        ))}
      </div>
    </section>
  );
}

function NodeDetails({ row, activeTab }) {
  if (activeTab === 'access') {
    return (
      <dl className="fleet-ops-facts">
        <div>
          <dt>Access</dt>
          <dd>{row.accessLabel}</dd>
        </div>
        <div>
          <dt>Policy</dt>
          <dd>{row.accessMode === 'ssh_key' ? 'SSH read posture' : 'Read-only sync posture'}</dd>
        </div>
        <div>
          <dt>Auth</dt>
          <dd>{row.auth.detail}</dd>
        </div>
        <div>
          <dt>Branch</dt>
          <dd>{row.branch}</dd>
        </div>
      </dl>
    );
  }

  if (activeTab === 'sidecars') {
    return (
      <div className="fleet-ops-sidecar-grid">
        <section>
          <h3>MAVLink</h3>
          <p>{row.mavlink.detail}</p>
          <SidecarHashFacts runtime={row.mavlinkRuntime} />
          <DashboardLinks runtime={row.mavlinkRuntime} nodeIp={row.ip} label="MAVLink" />
        </section>
        <section>
          <h3>Connectivity</h3>
          <p>{row.connectivity.detail}</p>
          <SidecarHashFacts runtime={row.connectivityRuntime} profile />
          <DashboardLinks runtime={row.connectivityRuntime} nodeIp={row.ip} label="Smart Wi-Fi" />
        </section>
      </div>
    );
  }

  if (activeTab === 'sync') {
    const gitSync = row.gitSyncRuntime || {};
    return (
      <dl className="fleet-ops-facts">
        <div>
          <dt>Commit</dt>
          <dd>{row.shortCommit}</dd>
        </div>
        <div>
          <dt>GCS Sync</dt>
          <dd>{row.sync.detail}</dd>
        </div>
        <div>
          <dt>Runtime Sync</dt>
          <dd>{gitSync.summary || row.boot.detail || 'No node-local git sync runtime state has been recorded yet.'}</dd>
        </div>
        <div>
          <dt>Boot phase</dt>
          <dd>{row.boot.detail}</dd>
        </div>
        <div>
          <dt>Reconcile</dt>
          <dd>
            MAVSDK {gitSync.mavsdk_runtime_status || 'unknown'} · MAVLink {gitSync.mavlink_runtime_reconcile_status || 'unknown'} · Connectivity {gitSync.connectivity_reconcile_status || 'unknown'}
          </dd>
        </div>
      </dl>
    );
  }

  return (
    <div className="fleet-ops-status-grid">
      <StatusMetric icon={FaBroadcastTower} label="Link" status={row.presence} />
      <StatusMetric icon={FaServer} label="Boot" status={row.boot} />
      <StatusMetric icon={FaSyncAlt} label="Repo" status={row.sync} />
      <StatusMetric icon={FaKey} label="Auth" status={row.auth} />
      <StatusMetric icon={FaSatelliteDish} label="MAVLink" status={row.mavlink} />
      <StatusMetric icon={FaWifi} label="Wi-Fi" status={row.connectivity} />
    </div>
  );
}

function NodeCard({ row, activeTab, selected, onToggleSelected }) {
  return (
    <OperatorCard
      className={`fleet-ops-node-card ${row.needsAttention ? 'is-attention' : 'is-clear'}`}
      selected={selected}
      tone={row.needsAttention ? 'warning' : 'neutral'}
    >
      <header className="fleet-ops-node-card__header">
        <ActionIconButton
          icon={selected ? <FaCheck /> : <FaPlus />}
          label={`${selected ? 'Deselect' : 'Select'} drone ${row.posId}`}
          size="sm"
          className="fleet-ops-node-card__selector"
          onClick={() => onToggleSelected(row.key)}
          active={selected}
        />
        <div className="fleet-ops-node-card__identity">
          <span className="fleet-ops-node-card__eyebrow">Drone {row.posId}</span>
          <h2>HW {row.hwId}</h2>
          <p>{row.ip}</p>
        </div>
        <div className="fleet-ops-node-card__pills">
          <StatusBadge tone={toPrimitiveTone(row.presence.tone)} className="fleet-ops-pill" aria-label={row.presence.detail}>
            {row.presence.label}
          </StatusBadge>
          {row.boot.state !== 'unknown' ? (
            <StatusBadge tone={toPrimitiveTone(row.boot.tone)} className="fleet-ops-pill" aria-label={row.boot.detail}>
              {row.boot.label}
            </StatusBadge>
          ) : null}
          <StatusBadge tone={row.runtimeMode === 'real' ? 'success' : row.runtimeMode === 'sitl' ? 'info' : 'muted'} className={`fleet-ops-pill fleet-ops-pill--${row.runtimeMode === 'real' ? 'real' : row.runtimeMode === 'sitl' ? 'sitl' : 'muted'}`}>
            {row.runtimeModeLabel}
          </StatusBadge>
        </div>
        <DashboardQuickLinks row={row} />
      </header>
      <NodeDetails row={row} activeTab={activeTab} />
    </OperatorCard>
  );
}

function filterRows(rows, query, filter) {
  const normalizedQuery = String(query || '').trim().toLowerCase();
  return rows.filter((row) => {
    if (filter === 'attention' && !row.needsAttention) {
      return false;
    }
    if (filter === 'online' && !row.online) {
      return false;
    }
    if (filter === 'offline' && row.online) {
      return false;
    }
    if (filter === 'drift' && !row.hasDrift) {
      return false;
    }

    if (!normalizedQuery) {
      return true;
    }

    return [
      row.posId,
      row.hwId,
      row.ip,
      row.branch,
      row.shortCommit,
      row.accessLabel,
      row.runtimeModeLabel,
      row.boot.detail,
      row.sync.detail,
      row.auth.detail,
      row.nodeSyncRuntime.detail,
      row.mavlink.detail,
      row.connectivity.detail,
    ].join(' ').toLowerCase().includes(normalizedQuery);
  });
}

function countGitSyncResults(results, ok) {
  return Object.values(results || {}).filter((result) => Boolean(result && result.ok) === ok).length;
}

function SyncProgressPanel({ progress }) {
  if (!progress || progress.phase === 'idle') {
    return null;
  }

  return (
    <section
      className={'fleet-ops-sync-progress is-' + (progress.tone || 'neutral')}
      aria-label="Fleet Ops sync progress"
      aria-live="polite"
      role="status"
    >
      <div className="fleet-ops-sync-progress__copy">
        <strong>{progress.title}</strong>
        <span>{progress.message}</span>
      </div>
      <ol className="fleet-ops-sync-progress__steps">
        {(progress.steps || []).map((step) => (
          <li key={step.label} className={'is-' + (step.state || 'pending')}>
            <span aria-hidden="true" />
            <p>{step.label}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function FleetOpsPage({ gitStatusOverride = null, heartbeatOverride = null, nodeBootStatusOverride = null }) {
  const location = useLocation();
  const urlScopeAppliedRef = useRef();
  const urlAutoPlanAppliedRef = useRef();
  const [activeTab, setActiveTab] = useState('overview');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selectedKeys, setSelectedKeys] = useState(() => new Set());
  const [actionState, setActionState] = useState({ running: false, message: '', tone: 'neutral' });
  const [pendingGitSync, setPendingGitSync] = useState(null);
  const [syncProgress, setSyncProgress] = useState({ phase: 'idle' });
  const [gitSyncAck, setGitSyncAck] = useState(false);
  const [opsToken, setOpsToken] = useState(() => {
    if (typeof window === 'undefined') return '';
    return window.sessionStorage?.getItem('fleetOpsMutationToken') || '';
  });
  const gitStatusFetch = useFetch(gitStatusOverride ? null : GCS_ROUTE_KEYS.gitStatus, 5000);
  const heartbeatFetch = useFetch(heartbeatOverride ? null : GCS_ROUTE_KEYS.fleetHeartbeats, 3000);
  const nodeBootStatusFetch = useFetch(nodeBootStatusOverride ? null : GCS_ROUTE_KEYS.fleetNodeBootStatus, 3000);
  const connectivityProfileFetch = useFetch(gitStatusOverride ? null : GCS_ROUTE_KEYS.connectivityProfile, 10000);
  const gitStatus = gitStatusOverride || gitStatusFetch.data;
  const heartbeatStatus = heartbeatOverride || heartbeatFetch.data;
  const nodeBootStatus = nodeBootStatusOverride || nodeBootStatusFetch.data;
  const connectivityProfile = connectivityProfileFetch.data;
  const loading = !gitStatusOverride && gitStatusFetch.loading && !gitStatus;
  const error = gitStatusFetch.error || heartbeatFetch.error || nodeBootStatusFetch.error;

  const viewModel = useMemo(
    () => buildFleetOpsViewModel(gitStatus, heartbeatStatus, nodeBootStatus),
    [gitStatus, heartbeatStatus, nodeBootStatus],
  );
  const visibleRows = useMemo(
    () => filterRows(viewModel.rows, query, filter),
    [viewModel.rows, query, filter],
  );
  const selectedRows = useMemo(
    () => viewModel.rows.filter((row) => selectedKeys.has(row.key)),
    [selectedKeys, viewModel.rows],
  );
  const selectedPosIds = useMemo(
    () => selectedRows.map((row) => Number(row.posId)).filter((value) => Number.isFinite(value) && value > 0),
    [selectedRows],
  );
  const targetLabel = selectedPosIds.length ? `${selectedPosIds.length} selected` : 'all eligible';

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const requestedTab = params.get('tab');
    const requestedFilter = params.get('filter');
    if (TABS.some((tab) => tab.key === requestedTab)) {
      setActiveTab(requestedTab);
    }
    if (FILTERS.some((item) => item.key === requestedFilter)) {
      setFilter(requestedFilter);
    }
  }, [location.search]);

  useEffect(() => {
    if (urlScopeAppliedRef.current === location.search) {
      return;
    }
    const params = new URLSearchParams(location.search);
    if (params.get('scope') !== 'needs-sync' || !viewModel.rows.length) {
      return;
    }
    const syncKeys = viewModel.rows
      .filter((row) => row.online && row.hasDrift)
      .map((row) => row.key);
    if (syncKeys.length) {
      setSelectedKeys(new Set(syncKeys));
    }
    urlScopeAppliedRef.current = location.search;
  }, [location.search, viewModel.rows]);

  const toggleSelected = useCallback((key) => {
    setSelectedKeys((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const selectVisible = useCallback(() => {
    setSelectedKeys(new Set(visibleRows.map((row) => row.key)));
  }, [visibleRows]);

  const clearSelection = useCallback(() => {
    setSelectedKeys(new Set());
  }, []);

  const runGitSync = useCallback(async () => {
    setActionState({ running: true, message: 'Planning sync for ' + targetLabel + ' node(s)...', tone: 'neutral' });
    setSyncProgress({
      phase: 'planning',
      tone: 'neutral',
      title: 'Preparing sync preview',
      message: 'Checking the GCS commit, selected online drones, and safety gates. No drone has been updated yet.',
      steps: syncSteps({ preview: 'active' }),
    });
    setPendingGitSync(null);
    setGitSyncAck(false);
    try {
      const payload = selectedPosIds.length ? { pos_ids: selectedPosIds } : {};
      const response = await dryRunFleetGitSyncResponse(payload);
      const data = response?.data || {};
      const results = data.results || {};
      const okCount = countGitSyncResults(results, true);
      const blockedCount = countGitSyncResults(results, false);
      const targetCommit = data.target_commit ? compactHash(data.target_commit) : 'current GCS commit';
      setPendingGitSync(data);
      setActionState({
        running: false,
        tone: okCount > 0 && blockedCount === 0 ? 'success' : 'warning',
        message: 'Sync plan ready: ' + okCount + ' ready' + (blockedCount ? ', ' + blockedCount + ' blocked' : '') + '. No commands sent yet.',
      });
      setSyncProgress({
        phase: okCount > 0 ? 'ready' : 'blocked',
        tone: okCount > 0 && blockedCount === 0 ? 'success' : 'warning',
        title: okCount > 0 ? 'Preview ready' : 'No eligible sync target',
        message: okCount > 0
          ? 'Ready to update ' + okCount + ' drone(s) to ' + targetCommit + '. Review the targets before applying.'
          : 'No online eligible drone can be synced from this plan. Resolve blocked nodes, then plan again.',
        steps: syncSteps({ preview: 'done', review: okCount > 0 ? 'active' : 'blocked' }),
      });
    } catch (error) {
      setActionState({
        running: false,
        tone: 'danger',
        message: error?.response?.data?.detail || error?.message || 'Fleet sync preview failed.',
      });
      setSyncProgress({
        phase: 'failed',
        tone: 'danger',
        title: 'Sync preview failed',
        message: error?.response?.data?.detail || error?.message || 'Fleet sync preview failed.',
        steps: syncSteps({ preview: 'blocked' }),
      });
    }
  }, [selectedPosIds, targetLabel]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('scope') !== 'needs-sync' || params.get('autoplan') !== '1') {
      return;
    }
    if (urlAutoPlanAppliedRef.current === location.search) {
      return;
    }
    if (!selectedPosIds.length || actionState.running || pendingGitSync) {
      return;
    }
    urlAutoPlanAppliedRef.current = location.search;
    runGitSync();
  }, [actionState.running, location.search, pendingGitSync, runGitSync, selectedPosIds.length]);

  const applyGitSync = useCallback(async () => {
    if (!pendingGitSync?.job_id || !pendingGitSync?.confirmation_token) {
      return;
    }
    if (!gitSyncAck) {
      setActionState({
        running: false,
        tone: 'warning',
        message: 'Review and acknowledge the sync preview before applying updates.',
      });
      return;
    }
    setActionState({ running: true, message: 'Applying sync and waiting for verification...', tone: 'neutral' });
    setSyncProgress({
      phase: 'applying',
      tone: 'neutral',
      title: 'Sync in progress',
      message: 'Sending the approved update command to each ready drone, then verifying that node commits match GCS.',
      steps: syncSteps({ preview: 'done', review: 'done', apply: 'active' }),
    });
    try {
      const response = await applyFleetGitSyncResponse({
        dry_run_id: pendingGitSync.job_id,
        confirmation: {
          acknowledged_risks: true,
          confirmation_token: pendingGitSync.confirmation_token,
        },
      });
      const data = response?.data || {};
      const failed = Array.isArray(data.failed_drones) && data.failed_drones.length
        ? ` Failed: ${data.failed_drones.join(', ')}.`
        : '';
      setPendingGitSync(null);
      setGitSyncAck(false);
      setActionState({
        running: false,
        tone: data.success ? 'success' : 'warning',
        message: `${data.message || 'Sync completed.'}${failed}`,
      });
      setSyncProgress({
        phase: data.success ? 'success' : 'attention',
        tone: data.success ? 'success' : 'warning',
        title: data.success ? 'Sync verified' : 'Sync needs attention',
        message: (data.message || 'Sync completed.') + failed,
        steps: syncSteps({ preview: 'done', review: 'done', apply: 'done', verify: data.success ? 'done' : 'blocked' }),
      });
    } catch (error) {
      setActionState({
        running: false,
        tone: 'danger',
        message: error?.response?.data?.detail || error?.message || 'Fleet sync apply failed.',
      });
      setSyncProgress({
        phase: 'failed',
        tone: 'danger',
        title: 'Sync apply failed',
        message: error?.response?.data?.detail || error?.message || 'Fleet sync apply failed.',
        steps: syncSteps({ preview: 'done', review: 'done', apply: 'blocked' }),
      });
    }
  }, [gitSyncAck, pendingGitSync]);

  const cancelGitSync = useCallback(() => {
    setPendingGitSync(null);
    setGitSyncAck(false);
    setSyncProgress({ phase: 'idle' });
  }, []);

  const updateOpsToken = useCallback((value) => {
    setOpsToken(value);
    if (typeof window !== 'undefined') {
      if (value) {
        window.sessionStorage?.setItem('fleetOpsMutationToken', value);
      } else {
        window.sessionStorage?.removeItem('fleetOpsMutationToken');
        window.localStorage?.removeItem('fleetOpsMutationToken');
      }
    }
  }, []);

  const pendingGitSyncReadyCount = pendingGitSync ? countGitSyncResults(pendingGitSync.results, true) : 0;
  const pendingGitSyncBlockedCount = pendingGitSync ? countGitSyncResults(pendingGitSync.results, false) : 0;
  const pendingGitSyncBranch = pendingGitSync?.target_branch || viewModel.gcsStatus?.branch || 'current branch';
  const pendingGitSyncCommit = pendingGitSync?.target_commit ? compactHash(pendingGitSync.target_commit) : 'current GCS commit';
  const connectivityProfileLabel = connectivityProfile?.profile_present
    ? `Wi-Fi ${compactHash(connectivityProfile.profile_hash)}`
    : 'Wi-Fi profile unset';
  const connectivityProfileTitle = connectivityProfile?.message || 'Repo-owned Smart Wi-Fi fleet profile status.';
  const summaryItems = [
    {
      key: 'online',
      icon: <FaBroadcastTower />,
      label: 'Online',
      value: `${viewModel.summary.online}/${viewModel.summary.total}`,
      detail: 'Heartbeat-active nodes',
      tone: viewModel.summary.online === viewModel.summary.total ? 'success' : 'warning',
    },
    {
      key: 'synced',
      icon: <FaSyncAlt />,
      label: 'Synced',
      value: `${viewModel.summary.synced}/${viewModel.summary.total}`,
      detail: 'Node commit matches GCS',
      tone: viewModel.summary.synced === viewModel.summary.total ? 'success' : 'warning',
    },
    {
      key: 'auth',
      icon: <FaKey />,
      label: 'Auth',
      value: `${viewModel.summary.authHealthy}/${viewModel.summary.total}`,
      detail: 'Healthy read posture',
      tone: viewModel.summary.authHealthy === viewModel.summary.total ? 'success' : 'warning',
    },
    {
      key: 'sidecars',
      icon: <FaNetworkWired />,
      label: 'Sidecars',
      value: `${viewModel.summary.mavlinkHealthy} MAVLink`,
      detail: `${viewModel.summary.connectivityHealthy} connectivity · ${viewModel.summary.sidecarAttention + viewModel.summary.nodeSyncRuntimeAttention} attention`,
      tone: viewModel.summary.sidecarAttention || viewModel.summary.nodeSyncRuntimeAttention ? 'warning' : 'success',
    },
  ];

  return (
    <PageShell
      className="fleet-ops-page"
      eyebrow="Fleet Maintenance"
      title="Fleet Ops"
      subtitle="Drone-node sync, access, and sidecars. GCS host controls stay separate."
      icon={<FaNetworkWired />}
      docsRoute="/fleet-ops"
      docsOptions={{
        repoUrl: viewModel.gcsStatus?.remote_url || '',
        branch: viewModel.gcsStatus?.branch || '',
      }}
      actions={(
        <Link className="fleet-ops-page__scope-link" to="/runtime-admin" aria-label="Open GCS Runtime Admin">
          <FaServer aria-hidden="true" />
          <span>GCS Runtime</span>
        </Link>
      )}
      status={(
        <div className="fleet-ops-page__status-pills">
          <StatusBadge tone="info">Drone nodes</StatusBadge>
          <StatusBadge tone="muted">GCS {viewModel.gcsStatus?.branch || 'unknown'}</StatusBadge>
          <StatusBadge tone={viewModel.summary.needsAttention ? 'warning' : 'success'}>
            {viewModel.summary.needsAttention} attention
          </StatusBadge>
        </div>
      )}
    >

      {error ? (
        <OperatorNotice tone="warning" title="Live feed degraded" icon={<FaExclamationTriangle />}>
          Showing the last available fleet data where possible.
        </OperatorNotice>
      ) : null}

      {actionState.message ? (
        <OperatorNotice
          tone={toPrimitiveTone(actionState.tone)}
          title={actionState.tone === 'danger' ? 'Action failed' : 'Fleet action'}
          icon={actionState.tone === 'danger' ? <FaExclamationTriangle /> : <FaShieldAlt />}
        >
          {actionState.message}
        </OperatorNotice>
      ) : null}

      <MetricStrip items={summaryItems} label="Fleet operations summary" className="fleet-ops-summary-grid" />

      <section className="fleet-ops-toolbar" aria-label="Fleet operations controls">
        <label>
          <span><FaSearch /> Search</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Drone, IP, branch, commit..."
          />
        </label>
        <label>
          <span><FaFilter /> Filter</span>
          <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            {FILTERS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
        </label>
        <div className="fleet-ops-tabs" aria-label="Fleet Ops sections">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              aria-pressed={activeTab === tab.key}
              className={activeTab === tab.key ? 'is-active' : ''}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      <section className="fleet-ops-actions" aria-label="Fleet Ops actions">
        <div className="fleet-ops-actions__summary">
          <FaShieldAlt aria-hidden="true" />
          <span aria-label="Actions target selected nodes first. With no selection, sync targets all eligible online nodes.">
            {selectedRows.length ? `${selectedRows.length} selected` : 'All eligible'}
          </span>
          <span className="fleet-ops-actions__profile" aria-label={connectivityProfileTitle}>
            <FaWifi aria-hidden="true" /> {connectivityProfileLabel}
          </span>
          <input
            className="fleet-ops-actions__token-input"
            type="password"
            value={opsToken}
            onChange={(event) => updateOpsToken(event.target.value)}
            placeholder="Ops token"
            aria-label="Fleet Ops mutation token"
          />
        </div>
        <div className="fleet-ops-actions__buttons">
          <Link className="fleet-ops-actions__link" to="/fleet-ops/wifi" aria-label="Open Fleet Ops Wi-Fi profile controls">
            <FaWifi aria-hidden="true" /> Wi-Fi profiles
          </Link>
          <Link className="fleet-ops-actions__link" to="/fleet-ops/mavlink" aria-label="Open Fleet Ops MAVLink profile controls">
            <FaSatelliteDish aria-hidden="true" /> MAVLink profiles
          </Link>
          <button type="button" onClick={selectVisible} disabled={!visibleRows.length || actionState.running} aria-label="Select all visible nodes">
            Select view
          </button>
          <button type="button" onClick={clearSelection} disabled={!selectedRows.length || actionState.running} aria-label="Clear node selection">
            Clear
          </button>
          <button
            type="button"
            className={actionState.running && syncProgress.phase === 'planning' ? 'is-primary is-busy' : 'is-primary'}
            onClick={runGitSync}
            disabled={actionState.running}
            aria-label="Plan Fleet Ops sync now"
            aria-busy={actionState.running && syncProgress.phase === 'planning'}
          >
            <FaSyncAlt /> {actionState.running ? 'Working' : 'Sync now'}
          </button>
        </div>
      </section>

      <SyncProgressPanel progress={syncProgress} />

      {pendingGitSync ? (
        <section className="fleet-ops-confirm" aria-label="Confirm Fleet Ops git sync">
          <div className="fleet-ops-confirm__copy">
            <strong>Review sync preview</strong>
            <span>No commands have been sent yet. Apply updates only the ready drones shown in this preview.</span>
            <dl className="fleet-ops-confirm__facts">
              <div>
                <dt>Ready</dt>
                <dd>{pendingGitSyncReadyCount}</dd>
              </div>
              <div>
                <dt>Blocked</dt>
                <dd>{pendingGitSyncBlockedCount}</dd>
              </div>
              <div>
                <dt>Branch</dt>
                <dd>{pendingGitSyncBranch}</dd>
              </div>
              <div>
                <dt>Commit</dt>
                <dd>{pendingGitSyncCommit}</dd>
              </div>
            </dl>
          </div>
          <label className="fleet-ops-confirm__ack">
            <input
              type="checkbox"
              checked={gitSyncAck}
              onChange={(event) => setGitSyncAck(event.target.checked)}
            />
            I reviewed this preview and want to apply updates to the ready drones.
          </label>
          <div className="fleet-ops-confirm__actions">
            <button type="button" onClick={cancelGitSync} disabled={actionState.running}>Cancel</button>
            <button
              type="button"
              className={actionState.running && syncProgress.phase === 'applying' ? 'is-primary is-busy' : 'is-primary'}
              onClick={applyGitSync}
              disabled={actionState.running || !gitSyncAck || !pendingGitSyncReadyCount}
              aria-busy={actionState.running && syncProgress.phase === 'applying'}
            >
              <FaShieldAlt /> {actionState.running && syncProgress.phase === 'applying' ? 'Applying...' : 'Apply updates'}
            </button>
          </div>
        </section>
      ) : null}

      {loading ? (
        <EmptyState icon={<FaNetworkWired />} title="Loading Fleet Ops" detail="Refreshing node sync, access, and sidecar posture." />
      ) : null}

      {!loading && activeTab === 'sidecars' ? (
        <SidecarFleetTable rows={visibleRows} />
      ) : null}

      {!loading && visibleRows.length === 0 ? (
        <EmptyState icon={<FaFilter />} title="No matching nodes" detail="Change the filter or search text to widen the fleet view." />
      ) : (
        <section className="fleet-ops-node-grid" aria-label="Fleet node operations">
          {visibleRows.map((row) => (
            <NodeCard
              key={row.key}
              row={row}
              activeTab={activeTab}
              selected={selectedKeys.has(row.key)}
              onToggleSelected={toggleSelected}
            />
          ))}
        </section>
      )}
    </PageShell>
  );
}
