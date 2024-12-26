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
} from '@fortawesome/free-solid-svg-icons';

const DroneGitStatus = ({ gitStatus, droneName }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!gitStatus) {
    return <div className="git-status git-loading">Git status not available.</div>;
  }

  const isInSync = gitStatus.status === 'clean';

  const handleCopyCommit = () => {
    navigator.clipboard.writeText(gitStatus.commit).then(
      () => {
        alert('Commit hash copied to clipboard!');
      },
      (err) => {
        console.error('Could not copy text: ', err);
      }
    );
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
      </div>
      <div className="git-status-info">
        <div className="git-info-row">
          <span className="git-label">Branch:</span>
          <span className="git-value">{gitStatus.branch}</span>
        </div>
        <div className="git-info-row">
          <span className="git-label">Commit:</span>
          <span className="git-value commit-hash" onClick={handleCopyCommit} title="Click to copy commit hash" aria-label="Commit hash, click to copy">
            {gitStatus.commit.slice(0, 7)}
            <FontAwesomeIcon icon={faCopy} className="copy-icon" />
          </span>
        </div>
        <div className="git-info-row">
          
        </div>
      </div>
      {gitStatus.uncommitted_changes && gitStatus.uncommitted_changes.length > 0 && (
        <div className="git-status-details">
          <button
            className="toggle-details-button"
            onClick={() => setIsExpanded(!isExpanded)}
            aria-expanded={isExpanded}
            aria-controls={`git-details-${droneName}`}
          >
            {isExpanded ? (
              <>
                Hide Details <FontAwesomeIcon icon={faChevronUp} />
              </>
            ) : (
              <>
                Show Details <FontAwesomeIcon icon={faChevronDown} />
              </>
            )}
          </button>
          {isExpanded && (
            <div id={`git-details-${droneName}`} className="uncommitted-changes">
              <strong>Uncommitted Changes:</strong>
              <ul>
                {gitStatus.uncommitted_changes.map((change, index) => (
                  <li key={index}>{change}</li>
                ))}
              </ul>
              <span className="git-label">Status:</span>
              <span className="git-value">{gitStatus.status}</span>

            </div>
          )}
        </div>
      )}
      {!isInSync && <div className="git-warning">This drone's Git status is not in sync.</div>}
    </div>
  );
};

DroneGitStatus.propTypes = {
  gitStatus: PropTypes.shape({
    branch: PropTypes.string.isRequired,
    commit: PropTypes.string.isRequired,
    status: PropTypes.string.isRequired,
    uncommitted_changes: PropTypes.arrayOf(PropTypes.string),
  }),
  droneName: PropTypes.string.isRequired,
};

export default DroneGitStatus;
