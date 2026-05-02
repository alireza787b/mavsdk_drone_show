import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FaBookOpen,
  FaCheckCircle,
  FaCodeBranch,
  FaExclamationTriangle,
  FaKey,
  FaNetworkWired,
  FaPlus,
  FaRedoAlt,
  FaSatelliteDish,
  FaSave,
  FaServer,
  FaSignOutAlt,
  FaUserEdit,
  FaUserShield,
} from 'react-icons/fa';

import {
  OperatorNotice,
  PageShell,
  StatusBadge,
} from '../components/ui';
import useGcsGitInfo from '../hooks/useGcsGitInfo';
import useGcsRuntimeStatus from '../hooks/useGcsRuntimeStatus';
import { useAuth } from '../contexts/AuthContext';
import {
  applyGcsConfigResponse,
  applyRuntimeUpdateResponse,
  createAuthTokenResponse,
  createAuthUserResponse,
  listAuthTokensResponse,
  listAuthUsersResponse,
  fetchGcsResource,
  GCS_ROUTE_KEYS,
  revokeAuthTokenResponse,
  saveGcsConfigResponse,
  updateAuthUserResponse,
} from '../services/gcsApiService';
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
  const primitiveTone = tone === 'good' ? 'success' : ['success', 'warning', 'danger', 'muted', 'info'].includes(tone) ? tone : 'neutral';
  return (
    <StatusBadge tone={primitiveTone} className={`runtime-admin-page__pill runtime-admin-page__pill--${tone}`}>
      {children}
    </StatusBadge>
  );
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

