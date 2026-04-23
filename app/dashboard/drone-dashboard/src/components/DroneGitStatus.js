import React, { useState } from 'react';
import PropTypes from 'prop-types';
import '../styles/DroneGitStatus.css';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faCheckCircle,
  faExclamationCircle,
  faChevronDown,
  faChevronUp,
  faCopy,
  faLink,
} from '@fortawesome/free-solid-svg-icons';
import { areGitRevisionsEquivalent } from '../utilities/missionIdentityUtils';

const formatRepoAccessMode = (value) => {
  switch (value) {
    case 'ssh_key':
      return 'SSH key';
    case 'https_token_file':
      return 'HTTPS token file';
    case 'https_public_or_read_only':
      return 'HTTPS public/read-only';
    case 'custom_or_unknown':
      return 'Custom/unknown';
    default:
      return value || 'Unknown';
  }
};

const formatDashboardAccess = (runtime) => {
  if (!runtime) {
    return 'Unknown';
  }
  if (runtime.dashboard_access_mode === 'disabled') {
    return 'Disabled';
  }
  if (runtime.dashboard_access_mode === 'local_only') {
    return 'Local only';
  }
  if (runtime.dashboard_access_mode === 'direct' && runtime.dashboard_url) {
    return 'Direct link';
  }
  return 'Unknown';
};

const renderRuntimeSummary = (runtime, type) => {
  if (!runtime) {
    return 'Unavailable';
  }

  if (type === 'mavlink') {
    return [
      runtime.management_mode || 'unknown',
      runtime.ref || 'unknown',
      `router ${runtime.router_service_status || 'unknown'}`,
      `dashboard ${formatDashboardAccess(runtime).toLowerCase()}`,
    ].join(' · ');
  }

  return [
    runtime.backend || 'unknown',
    runtime.mode || 'unknown',
    `service ${runtime.service_status || 'unknown'}`,
    `dashboard ${formatDashboardAccess(runtime).toLowerCase()}`,
  ].join(' · ');
};

