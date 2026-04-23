import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FaBookOpen,
  FaCheckCircle,
  FaCodeBranch,
  FaExclamationTriangle,
  FaKey,
  FaRedoAlt,
  FaSatelliteDish,
  FaSave,
  FaServer,
  FaWifi,
} from 'react-icons/fa';

import useGcsGitInfo from '../hooks/useGcsGitInfo';
import useGcsRuntimeStatus from '../hooks/useGcsRuntimeStatus';
import { applyGcsConfigResponse, applyRuntimeUpdateResponse, saveGcsConfigResponse } from '../services/gcsApiService';
import '../styles/RuntimeAdminPage.css';

function formatRepoAccessModeLabel(mode) {
  switch (mode) {
    case 'ssh_key':
      return 'SSH key';
    case 'https_token_file':
      return 'HTTPS token file';
    case 'https_public_or_read_only':
      return 'HTTPS public/read-only';
    default:
      return 'Custom / unknown';
  }
}

function StatusPill({ tone = 'neutral', children }) {
  return <span className={`runtime-admin-page__pill runtime-admin-page__pill--${tone}`}>{children}</span>;
}

function formatAuthHealthTone(status) {
  switch (status) {
    case 'healthy':
      return 'good';
    case 'warning':
      return 'warning';
    case 'error':
      return 'danger';
    default:
      return 'neutral';
  }
}

function formatServiceStatusTone(status) {
  switch (status) {
    case 'active':
      return 'good';
    case 'enabled':
      return 'warning';
    case 'absent':
      return 'neutral';
    default:
      return 'warning';
  }
}

function formatRepoSyncTone(status) {
  switch (status) {
    case 'up_to_date':
      return 'good';
    case 'ready_to_fast_forward':
    case 'no_tracking_branch':
      return 'warning';
    case 'blocked_dirty':
    case 'divergent':
    case 'local_ahead':
      return 'danger';
    default:
      return 'neutral';
  }
}

function formatRepoSyncLabel(status) {
  switch (status) {
    case 'up_to_date':
      return 'Up to date';
    case 'ready_to_fast_forward':
      return 'Update available';
    case 'blocked_dirty':
      return 'Dirty checkout';
    case 'divergent':
      return 'Diverged';
    case 'local_ahead':
      return 'Local ahead';
    case 'no_tracking_branch':
      return 'No upstream';
    default:
      return 'Repo sync unknown';
  }
}

function formatNoticeTone(status, fallback = 'neutral') {
  switch (status) {
    case 'scheduled':
    case 'success':
      return 'success';
    case 'already_scheduled':
    case 'no_restart_required':
    case 'warning':
      return 'warning';
    case 'error':
      return 'danger';
    default:
      return fallback;
  }
}

function buildNotice(payload, fallbackTone = 'neutral') {
  if (!payload) {
    return null;
  }

  return {
    tone: formatNoticeTone(payload.status, fallbackTone),
    message: payload.message || 'Operation completed.',
    warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
  };
}

function resolveLocalDashboardUrl(listen) {
  const normalized = String(listen || '').trim();
  if (!normalized || typeof window === 'undefined') {
    return null;
  }

  const parts = normalized.split(':');
  if (parts.length < 2) {
    return null;
  }

  const port = parts[parts.length - 1];
  if (!port) {
    return null;
  }

  const protocol = window.location?.protocol || 'http:';
  const hostname = window.location?.hostname || 'localhost';
  return `${protocol}//${hostname}:${port}/`;
}

