import React from 'react';
import {
  FaBookOpen,
  FaCodeBranch,
  FaKey,
  FaSatelliteDish,
  FaServer,
  FaWifi,
} from 'react-icons/fa';

import useGcsGitInfo from '../hooks/useGcsGitInfo';
import useGcsRuntimeStatus from '../hooks/useGcsRuntimeStatus';
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

function RuntimeAdminPage() {
  const runtime = useGcsRuntimeStatus();
  const gitInfo = useGcsGitInfo();

  const runtimeTone = runtime.mode === 'real' ? 'real' : runtime.mode === 'sitl' ? 'sitl' : 'neutral';
  const authHealthTone = formatAuthHealthTone(runtime.gitAuthHealth?.status);
  const docs = [
    { key: 'mds_init_setup', label: 'Bootstrap guide' },
    { key: 'fleet_sync_and_secrets', label: 'Fleet sync and secrets' },
    { key: 'mavlink_routing_setup', label: 'MAVLink routing' },
    { key: 'git_sync_feature', label: 'Git sync feature' },
  ].filter((entry) => runtime.docs?.[entry.key]);

  return (
    <div className="runtime-admin-page">
      <header className="runtime-admin-page__hero">
        <div>
          <span className="runtime-admin-page__eyebrow">System</span>
          <h1>Runtime Admin</h1>
          <p>
            Live GCS runtime posture, config authority, and fleet defaults. This is the operator-facing read surface
            for SITL/REAL mode, git access posture, and optional tool defaults before mutation controls are layered in.
          </p>
        </div>
        <div className="runtime-admin-page__hero-pills">
          <StatusPill tone={runtimeTone}>{runtime.modeLabel}</StatusPill>
          <StatusPill tone={runtime.gitAutoPush ? 'good' : 'warning'}>
            {runtime.gitAutoPush ? 'Auto-push on' : 'Auto-push off'}
          </StatusPill>
          <StatusPill>{formatRepoAccessModeLabel(runtime.repoAccessMode)}</StatusPill>
          <StatusPill tone={authHealthTone}>{runtime.gitAuthHealth?.status || 'unknown'} auth</StatusPill>
        </div>
      </header>

      {runtime.error ? (
        <div className="runtime-admin-page__banner runtime-admin-page__banner--warning">
          Runtime status could not be loaded. The page is showing the last safe fallback only.
        </div>
      ) : null}

      <section className="runtime-admin-page__grid">
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
              <dt>Install dir</dt>
              <dd>{runtime.installDir || 'Not reported'}</dd>
            </div>
            <div>
              <dt>System config</dt>
              <dd>{runtime.gcsConfigPath || 'Not reported'}</dd>
            </div>
          </dl>
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
            </div>
          ) : null}
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
            </div>
          ) : null}
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
            <li>Use this page to verify the live runtime posture before changing SITL/REAL mode or repo/auth settings.</li>
            <li>Runtime mutation controls are intentionally being promoted after the status layer so restart/update actions can be tied to explicit guardrails.</li>
            <li>Fleet defaults shown here are the git-tracked intent for future node bootstraps; node-local overrides still live in each host runtime env.</li>
          </ul>
        </article>
      </section>
    </div>
  );
}

export default RuntimeAdminPage;