function RuntimeAdminPage({ runtimeOverride = null, gitInfoOverride = null }) {
  const runtimeState = useGcsRuntimeStatus() || {};
  const gitInfoState = useGcsGitInfo() || {};
  const runtime = runtimeOverride || runtimeState;
  const gitInfo = gitInfoOverride || gitInfoState;
  const auth = useAuth();

  const runtimeTone = runtime.mode === 'real' ? 'real' : runtime.mode === 'sitl' ? 'sitl' : 'neutral';
  const authHealthTone = formatAuthHealthTone(runtime.gitAuthHealth?.status);
  const repoSyncTone = formatRepoSyncTone(runtime.repoSyncStatus?.update_readiness);
  const docs = [
    { key: 'mds_init_setup', label: 'Bootstrap guide' },
    { key: 'gcs_auth', label: 'Auth guide' },
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
  const [restartWatch, setRestartWatch] = useState(null);
  const [authUsers, setAuthUsers] = useState([]);
  const [authTokens, setAuthTokens] = useState([]);
  const [authNotice, setAuthNotice] = useState(null);
  const [userDialog, setUserDialog] = useState(null);
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [userDraft, setUserDraft] = useState({ username: '', password: '', role: 'operator', disabled: false });
  const [tokenDraft, setTokenDraft] = useState({ name: '', scopes: 'operator', ttl_hours: 4 });
  const [revealedToken, setRevealedToken] = useState(null);

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

  const refreshSecurityLists = useCallback(async () => {
    if (!auth.dashboardAuthEnabled || auth.role !== 'admin') {
      setAuthUsers([]);
      setAuthTokens([]);
      return;
    }
    const [usersResponse, tokensResponse] = await Promise.all([
      listAuthUsersResponse(),
      listAuthTokensResponse(),
    ]);
    setAuthUsers(usersResponse?.data?.users || []);
    setAuthTokens(tokensResponse?.data?.tokens || []);
  }, [auth.dashboardAuthEnabled, auth.role]);

  useEffect(() => {
    refreshSecurityLists().catch(() => {
      setAuthNotice({ tone: 'warning', message: 'Security lists unavailable. Check auth role or backend logs.' });
    });
  }, [refreshSecurityLists]);

  const hasDraftChanges = useMemo(
    () => draftMode !== effectiveConfiguredMode || Boolean(draftGitAutoPush) !== Boolean(effectiveConfiguredGitAutoPush),
    [draftGitAutoPush, draftMode, effectiveConfiguredGitAutoPush, effectiveConfiguredMode],
  );
  const sitlInstanceCount = Number.isInteger(runtime.sitlInstanceCount) ? runtime.sitlInstanceCount : null;
  const showSitlInventoryWarning = Boolean(sitlInstanceCount && effectiveConfiguredMode === 'real');
  const sitlInventoryWarningMessage = runtime.mode === 'sitl'
    ? `${sitlInstanceCount} local SITL instance(s) are still running. A REAL restart will fence their heartbeats, but it will not stop the containers automatically.`
    : `${sitlInstanceCount} local SITL instance(s) are still running on this host while the GCS runtime is in REAL mode. Their heartbeats are fenced, but you should reconcile or stop them explicitly.`;
  const canRunControlledUpdate = Boolean(
    runtime.repoSyncStatus?.fast_forward_update_available && !effectiveRestartRequired
  );
  const controlledUpdateHint = effectiveRestartRequired
    ? 'Apply the pending runtime restart before attempting an in-place GCS update.'
    : 'Only runtime-safe fast-forward changes are eligible here. Frontend, launcher, tooling, and dependency updates still require the manual update path.';
  const tokenConfigured = Boolean(runtime.raw?.git_auth_token_file_readable || runtime.raw?.git_auth_token_file);
  const sshKeyConfigured = Boolean(runtime.raw?.git_ssh_key_file_readable || runtime.raw?.git_ssh_key_file);
  const secretPosture = runtime.repoAccessMode === 'ssh_key'
    ? (sshKeyConfigured ? 'SSH key configured' : 'SSH key missing')
    : runtime.repoAccessMode === 'https_token_file'
      ? (tokenConfigured ? 'Token file configured' : 'Token file missing')
      : 'No private secret required';
  const gcsRepoRole = runtime.gitAutoPush || effectiveConfiguredGitAutoPush ? 'GCS writer' : 'GCS read-only/demo';
  const mavlinkHostSummary = runtime.mavlinkRuntime?.runtime_present
    ? `GCS-local ${runtime.mavlinkRuntime?.management_mode || 'managed'} runtime; router ${runtime.mavlinkRuntime?.router_service_status || 'unknown'}`
    : 'Not installed on this GCS host';
  const connectivityHostSummary = runtime.connectivityRuntime?.install_dir_present || runtime.connectivityRuntime?.service_status === 'active'
    ? `GCS-local ${runtime.connectivityRuntime?.backend || 'connectivity'} runtime; service ${runtime.connectivityRuntime?.service_status || 'unknown'}`
    : 'Not installed on this GCS host';

  const setModeDraft = (nextMode) => {
    setDraftMode(nextMode);
    setDraftDirty(true);
  };

  const setGitAutoPushDraft = (nextValue) => {
    setDraftGitAutoPush(nextValue);
    setDraftDirty(true);
  };

  const persistRuntimeSettings = async () => {
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
    return { payload, restartRequired, configuredMode };
  };

  const beginRestartWatch = (payload = {}, targetMode = effectiveConfiguredMode) => {
    if (!payload.scheduled || typeof window === 'undefined') {
      return;
    }

    const startedAt = Date.now();
    const initialDelayMs = Math.max(Number(payload.restart_delay_ms || 0), 2000) + 2500;
    const normalizedTargetMode = String(targetMode || effectiveConfiguredMode || '').trim().toLowerCase();
    setNotice(null);
    setRestartWatch({
      targetMode: normalizedTargetMode,
      message: payload.message || 'GCS restart scheduled. Waiting for the launcher to return healthy.',
    });

    const poll = async () => {
      try {
        const response = await fetchGcsResource(GCS_ROUTE_KEYS.systemRuntimeStatus, { timeout: 4500 });
        const runningMode = String(response?.data?.mode || '').trim().toLowerCase();
        if (!normalizedTargetMode || runningMode === normalizedTargetMode) {
          if (typeof window.location?.reload === 'function') {
            window.location.reload();
          }
          return;
        }
      } catch (error) {
        // Expected while the launcher recycles the API process.
      }

      if (Date.now() - startedAt < 120000) {
        window.setTimeout(poll, 2500);
        return;
      }

      setRestartWatch((current) => current ? {
        ...current,
        message: 'GCS restart is taking longer than expected. Keep this page open or refresh after backend health returns.',
      } : current);
    };

    window.setTimeout(poll, initialDelayMs);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const { payload, restartRequired } = await persistRuntimeSettings();
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
      if (hasDraftChanges) {
        const { payload, restartRequired } = await persistRuntimeSettings();
        if (!restartRequired) {
          setNotice(buildNotice(payload, 'success'));
          return;
        }
      }

      const response = await applyGcsConfigResponse();
      const payload = response?.data || {};
      setNotice(buildNotice(payload, payload.scheduled ? 'success' : 'warning'));
      beginRestartWatch(payload, draftMode || effectiveConfiguredMode);
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
      beginRestartWatch(payload, effectiveConfiguredMode);
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || 'Failed to schedule a controlled GCS update.';
      setNotice({ tone: 'danger', message, warnings: [] });
    } finally {
      setUpdating(false);
    }
  };

  const openUserDialog = (user = null) => {
    setAuthNotice(null);
    setUserDialog(user ? { mode: 'edit', username: user.username } : { mode: 'create', username: '' });
    setUserDraft({
      username: user?.username || '',
      password: '',
      role: user?.role || 'operator',
      disabled: Boolean(user?.disabled),
    });
  };

  const closeUserDialog = () => {
    setUserDialog(null);
    setUserDraft({ username: '', password: '', role: 'operator', disabled: false });
  };

  const handleSaveUser = async (event) => {
    event.preventDefault();
    setAuthNotice(null);
    try {
      if (userDialog?.mode === 'edit') {
        await updateAuthUserResponse(userDialog.username, {
          role: userDraft.role,
          disabled: Boolean(userDraft.disabled),
        });
        if (userDraft.password) {
          await updateAuthUserResponse(userDialog.username, { password: userDraft.password });
        }
      } else {
        await createAuthUserResponse({
          username: userDraft.username,
          password: userDraft.password,
          role: userDraft.role,
          disabled: Boolean(userDraft.disabled),
        });
      }
      closeUserDialog();
      await refreshSecurityLists();
      setAuthNotice({ tone: 'success', message: 'User saved.' });
    } catch (error) {
      setAuthNotice({ tone: 'danger', message: error?.response?.data?.detail || error?.message || 'Failed to save user.' });
    }
  };

  const handleDisableUser = async (username, disabled) => {
    setAuthNotice(null);
    try {
      await updateAuthUserResponse(username, { disabled });
      await refreshSecurityLists();
      setAuthNotice({ tone: 'success', message: disabled ? 'User disabled.' : 'User enabled.' });
    } catch (error) {
      setAuthNotice({ tone: 'danger', message: error?.response?.data?.detail || error?.message || 'Failed to update user.' });
    }
  };

  const handleCreateToken = async (event) => {
    event.preventDefault();
    setAuthNotice(null);
    setRevealedToken(null);
    try {
      const scopes = String(tokenDraft.scopes || '')
        .split(',')
        .map((scope) => scope.trim())
        .filter(Boolean);
      const response = await createAuthTokenResponse({
        name: tokenDraft.name,
        scopes,
        ttl_hours: Number(tokenDraft.ttl_hours) || undefined,
      });
      setRevealedToken(response?.data?.token || null);
      setTokenDraft({ name: '', scopes: 'operator', ttl_hours: 4 });
      setTokenDialogOpen(false);
      await refreshSecurityLists();
      setAuthNotice({ tone: 'success', message: 'Token created. Copy it now; it will not be shown again.' });
    } catch (error) {
      setAuthNotice({ tone: 'danger', message: error?.response?.data?.detail || error?.message || 'Failed to create token.' });
    }
  };

  const handleRevokeToken = async (tokenId) => {
    setAuthNotice(null);
    try {
      await revokeAuthTokenResponse(tokenId);
      await refreshSecurityLists();
      setAuthNotice({ tone: 'success', message: 'Token revoked.' });
    } catch (error) {
      setAuthNotice({ tone: 'danger', message: error?.response?.data?.detail || error?.message || 'Failed to revoke token.' });
    }
  };

  return (
    <PageShell
      className="runtime-admin-page"
      eyebrow="System"
      title="GCS Runtime"
      subtitle="Host-local mode, update, and restart. Drone-node controls live in Fleet Ops."
      icon={<FaServer />}
      docsRoute="/runtime-admin"
      docsOptions={{
        repoUrl: runtime.repoSyncStatus?.remote_url || '',
        branch: runtime.repoBranch || gitInfo.branch || runtime.repoSyncStatus?.branch || '',
      }}
      actions={(
        <Link className="runtime-admin-page__scope-link" to="/fleet-ops" aria-label="Open Fleet Ops">
          <FaNetworkWired aria-hidden="true" />
          <span>Fleet Ops</span>
        </Link>
      )}
      status={(
        <div className="runtime-admin-page__status-pills">
          <StatusPill tone="info">GCS host</StatusPill>
          <StatusPill tone={runtimeTone}>{runtime.modeLabel}</StatusPill>
          <StatusPill tone={effectiveConfiguredMode === 'real' ? 'real' : 'sitl'}>
            Config {effectiveConfiguredModeLabel}
          </StatusPill>
          <StatusPill tone={runtime.gitAutoPush ? 'good' : 'warning'}>
            {runtime.gitAutoPush ? 'Auto-push on' : 'Auto-push off'}
          </StatusPill>
          <StatusPill>{formatRepoAccessModeLabel(runtime.repoAccessMode)}</StatusPill>
          <StatusPill tone={authHealthTone}>{runtime.gitAuthHealth?.status || 'unknown'} auth</StatusPill>
          {auth.dashboardAuthEnabled ? <StatusPill tone="good">Login on</StatusPill> : <StatusPill>Login off</StatusPill>}
          {effectiveRestartRequired ? <StatusPill tone="warning">Restart required</StatusPill> : null}
        </div>
      )}
    >

      {runtime.error ? (
        <OperatorNotice tone="warning" title="Runtime status unavailable">
          Showing the last safe fallback only.
        </OperatorNotice>
      ) : null}

      {effectiveRestartRequired ? (
        <OperatorNotice tone="warning" title="Restart required">
          Running GCS runtime and persisted host config do not match. Save final changes, then apply a clean restart.
        </OperatorNotice>
      ) : null}

      {restartWatch ? (
        <OperatorNotice tone="info" title="GCS reconnecting" icon={<FaRedoAlt />}>
          {restartWatch.message} Target mode: {restartWatch.targetMode?.toUpperCase() || 'current'}.
        </OperatorNotice>
      ) : null}

      {showSitlInventoryWarning ? (
        <OperatorNotice
          tone="warning"
          title="SITL containers still running"
          icon={<FaExclamationTriangle />}
          action={(
            <Link className="runtime-admin-page__doc-link" to="/sitl-control">
              Open SITL Control
            </Link>
          )}
        >
          {sitlInventoryWarningMessage}
        </OperatorNotice>
      ) : null}

      {notice ? (
        <OperatorNotice
          tone={notice.tone || 'neutral'}
          title={notice.tone === 'danger' ? 'Runtime action failed' : 'Runtime action'}
          icon={notice.tone === 'danger' ? <FaExclamationTriangle /> : <FaCheckCircle />}
        >
          {notice.message}
          {notice.warnings?.length ? (
            <ul className="runtime-admin-page__issues runtime-admin-page__issues--inline">
              {notice.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </OperatorNotice>
      ) : null}

      <section className="runtime-admin-page__grid">
        <article className="runtime-admin-page__card runtime-admin-page__card--wide">
          <div className="runtime-admin-page__card-header">
            <FaUserShield />
            <div>
              <h2>Security</h2>
              <p>Operator login, roles, and API tokens. SSH CLI remains the recovery path.</p>
            </div>
          </div>

          <div className="runtime-admin-page__security-summary">
            <StatusPill tone={auth.dashboardAuthEnabled ? 'good' : 'neutral'}>
              Dashboard {auth.dashboardAuthEnabled ? 'locked' : 'open'}
            </StatusPill>
            <StatusPill tone={auth.apiAuthEnabled ? 'warning' : 'neutral'}>
              API tokens {auth.apiAuthEnabled ? 'required' : 'optional'}
            </StatusPill>
            <StatusPill>{auth.role || 'open'}</StatusPill>
            {auth.user ? (
              <button type="button" className="runtime-admin-page__icon-action" onClick={auth.logout} aria-label="Log out">
                <FaSignOutAlt aria-hidden="true" />
                <span>Logout</span>
              </button>
            ) : null}
          </div>

          {authNotice ? (
            <OperatorNotice tone={authNotice.tone || 'neutral'} title="Security action">
              {authNotice.message}
            </OperatorNotice>
          ) : null}

          {!auth.dashboardAuthEnabled ? (
            <p className="runtime-admin-page__empty">
              Dashboard auth is disabled. Enable it through GCS bootstrap or the recovery CLI, then restart GCS.
            </p>
          ) : auth.role !== 'admin' ? (
            <p className="runtime-admin-page__empty">
              Signed in as {auth.role || 'operator'}. Admin role is required to manage users and tokens.
            </p>
          ) : (
            <div className="runtime-admin-page__security-grid">
              <section className="runtime-admin-page__security-panel">
                <div className="runtime-admin-page__security-panel-header">
                  <h3>Users</h3>
                  <button type="button" className="runtime-admin-page__action-btn" onClick={() => openUserDialog()}>
                    <FaPlus aria-hidden="true" />
                    <span>Add</span>
                  </button>
                </div>
                <div className="runtime-admin-page__mini-table">
                  {authUsers.map((user) => (
                    <div key={user.username} className="runtime-admin-page__mini-row">
                      <span>{user.username}</span>
                      <StatusPill tone={user.disabled ? 'warning' : 'neutral'}>{user.disabled ? 'disabled' : user.role}</StatusPill>
                      <span className="runtime-admin-page__mini-actions">
                        <button type="button" onClick={() => openUserDialog(user)} aria-label={`Edit ${user.username}`}>
                          <FaUserEdit aria-hidden="true" />
                          <span>Edit</span>
                        </button>
                        <button type="button" onClick={() => handleDisableUser(user.username, !user.disabled)}>
                          {user.disabled ? 'Enable' : 'Disable'}
                        </button>
                      </span>
                    </div>
                  ))}
                  {!authUsers.length ? <p className="runtime-admin-page__empty">No users reported.</p> : null}
                </div>
              </section>

              <section className="runtime-admin-page__security-panel">
                <div className="runtime-admin-page__security-panel-header">
                  <h3>Tokens</h3>
                  <button type="button" className="runtime-admin-page__action-btn" onClick={() => setTokenDialogOpen(true)}>
                    <FaPlus aria-hidden="true" />
                    <span>Create</span>
                  </button>
                </div>
                {revealedToken?.token ? (
                  <div className="runtime-admin-page__token-reveal">
                    <span>Shown once</span>
                    <code>{revealedToken.token}</code>
                  </div>
                ) : null}
                <div className="runtime-admin-page__mini-table">
                  {authTokens.map((token) => (
                    <div key={token.id} className="runtime-admin-page__mini-row">
                      <span>{token.name || token.id}</span>
                      <StatusPill tone={token.revoked ? 'danger' : 'good'}>
                        {token.revoked ? 'revoked' : 'active'}
                      </StatusPill>
                      <button type="button" disabled={token.revoked} onClick={() => handleRevokeToken(token.id)}>
                        Revoke
                      </button>
                    </div>
                  ))}
                  {!authTokens.length ? <p className="runtime-admin-page__empty">No API tokens reported.</p> : null}
                </div>
              </section>
            </div>
          )}
        </article>

        <article className="runtime-admin-page__card runtime-admin-page__card--wide">
          <div className="runtime-admin-page__card-header">
            <FaRedoAlt />
            <div>
              <h2>Runtime Controls</h2>
              <p>Persist host mode and relaunch through the canonical GCS launcher.</p>
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
                  aria-label="Set runtime mode to REAL"
                  disabled={saving || applying || Boolean(restartWatch)}
                >
                  REAL
                </button>
                <button
                  type="button"
                  className={`runtime-admin-page__segmented-btn ${draftMode === 'sitl' ? 'is-active is-sitl' : ''}`}
                  onClick={() => setModeDraft('sitl')}
                  aria-label="Set runtime mode to SITL"
                  disabled={saving || applying || Boolean(restartWatch)}
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
                  aria-label="Enable git auto-push"
                  disabled={saving || applying || Boolean(restartWatch)}
                >
                  ON
                </button>
                <button
                  type="button"
                  className={`runtime-admin-page__segmented-btn ${!draftGitAutoPush ? 'is-active is-warning' : ''}`}
                  onClick={() => setGitAutoPushDraft(false)}
                  aria-label="Disable git auto-push"
                  disabled={saving || applying || Boolean(restartWatch)}
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
                disabled={!hasDraftChanges || saving || applying || Boolean(restartWatch)}
                aria-label="Save runtime settings"
              >
                <FaSave />
                <span>{saving ? 'Saving...' : 'Save host config'}</span>
              </button>
              <button
                type="button"
                className="runtime-admin-page__action-btn"
                onClick={handleApply}
                disabled={(!effectiveRestartRequired && !hasDraftChanges) || saving || applying || Boolean(restartWatch)}
                aria-label={hasDraftChanges ? 'Apply runtime changes and restart GCS' : 'Apply persisted runtime settings with restart'}
              >
                <FaRedoAlt />
                <span>{applying ? 'Scheduling...' : hasDraftChanges ? 'Save + restart' : 'Apply restart'}</span>
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
              <p>Canonical mode and host runtime inputs.</p>
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
              <p>GCS-host repository role and auth health without exposing secret paths or values.</p>
            </div>
          </div>
          <dl className="runtime-admin-page__facts">
            <div>
              <dt>Host role</dt>
              <dd>{gcsRepoRole}</dd>
            </div>
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
              <dt>Secret posture</dt>
              <dd>{secretPosture}</dd>
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

        <article className="runtime-admin-page__card runtime-admin-page__card--wide">
          <div className="runtime-admin-page__card-header">
            <FaSatelliteDish />
            <div>
              <h2>Host Capabilities</h2>
              <p>Local host capability summary. Node compliance belongs in Fleet Ops.</p>
            </div>
          </div>
          <div className="runtime-admin-page__capability-grid">
            <div className="runtime-admin-page__capability">
              <span className="runtime-admin-page__capability-label">SITL Inventory</span>
              <StatusPill tone={sitlInstanceCount ? 'warning' : 'good'}>
                {sitlInstanceCount ?? 'Unknown'} local
              </StatusPill>
              <p>Local containers are visible here only as host runtime risk; lifecycle controls stay in SITL Control.</p>
            </div>
            <div className="runtime-admin-page__capability">
              <span className="runtime-admin-page__capability-label">Fleet Profile</span>
              <StatusPill>{runtime.fleetDefaults?.profile_id || 'Unknown'}</StatusPill>
              <p>{runtime.fleetDefaults?.profile_source || 'Profile source not reported'}</p>
            </div>
            <div className="runtime-admin-page__capability">
              <span className="runtime-admin-page__capability-label">MAVLink Policy</span>
              <StatusPill>{runtime.fleetDefaults?.mavlink_management_mode || 'Unknown'}</StatusPill>
              <p>Fleet default ref {runtime.fleetDefaults?.mavlink_anywhere_ref || 'unknown'}; local host {mavlinkHostSummary}.</p>
            </div>
            <div className="runtime-admin-page__capability">
              <span className="runtime-admin-page__capability-label">Connectivity Policy</span>
              <StatusPill>{runtime.fleetDefaults?.connectivity_backend || 'Unknown'}</StatusPill>
              <p>Fleet default ref {runtime.fleetDefaults?.smart_wifi_manager_ref || 'unknown'}; local host {connectivityHostSummary}.</p>
            </div>
          </div>
          <p className="runtime-admin-page__empty">
            Use Fleet Ops for drone MAVLink, Smart Wi-Fi, git auth, profile drift, and sync actions.
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
            <li>Local SITL containers are not stopped automatically when switching the GCS into REAL mode; remove them explicitly through SITL Control, which stays available in cleanup-only mode.</li>
            <li>Fleet defaults shown here are read-only host context. Use Fleet Ops for node actions and profile drift.</li>
          </ul>
        </article>
      </section>

      {userDialog ? (
        <div
          className="runtime-admin-page__dialog"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeUserDialog();
            }
          }}
        >
          <form className="runtime-admin-page__dialog-panel" role="dialog" aria-modal="true" aria-label="User security editor" onSubmit={handleSaveUser}>
            <header>
              <span><FaUserShield aria-hidden="true" /></span>
              <div>
                <strong>{userDialog.mode === 'edit' ? 'Edit user' : 'Add user'}</strong>
                <small>{userDialog.mode === 'edit' ? userDialog.username : 'Create a dashboard login'}</small>
              </div>
              <button type="button" onClick={closeUserDialog} aria-label="Close user editor">×</button>
            </header>
            <label>
              <span>Username</span>
              <input
                placeholder="operator name"
                value={userDraft.username}
                onChange={(event) => setUserDraft((current) => ({ ...current, username: event.target.value }))}
                disabled={userDialog.mode === 'edit'}
                required
              />
            </label>
            <label>
              <span>{userDialog.mode === 'edit' ? 'New password' : 'Password'}</span>
              <input
                placeholder={userDialog.mode === 'edit' ? 'leave unchanged' : 'temporary password'}
                type="password"
                value={userDraft.password}
                onChange={(event) => setUserDraft((current) => ({ ...current, password: event.target.value }))}
                required={userDialog.mode !== 'edit'}
              />
            </label>
            <label>
              <span>Role</span>
              <select
                value={userDraft.role}
                onChange={(event) => setUserDraft((current) => ({ ...current, role: event.target.value }))}
              >
                <option value="admin">admin</option>
                <option value="operator">operator</option>
                <option value="viewer">viewer</option>
              </select>
            </label>
            <label className="runtime-admin-page__checkbox-row">
              <input
                type="checkbox"
                checked={userDraft.disabled}
                onChange={(event) => setUserDraft((current) => ({ ...current, disabled: event.target.checked }))}
              />
              <span>Disable this login</span>
            </label>
            <footer>
              <button type="button" className="runtime-admin-page__action-btn" onClick={closeUserDialog}>
                Cancel
              </button>
              <button type="submit" className="runtime-admin-page__action-btn runtime-admin-page__action-btn--primary">
                Save user
              </button>
            </footer>
          </form>
        </div>
      ) : null}

      {tokenDialogOpen ? (
        <div
          className="runtime-admin-page__dialog"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setTokenDialogOpen(false);
            }
          }}
        >
          <form className="runtime-admin-page__dialog-panel" role="dialog" aria-modal="true" aria-label="Create API token" onSubmit={handleCreateToken}>
            <header>
              <span><FaKey aria-hidden="true" /></span>
              <div>
                <strong>Create API token</strong>
                <small>For scripted tools or field diagnostics</small>
              </div>
              <button type="button" onClick={() => setTokenDialogOpen(false)} aria-label="Close token editor">×</button>
            </header>
            <label>
              <span>Purpose</span>
              <input
                placeholder="field debug token"
                value={tokenDraft.name}
                onChange={(event) => setTokenDraft((current) => ({ ...current, name: event.target.value }))}
                required
              />
            </label>
            <label>
              <span>Scopes</span>
              <input
                placeholder="operator,readonly"
                value={tokenDraft.scopes}
                onChange={(event) => setTokenDraft((current) => ({ ...current, scopes: event.target.value }))}
              />
            </label>
            <label>
              <span>TTL hours</span>
              <input
                aria-label="Token TTL hours"
                placeholder="4"
                type="number"
                min="1"
                max="8760"
                value={tokenDraft.ttl_hours}
                onChange={(event) => setTokenDraft((current) => ({ ...current, ttl_hours: event.target.value }))}
              />
            </label>
            <footer>
              <button type="button" className="runtime-admin-page__action-btn" onClick={() => setTokenDialogOpen(false)}>
                Cancel
              </button>
              <button type="submit" className="runtime-admin-page__action-btn runtime-admin-page__action-btn--primary">
                Create token
              </button>
            </footer>
          </form>
        </div>
      ) : null}
    </PageShell>
  );
}

export default RuntimeAdminPage;