function RuntimeAdminPage() {
  const runtime = useGcsRuntimeStatus();
  const gitInfo = useGcsGitInfo();

  const runtimeTone = runtime.mode === 'real' ? 'real' : runtime.mode === 'sitl' ? 'sitl' : 'neutral';
  const authHealthTone = formatAuthHealthTone(runtime.gitAuthHealth?.status);
  const repoSyncTone = formatRepoSyncTone(runtime.repoSyncStatus?.update_readiness);
  const docs = [
    { key: 'mds_init_setup', label: 'Bootstrap guide' },
    { key: 'fleet_sync_and_secrets', label: 'Fleet sync and secrets' },
    { key: 'mavlink_routing_setup', label: 'MAVLink routing' },
    { key: 'git_sync_feature', label: 'Git sync feature' },
  ].filter((entry) => runtime.docs?.[entry.key]);

  const [draftMode, setDraftMode] = useState('sitl');
  const [draftGitAutoPush, setDraftGitAutoPush] = useState(false);
  const [draftDirty, setDraftDirty] = useState(false);
  const [optimisticConfig, setOptimisticConfig] = useState(null);
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [updating, setUpdating] = useState(false);

  const effectiveConfiguredMode = optimisticConfig?.configuredMode || runtime.configuredMode || runtime.mode || 'sitl';
  const effectiveConfiguredModeLabel = optimisticConfig?.configuredModeLabel || runtime.configuredModeLabel || runtime.modeLabel;
  const effectiveConfiguredGitAutoPush = Object.prototype.hasOwnProperty.call(optimisticConfig || {}, 'configuredGitAutoPush')
    ? optimisticConfig.configuredGitAutoPush
    : runtime.configuredGitAutoPush;
  const effectiveRestartRequired = Object.prototype.hasOwnProperty.call(optimisticConfig || {}, 'restartRequired')
    ? optimisticConfig.restartRequired
    : runtime.restartRequired;

  useEffect(() => {
    if (!draftDirty) {
      setDraftMode(effectiveConfiguredMode || 'sitl');
      setDraftGitAutoPush(Boolean(effectiveConfiguredGitAutoPush));
    }
  }, [draftDirty, effectiveConfiguredGitAutoPush, effectiveConfiguredMode]);

  useEffect(() => {
    if (
      optimisticConfig
      && runtime.configuredMode === optimisticConfig.configuredMode
      && runtime.configuredGitAutoPush === optimisticConfig.configuredGitAutoPush
      && runtime.restartRequired === optimisticConfig.restartRequired
    ) {
      setOptimisticConfig(null);
    }
  }, [
    optimisticConfig,
    runtime.configuredGitAutoPush,
    runtime.configuredMode,
    runtime.restartRequired,
  ]);

  const hasDraftChanges = useMemo(
    () => draftMode !== effectiveConfiguredMode || Boolean(draftGitAutoPush) !== Boolean(effectiveConfiguredGitAutoPush),
    [draftGitAutoPush, draftMode, effectiveConfiguredGitAutoPush, effectiveConfiguredMode],
  );
  const sitlInstanceCount = Number.isInteger(runtime.sitlInstanceCount) ? runtime.sitlInstanceCount : null;
  const showSitlInventoryWarning = Boolean(sitlInstanceCount && effectiveConfiguredMode === 'real');
  const sitlInventoryWarningMessage = runtime.mode === 'sitl'
    ? `${sitlInstanceCount} local SITL instance(s) are still running. A REAL restart will fence their heartbeats, but it will not stop the containers automatically.`
    : `${sitlInstanceCount} local SITL instance(s) are still running on this host while the GCS runtime is in REAL mode. Their heartbeats are fenced, but you should reconcile or stop them explicitly.`;
  const localMavlinkDashboardUrl = resolveLocalDashboardUrl(runtime.mavlinkRuntime?.dashboard_listen);
  const localConnectivityDashboardUrl = resolveLocalDashboardUrl(runtime.connectivityRuntime?.dashboard_listen);
  const canRunControlledUpdate = Boolean(
    runtime.repoSyncStatus?.fast_forward_update_available && !effectiveRestartRequired
  );
  const controlledUpdateHint = effectiveRestartRequired
    ? 'Apply the pending runtime restart before attempting an in-place GCS update.'
    : 'Only runtime-safe fast-forward changes are eligible here. Frontend, launcher, tooling, and dependency updates still require the manual update path.';

  const setModeDraft = (nextMode) => {
    setDraftMode(nextMode);
    setDraftDirty(true);
  };

  const setGitAutoPushDraft = (nextValue) => {
    setDraftGitAutoPush(nextValue);
    setDraftDirty(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const response = await saveGcsConfigResponse({
        mode: draftMode,
        git_auto_push: draftGitAutoPush,
      });
      const payload = response?.data || {};
      const configuredMode = String(payload.configured_mode || draftMode || effectiveConfiguredMode).trim().toLowerCase() || 'sitl';
      const configuredGitAutoPush = Object.prototype.hasOwnProperty.call(payload, 'configured_git_auto_push')
        ? Boolean(payload.configured_git_auto_push)
        : Boolean(draftGitAutoPush);
      const restartRequired = Boolean(payload.restart_required);
      setOptimisticConfig({
        configuredMode,
        configuredModeLabel: configuredMode === 'real' ? 'REAL' : 'SITL',
        configuredGitAutoPush,
        restartRequired,
      });
      setDraftDirty(false);
      setNotice(buildNotice(payload, restartRequired ? 'warning' : 'success'));
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || 'Failed to persist host-local runtime settings.';
      setNotice({ tone: 'danger', message, warnings: [] });
    } finally {
      setSaving(false);
    }
  };

  const handleApply = async () => {
    setApplying(true);
    try {
      const response = await applyGcsConfigResponse();
      const payload = response?.data || {};
      setNotice(buildNotice(payload, payload.scheduled ? 'success' : 'warning'));
      if (payload.scheduled && typeof window !== 'undefined' && typeof window.setTimeout === 'function') {
        window.setTimeout(() => {
          if (typeof window.location?.reload === 'function') {
            window.location.reload();
          }
        }, Math.max(Number(payload.restart_delay_ms || 0), 2000) + 3000);
      }
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || 'Failed to schedule a clean GCS restart.';
      setNotice({ tone: 'danger', message, warnings: [] });
    } finally {
      setApplying(false);
    }
  };

  const handleRuntimeUpdate = async () => {
    setUpdating(true);
    try {
      const response = await applyRuntimeUpdateResponse();
      const payload = response?.data || {};
      setNotice(buildNotice(payload, payload.scheduled ? 'success' : 'warning'));
      if (payload.scheduled && typeof window !== 'undefined' && typeof window.setTimeout === 'function') {
        window.setTimeout(() => {
          if (typeof window.location?.reload === 'function') {
            window.location.reload();
          }
        }, Math.max(Number(payload.restart_delay_ms || 0), 2000) + 3000);
      }
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || 'Failed to schedule a controlled GCS update.';
      setNotice({ tone: 'danger', message, warnings: [] });
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="runtime-admin-page">
      <header className="runtime-admin-page__hero">
        <div>
          <span className="runtime-admin-page__eyebrow">System</span>
          <h1>Runtime Admin</h1>
          <p>
            Live runtime posture, host-local config authority, and restart-safe apply controls for SITL/REAL switching.
          </p>
        </div>
        <div className="runtime-admin-page__hero-pills">
          <StatusPill tone={runtimeTone}>{runtime.modeLabel}</StatusPill>
          <StatusPill tone={effectiveConfiguredMode === 'real' ? 'real' : 'sitl'}>
            Config {effectiveConfiguredModeLabel}
          </StatusPill>
          <StatusPill tone={runtime.gitAutoPush ? 'good' : 'warning'}>
            {runtime.gitAutoPush ? 'Auto-push on' : 'Auto-push off'}
          </StatusPill>
          <StatusPill>{formatRepoAccessModeLabel(runtime.repoAccessMode)}</StatusPill>
          <StatusPill tone={authHealthTone}>{runtime.gitAuthHealth?.status || 'unknown'} auth</StatusPill>
          {effectiveRestartRequired ? <StatusPill tone="warning">Restart required</StatusPill> : null}
        </div>
      </header>

      {runtime.error ? (
        <div className="runtime-admin-page__banner runtime-admin-page__banner--warning">
          Runtime status could not be loaded. The page is showing the last safe fallback only.
        </div>
      ) : null}

      {effectiveRestartRequired ? (
        <div className="runtime-admin-page__banner runtime-admin-page__banner--warning">
          Running GCS runtime and persisted host config do not match. Save any final changes, then apply a clean restart.
        </div>
      ) : null}

      {showSitlInventoryWarning ? (
        <div className="runtime-admin-page__banner runtime-admin-page__banner--warning">
          <div className="runtime-admin-page__banner-title">
            <FaExclamationTriangle />
            <span>{sitlInventoryWarningMessage}</span>
          </div>
          <div className="runtime-admin-page__banner-actions">
            <Link className="runtime-admin-page__doc-link" to="/sitl-control">
              Open SITL Control
            </Link>
          </div>
        </div>
      ) : null}

      {notice ? (
        <div className={`runtime-admin-page__banner runtime-admin-page__banner--${notice.tone || 'neutral'}`}>
          <div className="runtime-admin-page__banner-title">
            {notice.tone === 'danger' ? <FaExclamationTriangle /> : <FaCheckCircle />}
            <span>{notice.message}</span>
          </div>
          {notice.warnings?.length ? (
            <ul className="runtime-admin-page__issues runtime-admin-page__issues--inline">
              {notice.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <section className="runtime-admin-page__grid">
        <article className="runtime-admin-page__card runtime-admin-page__card--wide">
          <div className="runtime-admin-page__card-header">
            <FaRedoAlt />
            <div>
              <h2>Runtime Controls</h2>
              <p>Persist host-local mode and git auto-push, then relaunch the GCS cleanly through the canonical launcher.</p>
            </div>
          </div>

          <div className="runtime-admin-page__controls">
            <div className="runtime-admin-page__control-group">
              <span className="runtime-admin-page__control-label">Mode</span>
              <div className="runtime-admin-page__segmented">
                <button
                  type="button"
                  className={`runtime-admin-page__segmented-btn ${draftMode === 'real' ? 'is-active is-real' : ''}`}
                  onClick={() => setModeDraft('real')}
                  title="Persist REAL mode for the next clean GCS restart"
                  aria-label="Set runtime mode to REAL"
                  disabled={saving || applying}
                >
                  REAL
                </button>
                <button
                  type="button"
                  className={`runtime-admin-page__segmented-btn ${draftMode === 'sitl' ? 'is-active is-sitl' : ''}`}
                  onClick={() => setModeDraft('sitl')}
                  title="Persist SITL mode for the next clean GCS restart"
                  aria-label="Set runtime mode to SITL"
                  disabled={saving || applying}
                >
                  SITL
                </button>
              </div>
            </div>

            <div className="runtime-admin-page__control-group">
              <span className="runtime-admin-page__control-label">Git auto-push</span>
              <div className="runtime-admin-page__segmented">
                <button
                  type="button"
                  className={`runtime-admin-page__segmented-btn ${draftGitAutoPush ? 'is-active is-good' : ''}`}
                  onClick={() => setGitAutoPushDraft(true)}
                  title="Persist git auto-push enabled for this GCS host"
                  aria-label="Enable git auto-push"
                  disabled={saving || applying}
                >
                  ON
                </button>
                <button
                  type="button"
                  className={`runtime-admin-page__segmented-btn ${!draftGitAutoPush ? 'is-active is-warning' : ''}`}
                  onClick={() => setGitAutoPushDraft(false)}
                  title="Persist git auto-push disabled for this GCS host"
                  aria-label="Disable git auto-push"
                  disabled={saving || applying}
                >
                  OFF
                </button>
              </div>
            </div>

            <div className="runtime-admin-page__control-actions">
              <button
                type="button"
                className="runtime-admin-page__action-btn runtime-admin-page__action-btn--primary"
                onClick={handleSave}
                disabled={!hasDraftChanges || saving || applying}
                title="Persist host-local runtime settings to the GCS env file"
                aria-label="Save runtime settings"
              >
                <FaSave />
                <span>{saving ? 'Saving...' : 'Save host config'}</span>
              </button>
              <button
                type="button"
                className="runtime-admin-page__action-btn"
                onClick={handleApply}
                disabled={!effectiveRestartRequired || saving || applying}
                title="Schedule a clean GCS restart through linux_dashboard_start.sh"
                aria-label="Apply persisted runtime settings with restart"
              >
                <FaRedoAlt />
                <span>{applying ? 'Scheduling...' : 'Apply restart'}</span>
              </button>
            </div>
          </div>

          <dl className="runtime-admin-page__facts runtime-admin-page__facts--compact">
            <div>
              <dt>Running mode</dt>
              <dd>{runtime.modeLabel}</dd>
            </div>
            <div>
              <dt>Configured mode</dt>
              <dd>{effectiveConfiguredModeLabel}</dd>
            </div>
            <div>
              <dt>Running auto-push</dt>
              <dd>{runtime.gitAutoPush ? 'Enabled' : 'Disabled'}</dd>
            </div>
            <div>
              <dt>Configured auto-push</dt>
              <dd>{effectiveConfiguredGitAutoPush ? 'Enabled' : 'Disabled'}</dd>
            </div>
            <div>
              <dt>Local SITL containers</dt>
              <dd>{sitlInstanceCount ?? 'Unknown'}</dd>
            </div>
          </dl>
        </article>

        <article className="runtime-admin-page__card">
          <div className="runtime-admin-page__card-header">
            <FaServer />
            <div>
              <h2>GCS Runtime</h2>
              <p>Canonical mode and local host runtime inputs.</p>
            </div>
          </div>
          <dl className="runtime-admin-page__facts">
            <div>
              <dt>Mode</dt>
              <dd>{runtime.modeLabel}</dd>
            </div>
            <div>
              <dt>Mode source</dt>
              <dd>{runtime.modeSource || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Repo</dt>
              <dd>{gitInfo.repo}</dd>
            </div>
            <div>
              <dt>Branch</dt>
              <dd>{runtime.repoBranch || gitInfo.branch}</dd>
            </div>
            <div>
              <dt>Commit</dt>
              <dd>{gitInfo.commit || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Repo sync</dt>
              <dd>
                <StatusPill tone={repoSyncTone}>
                  {formatRepoSyncLabel(runtime.repoSyncStatus?.update_readiness)}
                </StatusPill>
              </dd>
            </div>
            <div>
              <dt>Tracking</dt>
              <dd>{runtime.repoSyncStatus?.tracking_branch || 'Not configured'}</dd>
            </div>
            <div>
              <dt>Sync summary</dt>
              <dd>{runtime.repoSyncStatus?.update_summary || 'Not reported'}</dd>
            </div>
            <div>
              <dt>Install dir</dt>
              <dd>{runtime.installDir || 'Not reported'}</dd>
            </div>
            <div>
              <dt>System config</dt>
              <dd>{runtime.gcsConfigPath || 'Not reported'}</dd>
            </div>
          </dl>
          <div className="runtime-admin-page__control-actions runtime-admin-page__control-actions--inline">
            <button
              type="button"
              className="runtime-admin-page__action-btn"
              onClick={handleRuntimeUpdate}
              disabled={!canRunControlledUpdate || saving || applying || updating}
              title={controlledUpdateHint}
              aria-label="Run controlled GCS update"
            >
              <FaRedoAlt />
              <span>{updating ? 'Scheduling...' : 'Update GCS'}</span>
            </button>
          </div>
          <p className="runtime-admin-page__empty">{controlledUpdateHint}</p>
        </article>

        <article className="runtime-admin-page__card">
          <div className="runtime-admin-page__card-header">
            <FaCodeBranch />
            <div>
              <h2>Git Access</h2>
              <p>Operator-safe visibility into the current repository auth posture.</p>
            </div>
          </div>
          <dl className="runtime-admin-page__facts">
            <div>
              <dt>Access mode</dt>
              <dd>{formatRepoAccessModeLabel(runtime.repoAccessMode)}</dd>
            </div>
            <div>
              <dt>Auth health</dt>
              <dd>{runtime.gitAuthHealth?.summary || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Auto-push</dt>
              <dd>{runtime.gitAutoPush ? 'Enabled' : 'Disabled'}</dd>
            </div>
            <div>
              <dt>Token file</dt>
              <dd>{runtime.raw?.git_auth_token_file || 'Not configured'}</dd>
            </div>
            <div>
              <dt>Token readable</dt>
              <dd>{runtime.raw?.git_auth_token_file_readable ? 'Yes' : 'No'}</dd>
            </div>
            <div>
              <dt>SSH key</dt>
              <dd>{runtime.raw?.git_ssh_key_file || 'Not configured'}</dd>
            </div>
            <div>
              <dt>SSH readable</dt>
              <dd>{runtime.raw?.git_ssh_key_file_readable ? 'Yes' : 'No'}</dd>
            </div>
          </dl>
          {runtime.gitAuthHealth?.issues?.length ? (
            <ul className="runtime-admin-page__issues">
              {runtime.gitAuthHealth.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          ) : null}
        </article>

        <article className="runtime-admin-page__card">
          <div className="runtime-admin-page__card-header">
            <FaSatelliteDish />
            <div>
              <h2>Fleet Defaults</h2>
              <p>Git-tracked defaults that new nodes inherit during bootstrap.</p>
            </div>
          </div>
          <dl className="runtime-admin-page__facts">
            <div>
              <dt>Profile</dt>
              <dd>{runtime.fleetDefaults?.profile_id || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Profile source</dt>
              <dd>{runtime.fleetDefaults?.profile_source || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Connectivity backend</dt>
              <dd>{runtime.fleetDefaults?.connectivity_backend || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Smart Wi-Fi mode</dt>
              <dd>{runtime.fleetDefaults?.smart_wifi_manager_mode || 'Unknown'}</dd>
            </div>
            <div>
              <dt>MAVLink mode</dt>
              <dd>{runtime.fleetDefaults?.mavlink_management_mode || 'Unknown'}</dd>
            </div>
            <div>
              <dt>MAVLink ref</dt>
              <dd>{runtime.fleetDefaults?.mavlink_anywhere_ref || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Smart Wi-Fi ref</dt>
              <dd>{runtime.fleetDefaults?.smart_wifi_manager_ref || 'Unknown'}</dd>
            </div>
          </dl>
        </article>

        <article className="runtime-admin-page__card">
          <div className="runtime-admin-page__card-header">
            <FaSatelliteDish />
            <div>
              <h2>MAVLink Runtime</h2>
              <p>Live managed mavlink-anywhere posture on this GCS host.</p>
            </div>
          </div>
          <dl className="runtime-admin-page__facts">
            <div>
              <dt>Management mode</dt>
              <dd>{runtime.mavlinkRuntime?.management_mode || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Ref</dt>
              <dd>{runtime.mavlinkRuntime?.ref || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Install dir</dt>
              <dd>{runtime.mavlinkRuntime?.install_dir || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Checkout present</dt>
              <dd>{runtime.mavlinkRuntime?.runtime_present ? 'Yes' : 'No'}</dd>
            </div>
            <div>
              <dt>Router service</dt>
              <dd>{runtime.mavlinkRuntime?.router_service_status || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Dashboard service</dt>
              <dd>{runtime.mavlinkRuntime?.dashboard_service_status || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Dashboard listen</dt>
              <dd>{runtime.mavlinkRuntime?.dashboard_listen || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Router binary</dt>
              <dd>{runtime.mavlinkRuntime?.router_binary_present ? 'Present' : 'Missing'}</dd>
            </div>
          </dl>
          {runtime.mavlinkRuntime?.repo_web_url ? (
            <div className="runtime-admin-page__link-row">
              <a
                className="runtime-admin-page__doc-link"
                href={runtime.mavlinkRuntime.repo_web_url}
                target="_blank"
                rel="noreferrer"
              >
                Open mavlink-anywhere repo
              </a>
              <StatusPill tone={formatServiceStatusTone(runtime.mavlinkRuntime?.router_service_status)}>
                Router {runtime.mavlinkRuntime?.router_service_status || 'unknown'}
              </StatusPill>
              <StatusPill tone={formatServiceStatusTone(runtime.mavlinkRuntime?.dashboard_service_status)}>
                Dashboard {runtime.mavlinkRuntime?.dashboard_service_status || 'unknown'}
              </StatusPill>
              {localMavlinkDashboardUrl ? (
                <a
                  className="runtime-admin-page__doc-link"
                  href={localMavlinkDashboardUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open local dashboard
                </a>
              ) : null}
            </div>
          ) : null}
          <p className="runtime-admin-page__empty">
            Runtime Admin only links GCS-local managed dashboards here. Node-local sidecar dashboards are not centrally proxied yet.
          </p>
        </article>

        <article className="runtime-admin-page__card">
          <div className="runtime-admin-page__card-header">
            <FaWifi />
            <div>
              <h2>Connectivity Runtime</h2>
              <p>Live Smart Wi-Fi Manager posture on this GCS host.</p>
            </div>
          </div>
          <dl className="runtime-admin-page__facts">
            <div>
              <dt>Backend</dt>
              <dd>{runtime.connectivityRuntime?.backend || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Mode</dt>
              <dd>{runtime.connectivityRuntime?.mode || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Ref</dt>
              <dd>{runtime.connectivityRuntime?.ref || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Install dir</dt>
              <dd>{runtime.connectivityRuntime?.install_dir || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Profile path</dt>
              <dd>{runtime.connectivityRuntime?.profile_path || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Profile present</dt>
              <dd>{runtime.connectivityRuntime?.profile_present ? 'Yes' : 'No'}</dd>
            </div>
            <div>
              <dt>Service status</dt>
              <dd>{runtime.connectivityRuntime?.service_status || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Dashboard listen</dt>
              <dd>{runtime.connectivityRuntime?.dashboard_listen || 'Unknown'}</dd>
            </div>
          </dl>
          {runtime.connectivityRuntime?.repo_web_url ? (
            <div className="runtime-admin-page__link-row">
              <a
                className="runtime-admin-page__doc-link"
                href={runtime.connectivityRuntime.repo_web_url}
                target="_blank"
                rel="noreferrer"
              >
                Open Smart Wi-Fi repo
              </a>
              <StatusPill tone={formatServiceStatusTone(runtime.connectivityRuntime?.service_status)}>
                Service {runtime.connectivityRuntime?.service_status || 'unknown'}
              </StatusPill>
              {localConnectivityDashboardUrl ? (
                <a
                  className="runtime-admin-page__doc-link"
                  href={localConnectivityDashboardUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open local dashboard
                </a>
              ) : null}
            </div>
          ) : null}
          <p className="runtime-admin-page__empty">
            Use fleet bootstrap defaults and node-local runtime env for node-side overrides; this panel is the GCS-local inspection surface only.
          </p>
        </article>

        <article className="runtime-admin-page__card runtime-admin-page__card--wide">
          <div className="runtime-admin-page__card-header">
            <FaBookOpen />
            <div>
              <h2>Operator Guides</h2>
              <p>Single-source docs for humans, agents, and headless workflows.</p>
            </div>
          </div>
          {docs.length ? (
            <div className="runtime-admin-page__doc-grid">
              {docs.map((doc) => (
                <a
                  key={doc.key}
                  className="runtime-admin-page__doc-link"
                  href={runtime.docs[doc.key]}
                  target="_blank"
                  rel="noreferrer"
                >
                  {doc.label}
                </a>
              ))}
            </div>
          ) : (
            <p className="runtime-admin-page__empty">
              Git-backed doc links are unavailable for the current remote URL.
            </p>
          )}
        </article>

        <article className="runtime-admin-page__card runtime-admin-page__card--wide">
          <div className="runtime-admin-page__card-header">
            <FaKey />
            <div>
              <h2>Operational Notes</h2>
              <p>Current safe posture for mutation and recovery actions.</p>
            </div>
          </div>
          <ul className="runtime-admin-page__notes">
            <li>Mode changes are host-local GCS mutations. Save them first, then apply through the canonical launcher restart.</li>
            <li>Mode-tagged heartbeats are fenced at intake so stale SITL or REAL nodes do not contaminate the other runtime after restart.</li>
            <li>Local SITL containers are not stopped automatically when switching the GCS into REAL mode; reconcile them explicitly through SITL Control.</li>
            <li>Fleet defaults shown here are git-tracked intent for future bootstraps; node-local overrides still live in each host runtime env.</li>
          </ul>
        </article>
      </section>
    </div>
  );
}

export default RuntimeAdminPage;
