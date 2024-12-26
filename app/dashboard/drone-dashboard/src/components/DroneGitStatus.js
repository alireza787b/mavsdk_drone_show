// src/components/DroneGitStatus.js

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
  faInfoCircle,
} from '@fortawesome/free-solid-svg-icons';

const DroneGitStatus = ({ gitStatus, droneName }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  if (!gitStatus) {
    return <div className="git-status git-loading">Git status not available.</div>;
  }

  const isInSync = gitStatus.status === 'clean';

  const handleCopyCommit = async () => {
    try {
      await navigator.clipboard.writeText(gitStatus.commit);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000); // Reset after 2 seconds
    } catch (err) {
      console.error('Could not copy text: ', err);
    }
  };

  const toggleDetails = () => {
    setIsExpanded(!isExpanded);
  };

  return (
    <div className={`git-status-card ${isInSync ? 'sync' : 'not-sync'}`}>
      <div className="git-status-header">
        <div className="status-indicator">
          {isInSync ? (
            <FontAwesomeIcon icon={faCheckCircle} className="status-icon online" title="Clean" aria-label="Clean" />
          ) : (
            <FontAwesomeIcon icon={faExclamationCircle} className="status-icon dirty" title="Dirty" aria-label="Dirty" />
          )}
        </div>
        <div className="git-basic-info">
          <span className="branch-name">{gitStatus.branch}</span>
          <span className="commit-hash" onClick={handleCopyCommit} title="Click to copy full commit hash" aria-label="Commit hash, click to copy">
            {gitStatus.commit.slice(0, 7)}
            <FontAwesomeIcon icon={faCopy} className="copy-icon" />
          </span>
          {copySuccess && <span className="copy-tooltip">Copied!</span>}
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
            <span className="detail-label">Commit Message:</span>
            <span className="detail-value">{gitStatus.commit_message}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Commit Date:</span>
            <span className="detail-value">{new Date(gitStatus.commit_date).toLocaleString()}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Author:</span>
            <span className="detail-value">
              {gitStatus.author_name} &lt;{gitStatus.author_email}&gt;
            </span>
          </div>
          {gitStatus.uncommitted_changes && gitStatus.uncommitted_changes.length > 0 && (
            <div className="detail-row">
              <span className="detail-label">Uncommitted Changes:</span>
              <ul className="changes-list">
                {gitStatus.uncommitted_changes.map((change, index) => (
                  <li key={index}>{change}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {!isInSync && <div className="git-warning">Git status is not in sync.</div>}
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
  droneName: PropTypes.string.isRequired,
};

export default DroneGitStatus;
