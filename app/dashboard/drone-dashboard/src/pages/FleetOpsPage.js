import React, { useMemo, useState } from 'react';
import {
  FaBroadcastTower,
  FaCodeBranch,
  FaExclamationTriangle,
  FaFilter,
  FaKey,
  FaLink,
  FaNetworkWired,
  FaSatelliteDish,
  FaSearch,
  FaSyncAlt,
  FaWifi,
} from 'react-icons/fa';
import useFetch from '../hooks/useFetch';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
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

function StatusPill({ tone = 'muted', children, title }) {
  return (
    <span className={`fleet-ops-pill fleet-ops-pill--${tone}`} title={title}>
      {children}
    </span>
  );
}

function SummaryCard({ icon: Icon, label, value, detail, tone = 'neutral' }) {
  return (
    <article className={`fleet-ops-summary-card fleet-ops-summary-card--${tone}`}>
      <span className="fleet-ops-summary-card__icon" aria-hidden="true">
        <Icon />
      </span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function StatusMetric({ icon: Icon, label, status, detail }) {
  return (
    <div className={`fleet-ops-metric fleet-ops-metric--${status.tone}`}>
      <Icon aria-hidden="true" />
      <div>
        <span>{label}</span>
        <strong>{status.label}</strong>
        <small title={detail || status.detail}>{detail || status.detail}</small>
      </div>
    </div>
  );
}

function DashboardLinks({ runtime }) {
  if (!runtime) {
    return null;
  }

  return (
    <div className="fleet-ops-node-card__links">
      {runtime.repo_web_url ? (
        <a href={runtime.repo_web_url} target="_blank" rel="noreferrer">
          <FaCodeBranch /> Repo
        </a>
      ) : null}
      {runtime.dashboard_url ? (
        <a href={runtime.dashboard_url} target="_blank" rel="noreferrer">
          <FaLink /> Dashboard
        </a>
      ) : (
        <span title="Dashboard is disabled, local-only, or not reported.">No direct dashboard</span>
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
          <dd>{row.accessMode === 'ssh_key' ? 'Node SSH read posture' : 'Node read-only sync posture'}</dd>
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
          <DashboardLinks runtime={row.mavlinkRuntime} />
        </section>
        <section>
          <h3>Connectivity</h3>
          <p>{row.connectivity.detail}</p>
          <SidecarHashFacts runtime={row.connectivityRuntime} profile />
          <DashboardLinks runtime={row.connectivityRuntime} />
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
      <StatusMetric icon={FaSyncAlt} label="Repo" status={row.sync} />
      <StatusMetric icon={FaKey} label="Auth" status={row.auth} />
      <StatusMetric icon={FaSatelliteDish} label="MAVLink" status={row.mavlink} />
      <StatusMetric icon={FaWifi} label="Wi-Fi" status={row.connectivity} />
    </div>
  );
}

function NodeCard({ row, activeTab }) {
  return (
    <article className={`fleet-ops-node-card ${row.needsAttention ? 'is-attention' : 'is-clear'}`}>
      <header className="fleet-ops-node-card__header">
        <div>
          <span className="fleet-ops-node-card__eyebrow">Drone {row.posId}</span>
          <h2>HW {row.hwId}</h2>
          <p>{row.ip}</p>
        </div>
        <div className="fleet-ops-node-card__pills">
          <StatusPill tone={row.online ? 'good' : 'warning'} title={row.online ? 'Node heartbeat is online' : 'Node heartbeat is offline or stale'}>
            {row.online ? 'Online' : 'Offline'}
          </StatusPill>
          <StatusPill tone={row.runtimeMode === 'real' ? 'real' : row.runtimeMode === 'sitl' ? 'sitl' : 'muted'}>
            {row.runtimeModeLabel}
          </StatusPill>
        </div>
      </header>
      <NodeDetails row={row} activeTab={activeTab} />
    </article>
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
  const gitStatusFetch = useFetch(gitStatusOverride ? null : GCS_ROUTE_KEYS.gitStatus, 5000);
  const heartbeatFetch = useFetch(heartbeatOverride ? null : GCS_ROUTE_KEYS.fleetHeartbeats, 3000);
  const gitStatus = gitStatusOverride || gitStatusFetch.data;
  const heartbeatStatus = heartbeatOverride || heartbeatFetch.data;
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

  return (
    <main className="fleet-ops-page">
      <section className="fleet-ops-hero">
        <div>
          <span className="fleet-ops-eyebrow">Fleet Node Operations</span>
          <h1>Fleet Ops</h1>
          <p>
            Node-level sync, access, and sidecar posture. Runtime Admin remains GCS-host only;
            this page is the fleet compliance surface.
          </p>
        </div>
        <div className="fleet-ops-hero__pills">
          <StatusPill tone="muted">GCS {viewModel.gcsStatus?.branch || 'unknown'}</StatusPill>
          <StatusPill tone={viewModel.summary.needsAttention ? 'warning' : 'good'}>
            {viewModel.summary.needsAttention} attention
          </StatusPill>
        </div>
      </section>

      {error ? (
        <div className="fleet-ops-banner fleet-ops-banner--warning">
          <FaExclamationTriangle />
          <span>Fleet Ops could not refresh one or more live feeds. Showing the last available data where possible.</span>
        </div>
      ) : null}

      <section className="fleet-ops-summary-grid" aria-label="Fleet operations summary">
        <SummaryCard
          icon={FaBroadcastTower}
          label="Online"
          value={`${viewModel.summary.online}/${viewModel.summary.total}`}
          detail="Heartbeat-active nodes"
          tone={viewModel.summary.online === viewModel.summary.total ? 'good' : 'warning'}
        />
        <SummaryCard
          icon={FaSyncAlt}
          label="Synced"
          value={`${viewModel.summary.synced}/${viewModel.summary.total}`}
          detail="Node commit matches GCS"
          tone={viewModel.summary.synced === viewModel.summary.total ? 'good' : 'warning'}
        />
        <SummaryCard
          icon={FaKey}
          label="Auth"
          value={`${viewModel.summary.authHealthy}/${viewModel.summary.total}`}
          detail="Healthy read posture"
          tone={viewModel.summary.authHealthy === viewModel.summary.total ? 'good' : 'warning'}
        />
        <SummaryCard
          icon={FaNetworkWired}
          label="Sidecars"
          value={`${viewModel.summary.mavlinkHealthy} MAVLink`}
          detail={`${viewModel.summary.connectivityHealthy} connectivity healthy · ${viewModel.summary.sidecarAttention} sidecar · ${viewModel.summary.nodeSyncRuntimeAttention} sync attention`}
          tone={viewModel.summary.sidecarAttention || viewModel.summary.nodeSyncRuntimeAttention ? 'warning' : 'good'}
        />
      </section>

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
        <div className="fleet-ops-tabs" role="tablist" aria-label="Fleet Ops sections">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.key}
              className={activeTab === tab.key ? 'is-active' : ''}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      {loading ? (
        <section className="fleet-ops-empty">Loading fleet operations status...</section>
      ) : null}

      {!loading && visibleRows.length === 0 ? (
        <section className="fleet-ops-empty">No fleet nodes match the current filter.</section>
      ) : (
        <section className="fleet-ops-node-grid" aria-label="Fleet node operations">
          {visibleRows.map((row) => (
            <NodeCard key={row.key} row={row} activeTab={activeTab} />
          ))}
        </section>
      )}
    </main>
  );
}
