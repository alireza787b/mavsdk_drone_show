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
} from '@fortawesome/free-solid-svg-icons';

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

  const isInSync = gcsGitStatus && gitStatus.commit && gcsGitStatus.commit
    ? String(gitStatus.commit).trim() === String(gcsGitStatus.commit).trim()
    : false;

  const handleCopyCommit = async () => {
    if (!gitStatus.commit) {
      console.warn('No commit hash to copy');
      return;
    }

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(gitStatus.commit);
        console.log('Copied to clipboard:', gitStatus.commit);
        setCopySuccess(true);
      } else {
        // Fallback for unsupported browsers
        const textarea = document.createElement('textarea');
        textarea.value = gitStatus.commit;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        console.log('Copied to clipboard using fallback:', gitStatus.commit);
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
      {!isInSync && <div className="git-warning">Git status is not in sync with GCS.</div>}
    </div>
  );
};

DroneGitStatus.propTypes = {
  gitStatus: PropTypes.shape({
    branch: PropTypes.string.isRequired,
    commit: PropTypes.string.isRequired,
    status: PropTypes.string.isRequired,
    commit_date: PropTypes.string.isRequired,
    commit_message: PropTypes.string.isRequired,
    author_name: PropTypes.string.isRequired,
    author_email: PropTypes.string.isRequired,
    uncommitted_changes: PropTypes.arrayOf(PropTypes.string),
  }),
  gcsGitStatus: PropTypes.shape({
    commit: PropTypes.string.isRequired,
  }),
  droneName: PropTypes.string.isRequired,
};

export default DroneGitStatus;