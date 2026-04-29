import React, { useCallback, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
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
  FaUpload,
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
import { GCS_ROUTE_KEYS, syncReposResponse, updateConnectivityProfileResponse } from '../services/gcsApiService';
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
    },
    {
      key: 'wifi',
      label: 'Open Smart Wi-Fi dashboard',
      icon: <FaWifi aria-hidden="true" />,
      href: resolveDashboardHref(row.connectivityRuntime, row.ip),
    },
  ].filter((link) => link.href);

  if (!links.length) {
    return null;
  }

  return (
    <div className="fleet-ops-node-card__quick-links" aria-label={`Drone ${row.posId} sidecar dashboard links`}>
      {links.map((link) => (
        <a key={link.key} href={link.href} target="_blank" rel="noreferrer" aria-label={link.label}>
          {link.icon}
        </a>
      ))}
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
          <dd>{gitSync.summary || 'No node-local git sync runtime state has been recorded yet.'}</dd>
        </div>
        <div>
          <dt>Reconcile</dt>
          <dd>
            MAVLink {gitSync.mavlink_runtime_reconcile_status || 'unknown'} · Connectivity {gitSync.connectivity_reconcile_status || 'unknown'}
          </dd>
        </div>
      </dl>
    );
  }

  return (
    <div className="fleet-ops-status-grid">
      <StatusMetric icon={FaBroadcastTower} label="Link" status={row.presence} />
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
      row.sync.detail,
      row.auth.detail,
      row.nodeSyncRuntime.detail,
      row.mavlink.detail,
      row.connectivity.detail,
    ].join(' ').toLowerCase().includes(normalizedQuery);
  });
}

export default function FleetOpsPage({ gitStatusOverride = null, heartbeatOverride = null }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selectedKeys, setSelectedKeys] = useState(() => new Set());
  const [actionState, setActionState] = useState({ running: false, message: '', tone: 'neutral' });
  const [connectivityProfileStatus, setConnectivityProfileStatus] = useState(null);
  const connectivityProfileInputRef = useRef(null);
  const gitStatusFetch = useFetch(gitStatusOverride ? null : GCS_ROUTE_KEYS.gitStatus, 5000);
  const heartbeatFetch = useFetch(heartbeatOverride ? null : GCS_ROUTE_KEYS.fleetHeartbeats, 3000);
  const connectivityProfileFetch = useFetch(gitStatusOverride ? null : GCS_ROUTE_KEYS.connectivityProfile, 10000);
  const gitStatus = gitStatusOverride || gitStatusFetch.data;
  const heartbeatStatus = heartbeatOverride || heartbeatFetch.data;
  const connectivityProfile = connectivityProfileStatus || connectivityProfileFetch.data;
  const loading = !gitStatusOverride && gitStatusFetch.loading && !gitStatus;
  const error = gitStatusFetch.error || heartbeatFetch.error;

  const viewModel = useMemo(
    () => buildFleetOpsViewModel(gitStatus, heartbeatStatus),
    [gitStatus, heartbeatStatus],
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
    setActionState({ running: true, message: `Syncing ${targetLabel} node(s)...`, tone: 'neutral' });
    try {
      const payload = selectedPosIds.length ? { pos_ids: selectedPosIds } : {};
      const response = await syncReposResponse(payload);
      const data = response?.data || {};
      const failed = Array.isArray(data.failed_drones) && data.failed_drones.length
        ? ` Failed: ${data.failed_drones.join(', ')}.`
        : '';
      setActionState({
        running: false,
        tone: data.success ? 'success' : 'warning',
        message: `${data.message || 'Sync completed.'}${failed}`,
      });
    } catch (error) {
      setActionState({
        running: false,
        tone: 'danger',
        message: error?.response?.data?.detail || error?.message || 'Fleet sync failed.',
      });
    }
  }, [selectedPosIds, targetLabel]);

  const openConnectivityProfileImport = useCallback(() => {
    connectivityProfileInputRef.current?.click();
  }, []);

  const handleConnectivityProfileImport = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) {
      return;
    }

    setActionState({ running: true, message: `Importing ${file.name}...`, tone: 'neutral' });
    try {
      const text = await file.text();
      const profile = JSON.parse(text);
      const response = await updateConnectivityProfileResponse({ profile });
      const data = response?.data || {};
      setConnectivityProfileStatus(data);
      const gitWarning = data.git_result && data.git_result.success === false
        ? ` Git: ${data.git_result.message || 'commit/push failed.'}`
        : '';
      setActionState({
        running: false,
        tone: gitWarning ? 'warning' : 'success',
        message: `${data.message || 'Smart Wi-Fi fleet profile saved.'} Hash ${compactHash(data.profile_hash)}.${gitWarning}`,
      });
    } catch (error) {
      setActionState({
        running: false,
        tone: 'danger',
        message: error?.response?.data?.detail || error?.message || 'Smart Wi-Fi profile import failed.',
      });
    }
  }, []);

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
        </div>
        <div className="fleet-ops-actions__buttons">
          <input
            ref={connectivityProfileInputRef}
            className="fleet-ops-file-input"
            type="file"
            accept="application/json,.json"
            onChange={handleConnectivityProfileImport}
            aria-label="Import Smart Wi-Fi fleet profile"
          />
          <ActionIconButton
            icon={<FaUpload />}
            label="Import Smart Wi-Fi fleet profile"
            onClick={openConnectivityProfileImport}
            disabled={actionState.running}
          >
            Wi-Fi profile
          </ActionIconButton>
          <button type="button" onClick={selectVisible} disabled={!visibleRows.length || actionState.running} aria-label="Select all visible nodes">
            Select view
          </button>
          <button type="button" onClick={clearSelection} disabled={!selectedRows.length || actionState.running} aria-label="Clear node selection">
            Clear
          </button>
          <button type="button" className="is-primary" onClick={runGitSync} disabled={actionState.running}>
            <FaSyncAlt /> {actionState.running ? 'Running' : 'Sync + reconcile'}
          </button>
        </div>
      </section>

      {loading ? (
        <EmptyState icon={<FaNetworkWired />} title="Loading Fleet Ops" detail="Refreshing node sync, access, and sidecar posture." />
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