const DroneGitStatus = ({ gitStatus, gcsGitStatus, droneName }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  // Handle missing git status gracefully
  if (!gitStatus || !gitStatus.branch) {
    return (
      <div className="git-status-card">
        <div className="git-status-header">
          <div className="status-indicator">
            <FontAwesomeIcon icon={faExclamationCircle} className="status-icon offline" title="Git Status Unavailable" />
          </div>
          <div className="git-basic-info">
            <span className="branch-name">Git Unavailable</span>
            <span className="commit-hash">N/A</span>
          </div>
        </div>
      </div>
    );
  }

  const isInSync = typeof gitStatus.in_sync_with_gcs === 'boolean'
    ? gitStatus.in_sync_with_gcs
    : (gcsGitStatus && gitStatus.commit && gcsGitStatus.commit
        ? areGitRevisionsEquivalent(gitStatus.commit, gcsGitStatus.commit)
        : false);

  const handleCopyCommit = async () => {
    if (!gitStatus.commit) {
      console.warn('No commit hash to copy');
      return;
    }

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(gitStatus.commit);
        setCopySuccess(true);
      } else {
        // Fallback for unsupported browsers
        const textarea = document.createElement('textarea');
        textarea.value = gitStatus.commit;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        setCopySuccess(true);
      }
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error('Could not copy text: ', err);
    }
  };

  const toggleDetails = () => {
    setIsExpanded(!isExpanded);
  };

  const gitAuthHealthStatus = gitStatus.git_auth_health_status || 'unknown';
  const gitAuthIssues = Array.isArray(gitStatus.git_auth_health_issues)
    ? gitStatus.git_auth_health_issues
    : [];
  const hasGitAuthWarning = gitAuthHealthStatus === 'warning' || gitAuthHealthStatus === 'error';

  // Add null checks for gitStatus.commit
  const shortCommitHash = gitStatus.commit ? gitStatus.commit.slice(0, 7) : 'N/A';

  return (
    <div className={`git-status-card ${isInSync ? 'sync' : 'not-sync'}`}>
      <div className="git-status-header">
        <div className="status-indicator">
          {isInSync ? (
            <FontAwesomeIcon icon={faCheckCircle} className="status-icon online" title="In Sync" aria-label="In Sync" />
          ) : (
            <FontAwesomeIcon icon={faExclamationCircle} className="status-icon dirty" title="Not In Sync" aria-label="Not In Sync" />
          )}
        </div>
        <div className="git-basic-info">
          <span className="branch-name" title={`Branch: ${gitStatus.branch || 'N/A'}`}>
            {gitStatus.branch || 'N/A'}
          </span>
          <span
            className="commit-hash"
            onClick={gitStatus.commit ? handleCopyCommit : undefined}
            title={gitStatus.commit ? "Click to copy full commit hash" : "No commit hash available"}
            aria-label={gitStatus.commit ? "Commit hash, click to copy" : "No commit hash available"}
            style={gitStatus.commit ? { cursor: 'pointer' } : { cursor: 'default', opacity: 0.6 }}
          >
            {shortCommitHash}
            {gitStatus.commit && <FontAwesomeIcon icon={faCopy} className="copy-icon" />}
            {copySuccess && <span className="copy-tooltip">Copied!</span>}
          </span>
        </div>
        <div className="details-toggle">
          <button
            className="toggle-button"
            onClick={toggleDetails}
            aria-expanded={isExpanded}
            aria-controls={`git-details-${droneName}`}
            title="Toggle Details"
            aria-label="Toggle Details"
          >
            <FontAwesomeIcon icon={isExpanded ? faChevronUp : faChevronDown} />
          </button>
        </div>
      </div>
      {isExpanded && (
        <div id={`git-details-${droneName}`} className="git-status-details">
          <div className="detail-row">
            <span className="detail-label">Full Hash</span>
            <span className="detail-value commit">{gitStatus.commit || 'N/A'}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Message</span>
            <span className="detail-value message">{gitStatus.commit_message || 'N/A'}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Date</span>
            <span className="detail-value">
              {gitStatus.commit_date
                ? new Date(gitStatus.commit_date).toLocaleString()
                : 'N/A'}
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Author</span>
            <span className="detail-value">
              {gitStatus.author_name && gitStatus.author_email
                ? `${gitStatus.author_name} <${gitStatus.author_email}>`
                : 'N/A'}
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Access</span>
            <span className="detail-value">
              {formatRepoAccessMode(gitStatus.repo_access_mode)}
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Auth</span>
            <span className={`detail-value git-auth-status git-auth-status-${gitAuthHealthStatus}`}>
              {gitStatus.git_auth_health_summary || 'N/A'}
            </span>
          </div>
          {gitStatus.mavlink_runtime && (
            <div className="detail-row">
              <span className="detail-label">MAVLink</span>
              <div className="detail-value runtime-detail-value">
                <span>{renderRuntimeSummary(gitStatus.mavlink_runtime, 'mavlink')}</span>
                <div className="runtime-detail-links">
                  {gitStatus.mavlink_runtime.repo_web_url && (
                    <a href={gitStatus.mavlink_runtime.repo_web_url} target="_blank" rel="noreferrer">
                      Repo
                    </a>
                  )}
                  {gitStatus.mavlink_runtime.dashboard_url && (
                    <a href={gitStatus.mavlink_runtime.dashboard_url} target="_blank" rel="noreferrer">
                      <FontAwesomeIcon icon={faLink} /> Dashboard
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}
          {gitStatus.connectivity_runtime && (
            <div className="detail-row">
              <span className="detail-label">Connectivity</span>
              <div className="detail-value runtime-detail-value">
                <span>{renderRuntimeSummary(gitStatus.connectivity_runtime, 'connectivity')}</span>
                <div className="runtime-detail-links">
                  {gitStatus.connectivity_runtime.repo_web_url && (
                    <a href={gitStatus.connectivity_runtime.repo_web_url} target="_blank" rel="noreferrer">
                      Repo
                    </a>
                  )}
                  {gitStatus.connectivity_runtime.dashboard_url && (
                    <a href={gitStatus.connectivity_runtime.dashboard_url} target="_blank" rel="noreferrer">
                      <FontAwesomeIcon icon={faLink} /> Dashboard
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}
          {gitStatus.git_sync_runtime && (
            <div className="detail-row">
              <span className="detail-label">Sync</span>
              <div className="detail-value runtime-detail-value">
                <span>{gitStatus.git_sync_runtime.summary || 'No sync runtime summary'}</span>
                {Array.isArray(gitStatus.git_sync_runtime.updated_units)
                  && gitStatus.git_sync_runtime.updated_units.length > 0 && (
                    <span className="runtime-detail-subtle">
                      Units: {gitStatus.git_sync_runtime.updated_units.join(', ')}
                    </span>
                  )}
              </div>
            </div>
          )}
          {gitAuthIssues.length > 0 && (
            <div className="detail-row">
              <span className="detail-label">Auth Issues</span>
              <ul className="changes-list">
                {gitAuthIssues.map((issue, index) => (
                  <li key={index}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
          {gitStatus.uncommitted_changes && gitStatus.uncommitted_changes.length > 0 && (
            <div className="detail-row">
              <span className="detail-label">Changes</span>
              <ul className="changes-list">
                {gitStatus.uncommitted_changes.map((change, index) => (
                  <li key={index}>{change}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {hasGitAuthWarning && (
        <div className={`git-warning git-auth-warning ${gitAuthHealthStatus}`}>
          {gitStatus.git_auth_health_summary || 'Git auth needs operator attention.'}
        </div>
      )}
      {!isInSync && (
        <div className="git-warning">
          Not in sync with GCS
          {gcsGitStatus?.commit && gitStatus.commit && (
            <span className="git-warning-detail">
              {' '}(drone: {gitStatus.commit.slice(0, 7)}, GCS: {gcsGitStatus.commit.slice(0, 7)})
            </span>
          )}
        </div>
      )}
    </div>
  );
};

DroneGitStatus.propTypes = {
  gitStatus: PropTypes.shape({
    branch: PropTypes.string,
    commit: PropTypes.string,
    status: PropTypes.string,
    in_sync_with_gcs: PropTypes.bool,
    commit_date: PropTypes.string,
    commit_message: PropTypes.string,
    author_name: PropTypes.string,
    author_email: PropTypes.string,
    uncommitted_changes: PropTypes.arrayOf(PropTypes.string),
    repo_access_mode: PropTypes.string,
    git_auth_health_status: PropTypes.string,
    git_auth_health_summary: PropTypes.string,
    git_auth_health_issues: PropTypes.arrayOf(PropTypes.string),
    mavlink_runtime: PropTypes.shape({
      management_mode: PropTypes.string,
      ref: PropTypes.string,
      repo_web_url: PropTypes.string,
      router_service_status: PropTypes.string,
      dashboard_access_mode: PropTypes.string,
      dashboard_url: PropTypes.string,
    }),
    connectivity_runtime: PropTypes.shape({
      backend: PropTypes.string,
      mode: PropTypes.string,
      service_status: PropTypes.string,
      repo_web_url: PropTypes.string,
      dashboard_access_mode: PropTypes.string,
      dashboard_url: PropTypes.string,
    }),
    git_sync_runtime: PropTypes.shape({
      status: PropTypes.string,
      summary: PropTypes.string,
      updated_units: PropTypes.arrayOf(PropTypes.string),
    }),
  }),
  gcsGitStatus: PropTypes.shape({
    commit: PropTypes.string,
  }),
  droneName: PropTypes.string.isRequired,
};

export default DroneGitStatus;
